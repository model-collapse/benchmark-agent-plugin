# SPDX-License-Identifier: Apache-2.0
"""Data-integrity-derived `passed`: a run that drops work must not pass."""

from clusterbench_core.domain import MeasureOutcome, PrepArtifact
from clusterbench_core.lifecycle import run_lifecycle
from clusterbench_core.model import (
    BenchmarkConfig,
    PhaseMetrics,
    ReliabilityTag,
    ResourceBudget,
    TreatmentVariable,
)


class IngestDomain:
    name = "ingest"

    def __init__(self, actual_docs, expected_docs=1000):
        self.actual_docs = actual_docs
        self.expected_docs = expected_docs

    def required_params(self):
        return {}

    def apply_config(self, cfg, ctx):
        return {}

    def verify_config(self, cfg, ctx):
        return {}

    def prep(self, cfg, ctx):
        return PrepArtifact(kind="ingest")

    def measure(self, cfg, prep, ctx):
        passed = self.actual_docs == self.expected_docs
        return MeasureOutcome(
            metrics={"p50_ms": 10.0, "peak_rss_kb": 1000},
            phases=[PhaseMetrics(name="search", duration_s=0.01)],
            functional_validation={"passed": passed, "recall@10": 0.98,
                                   "doc_count": self.actual_docs, "expected_docs": self.expected_docs},
        )


def _cfg():
    c = BenchmarkConfig(domain="ingest", hypothesis="h",
                        treatment_variable=TreatmentVariable("ingest.x", 1, 1))
    c.set_param("ingest.x", 1)
    c.resource_budget = ResourceBudget(total_ram_kb=10_000, estimated_peak_kb=1000)
    return c


def test_partial_ingest_is_unreliable(tmp_path):
    lr = run_lifecycle(_cfg(), IngestDomain(actual_docs=900, expected_docs=1000),
                       workdir=tmp_path, baseline=_cfg())
    assert lr.result.reliability_tag is ReliabilityTag.UNRELIABLE  # dropped 10% ⇒ not comparable


def test_full_ingest_is_not_failed(tmp_path):
    lr = run_lifecycle(_cfg(), IngestDomain(actual_docs=1000, expected_docs=1000),
                       workdir=tmp_path, baseline=_cfg())
    assert lr.result.reliability_tag is not ReliabilityTag.UNRELIABLE
    assert lr.result.functional_validation["passed"] is True


def test_recall_k_not_10_is_skipped_exploratory():
    from clusterbench_core.discipline.metrics import recall_validation
    fv = recall_validation(0.8, k=5, integrity_passed=True)
    assert fv["passed"] is None and "k==10" in fv["reason"]
    ok = recall_validation(0.9, k=10, integrity_passed=True)
    assert ok["passed"] is True
