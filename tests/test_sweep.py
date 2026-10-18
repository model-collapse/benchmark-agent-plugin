from clusterbench_core.sweep import sweep
from clusterbench_core.model import RunStatus

from conftest import FakeDomain, make_base_config


def test_sweep_picks_fastest_point(tmp_path):
    # FakeDomain speed model: p50 = 50 - 40*value -> higher value is faster.
    base = make_base_config(0.7)
    sr = sweep(base, values=[0.1, 0.4, 0.7, 0.9], domain=FakeDomain(),
               workdir=tmp_path, primary_metric="p50_ms", minimize=True,
               quality_metric="recall@10", quality_floor=0.95)
    assert sr.best is not None
    assert sr.best.value == 0.9  # fastest
    assert sr.baseline_point.value == 0.7
    # speedup vs baseline (0.7 -> p50=22; 0.9 -> p50=14) ~1.57x
    assert sr.speedup > 1.3
    assert "BEST" in sr.render()


def test_sweep_respects_quality_floor(tmp_path):
    # Make recall fail for the fastest point by overriding the domain.
    class LowRecallAtFast(FakeDomain):
        def measure(self, cfg, prep, ctx):
            out = super().measure(cfg, prep, ctx)
            if float(cfg.treatment_variable.value) >= 0.9:
                out.functional_validation["recall@10"] = 0.80  # below floor
            return out

    base = make_base_config(0.7)
    sr = sweep(base, values=[0.4, 0.7, 0.9], domain=LowRecallAtFast(),
               workdir=tmp_path, quality_metric="recall@10", quality_floor=0.95)
    # 0.9 is fastest but fails the floor -> best must be 0.7
    assert sr.best.value == 0.7


def test_sweep_skips_oom_points(tmp_path):
    base = make_base_config(0.4)
    base.treatment_variable.baseline_value = 0.4
    from clusterbench_core.model import ResourceBudget
    base.resource_budget = ResourceBudget(total_ram_kb=10_000)
    sr = sweep(base, values=[0.4, 0.7, 1.0], domain=FakeDomain(oom_at=1.0),
               workdir=tmp_path, quality_metric=None, quality_floor=None)
    # value 1.0 OOMs (ABORTED_GUARDRAIL) -> excluded; fastest completed is 0.7
    statuses = {p.value: p.lifecycle.result.status for p in sr.points}
    assert statuses[1.0] is RunStatus.ABORTED_GUARDRAIL
    assert sr.best.value == 0.7
