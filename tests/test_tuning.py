"""Tuning search tests on deterministic domains with a real speed/quality tradeoff."""

from dataclasses import dataclass

from clusterbench_core.domain import MeasureOutcome, PrepArtifact
from clusterbench_core.model import (
    BenchmarkConfig,
    PhaseMetrics,
    ResourceBudget,
    TreatmentVariable,
)
from clusterbench_core.tuning import TuneDim, Tuner


@dataclass
class TradeoffDomain:
    """p50 decreases with a and b (both 'faster when higher'); recall falls once
    a exceeds 0.6, so the constrained optimum under a recall floor is a bounded a
    plus the largest b."""
    name: str = "tradeoff"

    def required_params(self):
        return {}

    def apply_config(self, cfg, ctx):
        return {}

    def verify_config(self, cfg, ctx):
        return {}

    def prep(self, cfg, ctx):
        return PrepArtifact(kind="t", meta={})

    def measure(self, cfg, prep, ctx) -> MeasureOutcome:
        a = float(cfg.get("p.a"))
        b = float(cfg.get("p.b", 0.0))
        p50 = round(50.0 - 40.0 * a - 10.0 * b, 4)
        recall = round(1.0 - 0.5 * max(0.0, a - 0.6), 4)
        return MeasureOutcome(
            metrics={"p50_ms": p50, "peak_rss_kb": 1000},
            phases=[PhaseMetrics(name="search", duration_s=p50 / 1000, peak_rss_kb=1000)],
            functional_validation={"passed": True, "recall@10": recall},
        )


def _base(a=0.0, b=0.0):
    cfg = BenchmarkConfig(domain="tradeoff", hypothesis="tune",
                          treatment_variable=TreatmentVariable("p.a", baseline_value=a, value=a))
    cfg.set_param("p.a", a, source="treatment")
    cfg.set_param("p.b", b, source="inherited")
    cfg.resource_budget = ResourceBudget(total_ram_kb=10_000, estimated_peak_kb=1000)
    return cfg


def test_grid_picks_fastest_feasible(tmp_path):
    tn = Tuner(_base(a=0.0), TradeoffDomain(), tmp_path, quality_floor=0.95)
    res = tn.grid(TuneDim("p.a", values=[0.0, 0.3, 0.6, 0.8, 1.0]))
    # a>0.6 -> recall<0.95 infeasible; fastest feasible is a=0.6
    assert res.best.params["p.a"] == 0.6
    assert res.best.quality >= 0.95
    assert res.improvement > 1.0  # faster than the a=0.0 start


def test_refine_converges_without_floor(tmp_path):
    tn = Tuner(_base(a=0.0), TradeoffDomain(), tmp_path, quality_metric=None, quality_floor=None)
    res = tn.refine(TuneDim("p.a", bounds=(0.0, 1.0)), points=4, rounds=3)
    # no floor -> fastest is a near 1.0; refinement should zoom toward it
    assert res.best.params["p.a"] >= 0.75
    assert len(res.trials) > 4  # multiple rounds actually searched
    assert res.improvement > 1.5


def test_refine_respects_floor(tmp_path):
    tn = Tuner(_base(a=0.0), TradeoffDomain(), tmp_path, quality_floor=0.95)
    res = tn.refine(TuneDim("p.a", bounds=(0.0, 1.0)), points=5, rounds=3)
    # recall(a) = 1 - 0.5*(a-0.6); floor 0.95 -> feasible up to a=0.7.
    # Refinement should land just inside the boundary (0.6 < a <= 0.7), beating
    # the coarse grid's best of 0.6.
    assert res.best.quality >= 0.95
    assert 0.6 < res.best.params["p.a"] <= 0.70


def test_coordinate_descent_multi_param(tmp_path):
    tn = Tuner(_base(a=0.0, b=0.0), TradeoffDomain(), tmp_path, quality_floor=0.95)
    res = tn.coordinate([TuneDim("p.a", values=[0.0, 0.3, 0.6, 0.9]),
                         TuneDim("p.b", values=[0.0, 0.5, 1.0])], max_passes=3)
    # b has no recall cost -> pushed to 1.0; a capped at 0.6 by the floor
    assert res.best.params["p.b"] == 1.0
    assert res.best.params["p.a"] == 0.6
    assert res.best.quality >= 0.95
    assert res.improvement > 1.0
    assert "RECOMMENDED" in res.render()
