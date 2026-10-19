# SPDX-License-Identifier: Apache-2.0
"""Issue #1: with replication, the Tuner must reject a sub-noise 'speedup' and
only select a difference that exceeds the measured noise (effect > noise)."""

from clusterbench_core.domain import MeasureOutcome, PrepArtifact
from clusterbench_core.model import BenchmarkConfig, PhaseMetrics, ResourceBudget, TreatmentVariable
from clusterbench_core.tuning import TuneDim, Tuner

# deterministic per-replicate jitter (indexed by repro_nonce) → stdev ~1.1
_NOISE = [1.5, -1.5, 1.0, -1.0, 0.5, -0.5, 0.0]


class NoisyDomain:
    name = "noisy"

    def required_params(self):
        return {}

    def apply_config(self, cfg, ctx):
        return {}

    def verify_config(self, cfg, ctx):
        return {}

    def prep(self, cfg, ctx):
        return PrepArtifact(kind="noisy")

    def measure(self, cfg, prep, ctx):
        v = float(cfg.treatment_variable.value)
        base = 50.0 - 10.0 * v                 # higher v → faster
        p50 = base + _NOISE[cfg.repro_nonce % len(_NOISE)]
        return MeasureOutcome(metrics={"p50_ms": p50, "peak_rss_kb": 1000},
                              phases=[PhaseMetrics(name="s", duration_s=0.01)],
                              functional_validation={"passed": True, "recall@10": 0.98})


def _cfg(v):
    c = BenchmarkConfig(domain="noisy", hypothesis="h",
                        treatment_variable=TreatmentVariable("noisy.v", 0.0, v))
    c.set_param("noisy.v", v)
    c.resource_budget = ResourceBudget(total_ram_kb=10_000, estimated_peak_kb=1000)
    return c


def _tuner(tmp, **kw):
    return Tuner(_cfg(0.0), NoisyDomain(), tmp, primary_metric="p50_ms", minimize=True,
                 quality_metric=None, quality_floor=None, replicates=7, mde=0.03, **kw)


def test_subnoise_difference_not_selected(tmp_path):
    # base 50 vs 49 (diff 1) < noise band → not a real improvement
    res = _tuner(tmp_path).grid(TuneDim("noisy.v", values=[0.0, 0.1]))
    assert res.best.params["noisy.v"] == 0.0        # baseline retained
    assert res.improvement is None or res.improvement < 1.03


def test_clear_difference_selected(tmp_path):
    # base 50 vs 40 (diff 10) >> noise → real improvement
    res = _tuner(tmp_path).grid(TuneDim("noisy.v", values=[0.0, 1.0]))
    assert res.best.params["noisy.v"] == 1.0
    assert res.improvement > 1.1
