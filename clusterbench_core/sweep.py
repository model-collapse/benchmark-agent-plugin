"""Hyperparameter sweep + speed optimization.

Fan a base BenchmarkConfig over a grid of treatment-variable values, run one
lifecycle per point (each one preflight-gated against the baseline so only the
treatment differs), then pick the fastest point that still clears a quality
floor. This is the "tune a hyperparameter, optimize speed" deliverable.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clusterbench_core.lifecycle import LifecycleResult, run_lifecycle
from clusterbench_core.model import BenchmarkConfig, RunStatus


@dataclass
class SweepPoint:
    value: Any
    lifecycle: LifecycleResult

    @property
    def primary(self) -> float | None:
        return None

    def metric(self, name: str) -> float | None:
        r = self.lifecycle.result
        if name in r.metrics:
            return r.metrics[name]
        return r.functional_validation.get(name)


@dataclass
class SweepResult:
    treatment: str
    primary_metric: str
    minimize: bool
    points: list[SweepPoint] = field(default_factory=list)
    best: SweepPoint | None = None
    baseline_point: SweepPoint | None = None

    @property
    def speedup(self) -> float | None:
        """baseline_primary / best_primary (for a minimized latency/time metric,
        >1 means the best point is faster)."""
        if not (self.best and self.baseline_point):
            return None
        b = self.baseline_point.metric(self.primary_metric)
        x = self.best.metric(self.primary_metric)
        if not b or not x:
            return None
        return (b / x) if self.minimize else (x / b)

    def render(self) -> str:
        L = [f"Sweep over {self.treatment} (optimize {self.primary_metric}, "
             f"{'min' if self.minimize else 'max'}):"]
        for p in self.points:
            m = p.metric(self.primary_metric)
            rec = p.metric("recall@10")
            tag = p.lifecycle.result.reliability_tag.value
            star = "  <-- BEST" if p is self.best else ""
            rec_s = f" recall@10={rec}" if rec is not None else ""
            L.append(f"  {self.treatment}={p.value}: {self.primary_metric}={m}{rec_s} "
                     f"status={p.lifecycle.result.status.value} [{tag}]{star}")
        if self.speedup:
            L.append(f"Speedup vs baseline: {self.speedup:.2f}x "
                     f"(baseline {self.treatment}={self.baseline_point.value})")
        return "\n".join(L)


def _clone_with_treatment(base: BenchmarkConfig, value: Any) -> BenchmarkConfig:
    cfg = BenchmarkConfig.from_dict(copy.deepcopy(base.to_dict()))
    tv = cfg.treatment_variable
    tv.value = value
    cfg.set_param(tv.name, value, source="treatment")
    return cfg


def sweep(
    base: BenchmarkConfig,
    values: list[Any],
    domain,
    ctx=None,
    workdir: str | Path = "./clusterbench_data/runs",
    primary_metric: str = "p50_ms",
    minimize: bool = True,
    quality_metric: str | None = "recall@10",
    quality_floor: float | None = None,
    apply: bool = True,
) -> SweepResult:
    baseline_value = base.treatment_variable.baseline_value
    baseline_cfg = _clone_with_treatment(base, baseline_value)

    sr = SweepResult(treatment=base.treatment_variable.name,
                     primary_metric=primary_metric, minimize=minimize)

    for v in values:
        cfg = _clone_with_treatment(base, v)
        lr = run_lifecycle(cfg, domain, ctx=ctx, workdir=workdir,
                           baseline=baseline_cfg, apply=apply)
        pt = SweepPoint(value=v, lifecycle=lr)
        sr.points.append(pt)
        if v == baseline_value:
            sr.baseline_point = pt

    # candidates: completed runs that clear the quality floor
    def clears_floor(p: SweepPoint) -> bool:
        if quality_floor is None or quality_metric is None:
            return True
        q = p.metric(quality_metric)
        return q is not None and q >= quality_floor

    candidates = [
        p for p in sr.points
        if p.lifecycle.result.status is RunStatus.COMPLETED
        and p.metric(primary_metric) is not None
        and clears_floor(p)
    ]
    if candidates:
        sr.best = (min if minimize else max)(
            candidates, key=lambda p: p.metric(primary_metric)
        )
    return sr
