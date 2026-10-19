# SPDX-License-Identifier: Apache-2.0
"""Loop guard: the search never recommends from an unfair trial, halts (and ASKs)
on a broken experiment, respects budgets, stops on no-progress, and terminates."""

from clusterbench_core.domain import MeasureOutcome, PrepArtifact
from clusterbench_core.model import BenchmarkConfig, PhaseMetrics, ResourceBudget, TreatmentVariable
from clusterbench_core.tuning import HaltReason, LoopBudget, TuneDim, Tuner


class GateDomain:
    """measure clamps gate.x above a threshold → effective!=declared → the trial is
    non-comparable (UNRELIABLE). Baselines at/below the threshold stay comparable."""
    name = "gate"

    def __init__(self, clamp_above):
        self.clamp_above = clamp_above

    def required_params(self):
        return {}

    def apply_config(self, cfg, ctx):
        return {}

    def verify_config(self, cfg, ctx):
        return {}

    def prep(self, cfg, ctx):
        return PrepArtifact(kind="gate")

    def measure(self, cfg, prep, ctx):
        eff = getattr(ctx, "effective", lambda n, v: v)
        declared = int(cfg.get("gate.x"))
        used = declared if declared <= self.clamp_above else self.clamp_above
        x = eff("gate.x", used)
        return MeasureOutcome(metrics={"p50_ms": 50 - x, "peak_rss_kb": 1000},
                              phases=[PhaseMetrics(name="s", duration_s=0.01)],
                              functional_validation={"passed": True, "recall@10": 0.98})


class FlatDomain:
    name = "flat"

    def required_params(self):
        return {}

    def apply_config(self, cfg, ctx):
        return {}

    def verify_config(self, cfg, ctx):
        return {}

    def prep(self, cfg, ctx):
        return PrepArtifact(kind="flat")

    def measure(self, cfg, prep, ctx):
        return MeasureOutcome(metrics={"p50_ms": 10.0, "peak_rss_kb": 1000},
                              phases=[PhaseMetrics(name="s", duration_s=0.01)],
                              functional_validation={"passed": True, "recall@10": 0.98})


def _cfg(domain, param, baseline, value):
    c = BenchmarkConfig(domain=domain, hypothesis="h",
                        treatment_variable=TreatmentVariable(param, baseline, value))
    c.set_param(param, value)
    c.resource_budget = ResourceBudget(total_ram_kb=10_000, estimated_peak_kb=1000)
    return c


def _tuner(domain, base, **kw):
    return Tuner(base, domain, kw.pop("tmp"), primary_metric="p50_ms", minimize=True,
                 quality_metric=None, quality_floor=None, **kw)


def test_baseline_ungrounded_halts_and_asks(tmp_path):
    base = _cfg("gate", "gate.x", baseline=1, value=1)
    tn = _tuner(GateDomain(clamp_above=0), base, tmp=tmp_path)  # baseline x=1 > 0 → clamped
    res = tn.grid(TuneDim("gate.x", values=[1, 5, 6, 7]))
    assert res.halt.reason is HaltReason.BASELINE_UNGROUNDED
    assert res.halt.needs_human
    assert res.recommendation is None


def test_noncomparable_streak_halts_asks_and_recommends_nothing(tmp_path):
    base = _cfg("gate", "gate.x", baseline=1, value=1)
    tn = _tuner(GateDomain(clamp_above=1), base, tmp=tmp_path)  # baseline x=1 ok; >1 clamped
    res = tn.grid(TuneDim("gate.x", values=[1, 5, 6, 7, 8]))
    assert res.halt.reason is HaltReason.NONCOMPARABLE_STREAK
    assert res.halt.needs_human
    # the faster (lower p50) trials are all non-comparable → never selected
    assert res.recommendation is None
    assert all(not t.comparable for t in res.trials if t.params["gate.x"] != 1)


def test_budget_trials_auto_halts(tmp_path):
    base = _cfg("flat", "flat.x", baseline=0, value=0)
    tn = _tuner(FlatDomain(), base, tmp=tmp_path, budget=LoopBudget(max_trials=2))
    res = tn.grid(TuneDim("flat.x", values=[0, 1, 2, 3, 4, 5]))
    assert res.halt.reason is HaltReason.BUDGET_TRIALS
    assert len(res.trials) <= 2 and not res.halt.needs_human


def test_no_progress_auto_halts(tmp_path):
    base = _cfg("flat", "flat.x", baseline=0, value=0)
    tn = _tuner(FlatDomain(), base, tmp=tmp_path, budget=LoopBudget(no_progress_m=3))
    res = tn.grid(TuneDim("flat.x", values=[0, 1, 2, 3, 4, 5, 6, 7]))
    assert res.halt.reason is HaltReason.NO_PROGRESS
    assert not res.halt.needs_human
    assert res.recommendation is not None  # baseline is comparable & feasible


def test_loop_always_terminates(tmp_path):
    base = _cfg("gate", "gate.x", baseline=1, value=1)
    tn = _tuner(GateDomain(clamp_above=100), base, tmp=tmp_path)  # all comparable
    res = tn.grid(TuneDim("gate.x", values=list(range(1, 20))))
    assert res.halt is not None
    assert len(res.trials) <= tn.budget.hard_cap


def test_memory_metric_not_selected_when_noncomparable(tmp_path):
    # selecting on peak_rss_kb while in-process (memory_comparable False) must
    # yield NO recommendation — never pick on a contaminated memory metric
    from conftest import FakeDomain, make_base_config
    base = make_base_config(0.3)
    tn = Tuner(base, FakeDomain(), tmp_path, primary_metric="peak_rss_kb", minimize=True,
               quality_metric=None, quality_floor=None)
    res = tn.grid(TuneDim("fake.heap_factor", values=[0.3, 0.6, 0.9]))
    assert res.recommendation is None
    assert all(not t.memory_comparable for t in res.trials)
