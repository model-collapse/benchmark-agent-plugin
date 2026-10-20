from benchmark_engine.tuning import Tuner, TuneDim, LoopBudget, HaltReason
from benchmark_engine.domain import MeasureOutcome, PrepArtifact

from conftest import make_base_config


class GpuDomain:
    name = "fake"

    def required_params(self):
        return {}

    def apply_config(self, cfg, ctx):
        return {}

    def verify_config(self, cfg, ctx):
        return {}

    def prep(self, cfg, ctx):
        return PrepArtifact(kind="fake")

    def measure(self, cfg, prep, ctx):
        return MeasureOutcome(metrics={"p50_ms": 10.0, "gpu_hours": 1.0},
                              functional_validation={"passed": True, "recall@10": 0.99})


def test_halts_on_gpu_hour_budget(tmp_path):
    base = make_base_config(0.7)
    t = Tuner(base, GpuDomain(), str(tmp_path), primary_metric="p50_ms", minimize=True,
              quality_metric="recall@10", quality_floor=0.0,
              budget=LoopBudget(max_gpu_hours=2.5, hard_cap=64))
    res = t.grid(TuneDim("fake.heap_factor", values=[0.7, 0.8, 0.9, 1.0, 1.1, 1.2]))
    assert res.halt.reason is HaltReason.BUDGET_GPU_HOURS
    assert res.halt.total_trials <= 3            # ~2.5 gpu-hours ⇒ stop after 3 trials
