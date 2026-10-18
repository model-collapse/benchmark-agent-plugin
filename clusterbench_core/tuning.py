# SPDX-License-Identifier: Apache-2.0
"""Hyperparameter tuning + loop guard.

Three search strategies (grid / refine / coordinate), each reusing the lifecycle
so every trial is manifest-gated, preflight-checked, guarded, and persisted.

The loop guard (§12.3) guarantees the search never churns on invalid, non-
comparable runs and never recommends from an unfair comparison. One predicate
drives everything:

    comparable := status == COMPLETED
              AND reliability_tag in {RELIABLE, QUALIFIED}
              AND effective_signature == declared_signature   (no signature_diff)

`_better()` only accepts a comparable trial, so the recommendation is always a
comparable, floor-passing trial or None. The loop halts (and for broken-
experiment cases ASKs a human) on a non-comparable streak, an ungrounded
baseline, budget exhaustion, or no measurable progress.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from clusterbench_core.lifecycle import run_lifecycle
from clusterbench_core.model import BenchmarkConfig, ReliabilityTag, RunStatus

_COMPARABLE_TAGS = (ReliabilityTag.RELIABLE, ReliabilityTag.QUALIFIED)


class HaltReason(str, Enum):
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"
    BASELINE_UNGROUNDED = "BASELINE_UNGROUNDED"
    NONCOMPARABLE_STREAK = "NONCOMPARABLE_STREAK"
    BUDGET_TRIALS = "BUDGET_TRIALS"
    BUDGET_WALLCLOCK = "BUDGET_WALLCLOCK"
    BUDGET_ABORTS = "BUDGET_ABORTS"
    NO_PROGRESS = "NO_PROGRESS"


# reasons that mean "the experiment is broken", not "finished"
_ASK = {HaltReason.BASELINE_UNGROUNDED, HaltReason.NONCOMPARABLE_STREAK}


@dataclass
class LoopBudget:
    max_trials: int | None = None     # None ⇒ strategy-derived, capped at hard_cap
    hard_cap: int = 64
    wall_budget_s: float = 7200.0
    max_aborts: int = 5
    streak_k: int = 3
    no_progress_m: int = 5


@dataclass
class TuneDim:
    name: str
    values: list[Any] | None = None
    bounds: tuple[float, float] | None = None


@dataclass
class Trial:
    params: dict[str, Any]
    primary: float | None
    quality: float | None
    feasible: bool
    status: str
    run_id: str
    comparable: bool = False
    reliability_tag: str = ""
    signature_diff: dict = field(default_factory=dict)
    memory_comparable: bool = False


@dataclass
class HaltReport:
    reason: HaltReason
    message: str
    needs_human: bool
    offending_trials: list[Trial]
    comparable_count: int
    total_trials: int
    recommendation_safe: bool


@dataclass
class TuningResult:
    primary_metric: str
    minimize: bool
    quality_metric: str | None
    quality_floor: float | None
    strategy: str
    trials: list[Trial] = field(default_factory=list)
    best: Trial | None = None
    start: Trial | None = None
    halt: HaltReport | None = None
    comparable: list[Trial] = field(default_factory=list)

    @property
    def recommendation(self) -> Trial | None:
        return self.best if (self.halt and self.halt.recommendation_safe) else None

    @property
    def improvement(self) -> float | None:
        if not (self.best and self.start and self.best.primary and self.start.primary):
            return None
        return (self.start.primary / self.best.primary) if self.minimize \
            else (self.best.primary / self.start.primary)

    def render(self) -> str:
        L = [f"Tuning [{self.strategy}] optimize {self.primary_metric} "
             f"({'min' if self.minimize else 'max'})"
             + (f" s.t. {self.quality_metric} >= {self.quality_floor:.4f}"
                if self.quality_floor is not None else "")]
        for i, t in enumerate(self.trials):
            tags = []
            if not t.comparable:
                tags.append("non-comparable")
            elif not t.feasible:
                tags.append("below-floor")
            star = "  <-- RECOMMENDED" if t is self.best else ""
            L.append(f"  [{i:02d}] {t.params}: {self.primary_metric}={t.primary} "
                     f"{self.quality_metric}={t.quality} [{t.reliability_tag}]"
                     f"{' ' + '/'.join(tags) if tags else ''}{star}")
        if self.halt:
            L.append(f"Halt: {self.halt.reason.value}"
                     + (" (NEEDS HUMAN)" if self.halt.needs_human else ""))
        if self.improvement and self.recommendation is not None:
            L.append(f"Recommended config: {self.best.params}")
            L.append(f"Improvement vs start {self.start.params}: {self.improvement:.2f}x")
        return "\n".join(L)


class Tuner:
    def __init__(self, base: BenchmarkConfig, domain, workdir: str | Path,
                 primary_metric="p50_ms", minimize=True,
                 quality_metric: str | None = "recall@10", quality_floor: float | None = None,
                 apply=True, budget: LoopBudget | None = None):
        self.base = base
        self.domain = domain
        self.workdir = workdir
        self.primary_metric = primary_metric
        self.minimize = minimize
        self.quality_metric = quality_metric
        self.quality_floor = quality_floor
        self.apply = apply
        self.budget = budget or LoopBudget()
        self._cache: dict[tuple, Trial] = {}

    # ---- guard state ----
    def _reset_guard(self, max_trials: int):
        self.trials: list[Trial] = []
        self._cache = {}
        self._streak = 0
        self._aborts = 0
        self._since_improve = 0
        self._wall_start = time.time()
        self._halt: HaltReason | None = None
        self._max_trials = min(max_trials, self.budget.hard_cap) \
            if self.budget.max_trials is None else min(self.budget.max_trials, self.budget.hard_cap)

    def _comparable(self, t: Trial) -> bool:
        return t.comparable

    # ---- evaluation ----
    def _metric(self, result, name):
        if name in result.metrics:
            return result.metrics[name]
        return result.functional_validation.get(name)

    def _eval(self, coords: dict[str, Any], incumbent: dict[str, Any], treatment: str) -> Trial:
        key = tuple(sorted(coords.items()))
        if key in self._cache:
            return self._cache[key]
        cfg = BenchmarkConfig.from_dict(copy.deepcopy(self.base.to_dict()))
        for name, val in coords.items():
            cfg.set_param(name, val, source="treatment" if name == treatment else "inherited")
        cfg.treatment_variable.name = treatment
        cfg.treatment_variable.value = coords[treatment]
        cfg.treatment_variable.baseline_value = incumbent.get(treatment)
        baseline_cfg = BenchmarkConfig.from_dict(copy.deepcopy(self.base.to_dict()))
        for name, val in incumbent.items():
            baseline_cfg.set_param(name, val)
        baseline_cfg.treatment_variable.name = treatment
        baseline_cfg.treatment_variable.value = incumbent.get(treatment)

        lr = run_lifecycle(cfg, self.domain, workdir=self.workdir,
                           baseline=baseline_cfg, apply=self.apply)
        r = lr.result
        completed = r.status is RunStatus.COMPLETED
        primary = self._metric(r, self.primary_metric) if completed else None
        quality = self._metric(r, self.quality_metric) if self.quality_metric else None
        feasible = (
            completed and primary is not None
            and (self.quality_floor is None or (quality is not None and quality >= self.quality_floor))
        )
        comparable = completed and r.reliability_tag in _COMPARABLE_TAGS and not r.signature_diff
        trial = Trial(params=dict(coords), primary=primary, quality=quality, feasible=feasible,
                      status=r.status.value, run_id=r.run_id, comparable=comparable,
                      reliability_tag=r.reliability_tag.value, signature_diff=dict(r.signature_diff),
                      memory_comparable=bool(r.measurement_flags.get("memory_comparable", False)))
        self._cache[key] = trial
        self.trials.append(trial)
        self._record(trial)
        return trial

    def _record(self, t: Trial):
        if t.comparable:
            self._streak = 0
        else:
            self._streak += 1
            if t.status.startswith("ABORTED") or t.status == "FAILED":
                self._aborts += 1

    def _check_halt(self) -> HaltReason | None:
        if self._halt:
            return self._halt
        b = self.budget
        if self._streak >= b.streak_k:
            self._halt = HaltReason.NONCOMPARABLE_STREAK
        elif self._aborts >= b.max_aborts:
            self._halt = HaltReason.BUDGET_ABORTS
        elif len(self.trials) >= self._max_trials:
            self._halt = HaltReason.BUDGET_TRIALS
        elif (time.time() - self._wall_start) >= b.wall_budget_s:
            self._halt = HaltReason.BUDGET_WALLCLOCK
        elif self._since_improve >= b.no_progress_m:
            self._halt = HaltReason.NO_PROGRESS
        return self._halt

    def _consider(self, t: Trial, best: Trial | None) -> Trial | None:
        if self._better(t, best):
            self._since_improve = 0
            return t
        if t.comparable:
            self._since_improve += 1
        return best

    _MEMORY_METRICS = ("peak_rss_kb", "rss_kb")

    def _better(self, a: Trial, b: Trial | None) -> bool:
        if not (self._comparable(a) and a.feasible):   # safety: only comparable can win
            return False
        # never select on a memory metric that is not per-trial attributable
        if self.primary_metric in self._MEMORY_METRICS and not a.memory_comparable:
            return False
        if b is None:
            return True
        return (a.primary < b.primary) if self.minimize else (a.primary > b.primary)

    # ---- strategies ----
    def grid(self, dim: TuneDim) -> TuningResult:
        self._reset_guard(len(dim.values))
        start_val = self.base.treatment_variable.baseline_value
        start_trial = self._eval({dim.name: start_val}, {dim.name: start_val}, dim.name)
        if not start_trial.comparable:
            self._halt = HaltReason.BASELINE_UNGROUNDED
            return self._result("grid", None, start_trial)
        best = self._consider(start_trial, None)   # baseline goes through the same gate
        for v in dim.values:
            if v == start_val:
                continue
            t = self._eval({dim.name: v}, {dim.name: start_val}, dim.name)
            best = self._consider(t, best)
            if self._check_halt():
                break
        return self._result("grid", best, start_trial)

    def refine(self, dim: TuneDim, points=4, rounds=3) -> TuningResult:
        self._reset_guard(points * rounds)
        lo, hi = dim.bounds
        start_val = self.base.treatment_variable.baseline_value
        start_trial = self._eval({dim.name: start_val}, {dim.name: start_val}, dim.name)
        if not start_trial.comparable:
            self._halt = HaltReason.BASELINE_UNGROUNDED
            return self._result("refine", None, start_trial)
        best = self._consider(start_trial, None)   # baseline goes through the same gate
        for _ in range(rounds):
            self._since_improve = 0   # each zoom level is a fresh search neighborhood
            grid = [round(lo + (hi - lo) * i / (points - 1), 4) for i in range(points)]
            for v in grid:
                t = self._eval({dim.name: v}, {dim.name: start_val}, dim.name)
                best = self._consider(t, best)
                if self._check_halt():
                    break
            if self._halt or best is None:
                break
            bv = best.params[dim.name]
            span = (hi - lo) / 2.0
            lo, hi = max(dim.bounds[0], bv - span / 2), min(dim.bounds[1], bv + span / 2)
        return self._result("refine", best, start_trial)

    def coordinate(self, dims: list[TuneDim], max_passes=3) -> TuningResult:
        total = max_passes * sum(len(d.values) for d in dims)
        self._reset_guard(total)
        incumbent = {d.name: self.base.get(d.name) for d in dims}
        start_trial = self._eval(dict(incumbent), dict(incumbent), dims[0].name)
        if not start_trial.comparable:
            self._halt = HaltReason.BASELINE_UNGROUNDED
            return self._result("coordinate", None, start_trial)
        best = self._consider(start_trial, None)   # baseline goes through the same gate
        for _ in range(max_passes):
            self._since_improve = 0   # each coordinate pass is a fresh sweep
            changed = False
            for d in dims:
                for v in d.values:
                    cand = dict(incumbent)
                    cand[d.name] = v
                    t = self._eval(cand, dict(incumbent), treatment=d.name)
                    nb = self._consider(t, best)
                    if nb is t and nb is not best:
                        best = nb
                        incumbent = dict(cand)
                        changed = True
                    if self._check_halt():
                        break
                if self._halt:
                    break
            if self._halt or not changed:
                break
        return self._result("coordinate", best, start_trial)

    def _result(self, strategy, best, start_trial) -> TuningResult:
        reason = self._halt or HaltReason.SEARCH_EXHAUSTED
        comparable = [t for t in self.trials if t.comparable]
        rec_safe = (best is not None and best.comparable and best.feasible
                    and reason not in _ASK)
        offending = [t for t in self.trials if not t.comparable] if reason in _ASK else []
        halt = HaltReport(
            reason=reason,
            message=_halt_message(reason),
            needs_human=reason in _ASK,
            offending_trials=offending,
            comparable_count=len(comparable),
            total_trials=len(self.trials),
            recommendation_safe=rec_safe,
        )
        return TuningResult(
            primary_metric=self.primary_metric, minimize=self.minimize,
            quality_metric=self.quality_metric, quality_floor=self.quality_floor,
            strategy=strategy, trials=list(self.trials), best=best, start=start_trial,
            halt=halt, comparable=comparable,
        )


def _halt_message(reason: HaltReason) -> str:
    return {
        HaltReason.SEARCH_EXHAUSTED: "search space fully explored",
        HaltReason.BASELINE_UNGROUNDED: "baseline trial is non-comparable — re-establish it before tuning",
        HaltReason.NONCOMPARABLE_STREAK: "too many consecutive non-comparable/aborted trials — experiment is broken",
        HaltReason.BUDGET_TRIALS: "trial budget exhausted",
        HaltReason.BUDGET_WALLCLOCK: "wall-clock budget exhausted",
        HaltReason.BUDGET_ABORTS: "abort budget exhausted",
        HaltReason.NO_PROGRESS: "no comparable trial improved over the last M trials",
    }[reason]
