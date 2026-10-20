from benchmark_engine.tuning import Tuner, TuneDim
from benchmark_engine.domain import MeasureOutcome, PrepArtifact

from conftest import make_base_config


class SeedSignalDomain:
    """p50 has a strong, real heap_factor signal plus tiny seed noise."""
    name = "fake"

    def required_params(self): return {}
    def apply_config(self, cfg, ctx): return {}
    def verify_config(self, cfg, ctx): return {}
    def prep(self, cfg, ctx): return PrepArtifact(kind="fake")

    def measure(self, cfg, prep, ctx):
        hf = float(cfg.get("fake.heap_factor"))
        seed = int(cfg.get("fake.seed", 0))
        p50 = 20.0 - 10.0 * hf + (0.05 if seed % 2 else -0.05)   # real signal, tiny noise
        return MeasureOutcome(metrics={"p50_ms": p50},
                              functional_validation={"passed": True, "recall@10": 0.99})


class SeedNoisyDomain:
    """p50 is pure seed noise with NO real heap_factor signal."""
    name = "fake"

    def required_params(self): return {}
    def apply_config(self, cfg, ctx): return {}
    def verify_config(self, cfg, ctx): return {}
    def prep(self, cfg, ctx): return PrepArtifact(kind="fake")

    def measure(self, cfg, prep, ctx):
        seed = int(cfg.get("fake.seed", 0))
        p50 = 10.0 + (3.0 if seed % 2 else -3.0)
        return MeasureOutcome(metrics={"p50_ms": p50},
                              functional_validation={"passed": True, "recall@10": 0.99})


def _tuner(domain, tmp_path):
    base = make_base_config(0.7)
    base.set_param("fake.seed", 0, source="controlled")
    return Tuner(base, domain, str(tmp_path), primary_metric="p50_ms", minimize=True,
                 quality_metric="recall@10", quality_floor=0.0,
                 seed_param="fake.seed", seeds=[1, 2, 3, 4])


def test_seed_replication_runs_and_selects_real_signal(tmp_path):
    # the seeded runs must COMPLETE (not abort) and a real cross-seed signal is selected
    res = _tuner(SeedSignalDomain(), tmp_path).grid(TuneDim("fake.heap_factor", values=[0.7, 0.9]))
    assert res.comparable, "seeded runs must produce comparable trials (not all abort)"
    assert res.recommendation is not None
    assert res.improvement is not None and res.improvement > 1.0


def test_single_seed_luck_not_selected(tmp_path):
    # pure seed noise ⇒ no real improvement selected
    res = _tuner(SeedNoisyDomain(), tmp_path).grid(TuneDim("fake.heap_factor", values=[0.7, 0.9]))
    assert res.recommendation is None or res.improvement is None or res.improvement <= 1.0
