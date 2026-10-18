# SPDX-License-Identifier: Apache-2.0
"""Keystone: effective params must be captured at the point of use, so an
adaptive clamp applied right before the operation is recorded as the value
ACTUALLY used — not the declared value re-read from the config."""

from clusterbench_core.domain import MeasureOutcome, PrepArtifact
from clusterbench_core.lifecycle import run_lifecycle
from clusterbench_core.model import BenchmarkConfig, PhaseMetrics, ResourceBudget, TreatmentVariable


class ClampDomain:
    """measure() clamps query_cut under 'memory pressure' and records the value it
    actually passes to the (simulated) search — at the point of use."""

    name = "clamp"

    def __init__(self, clamp_to):
        self.clamp_to = clamp_to

    def required_params(self):
        return {}

    def apply_config(self, cfg, ctx):
        return {}

    def verify_config(self, cfg, ctx):
        return {}

    def prep(self, cfg, ctx):
        return PrepArtifact(kind="clamp")

    def measure(self, cfg, prep, ctx):
        eff = getattr(ctx, "effective", lambda n, v: v)
        declared = int(cfg.get("clamp.query_cut"))
        used = min(declared, self.clamp_to)        # adaptive safety clamp
        qc = eff("clamp.query_cut", used)          # recorded AT POINT OF USE
        return MeasureOutcome(
            metrics={"p50_ms": 10.0 + qc, "peak_rss_kb": 1000},
            phases=[PhaseMetrics(name="search", duration_s=0.01)],
            functional_validation={"passed": True, "recall@10": 0.98},
        )


def _cfg(query_cut=10):
    c = BenchmarkConfig(domain="clamp", hypothesis="h",
                        treatment_variable=TreatmentVariable("clamp.query_cut", query_cut, query_cut))
    c.set_param("clamp.query_cut", query_cut)
    c.resource_budget = ResourceBudget(total_ram_kb=10_000, estimated_peak_kb=1000)
    return c


def test_effective_capture_records_clamped_value(tmp_path):
    lr = run_lifecycle(_cfg(query_cut=10), ClampDomain(clamp_to=2), workdir=tmp_path,
                       baseline=_cfg(query_cut=10))
    # declared 10, but the clamp used 2 — the manifest must show 2
    assert lr.result.effective_params["clamp.query_cut"] == 2


def test_effective_capture_matches_when_no_clamp(tmp_path):
    lr = run_lifecycle(_cfg(query_cut=10), ClampDomain(clamp_to=99), workdir=tmp_path,
                       baseline=_cfg(query_cut=10))
    assert lr.result.effective_params["clamp.query_cut"] == 10


def test_clamp_run_is_tagged_unreliable_with_diff(tmp_path):
    from clusterbench_core.model import ReliabilityTag
    lr = run_lifecycle(_cfg(query_cut=10), ClampDomain(clamp_to=2), workdir=tmp_path,
                       baseline=_cfg(query_cut=10))
    assert lr.result.reliability_tag is ReliabilityTag.UNRELIABLE
    assert lr.result.signature_diff["clamp.query_cut"] == {"declared": 10, "effective": 2}
    assert "EFFECTIVE != DECLARED" in " ".join(lr.result.notes)


class CapturesUndeclaredDomain(ClampDomain):
    """Captures an effective param that the config does NOT declare (like n_knn
    omitted from the manifest). Must NOT be treated as a deviation."""
    def measure(self, cfg, prep, ctx):
        eff = getattr(ctx, "effective", lambda n, v: v)
        eff("clamp.undeclared_knob", 0)   # not in cfg.params
        return super().measure(cfg, prep, ctx)


def test_undeclared_captured_param_does_not_false_trip(tmp_path):
    from clusterbench_core.model import ReliabilityTag
    lr = run_lifecycle(_cfg(query_cut=10), CapturesUndeclaredDomain(clamp_to=99),
                       workdir=tmp_path, baseline=_cfg(query_cut=10))
    assert lr.result.reliability_tag is not ReliabilityTag.UNRELIABLE
    assert "clamp.undeclared_knob" not in lr.result.signature_diff
