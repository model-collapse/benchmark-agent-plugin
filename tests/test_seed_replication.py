from benchmark_engine.tuning import Tuner, TuneDim
from benchmark_engine.domain import MeasureOutcome, PrepArtifact

from conftest import make_base_config


class SeedNoisyDomain:
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
        seed = int(cfg.get("fake.seed", 0))
        # p50 is pure seed noise with NO real dependence on heap_factor
        p50 = 10.0 + (3.0 if seed % 2 else -3.0)
        return MeasureOutcome(metrics={"p50_ms": p50},
                              functional_validation={"passed": True, "recall@10": 0.99})


def test_single_seed_luck_not_selected(tmp_path):
    base = make_base_config(0.7)
    base.set_param("fake.seed", 0, source="controlled")
    t = Tuner(base, SeedNoisyDomain(), str(tmp_path), primary_metric="p50_ms", minimize=True,
              quality_metric="recall@10", quality_floor=0.0,
              seed_param="fake.seed", seeds=[1, 2, 3, 4])
    res = t.grid(TuneDim("fake.heap_factor", values=[0.7, 0.9]))
    # p50 has no real heap_factor signal across seeds ⇒ no comparable improvement selected
    assert res.recommendation is None or res.improvement is None or res.improvement <= 1.0
