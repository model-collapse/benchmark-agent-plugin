"""Shared test fixtures: a FakeDomain + synthetic SPLADE corpus."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import pytest

from clusterbench_core.domain import MeasureOutcome, PrepArtifact
from clusterbench_core.model import (
    BenchmarkConfig,
    ControlledVar,
    PhaseMetrics,
    ResourceBudget,
    TreatmentVariable,
)


@dataclass
class FakeDomain:
    """A deterministic in-memory domain for unit/integration tests.

    `live_overrides` lets a test force Phase C to observe a value different from
    the declared one (to exercise the verify gate). `speed_model` maps the
    treatment value -> primary metric so sweeps are deterministic.
    """

    name: str = "fake"
    manifest: dict = field(default_factory=dict)
    live_overrides: dict = field(default_factory=dict)
    applied: dict = field(default_factory=dict)
    oom_at: float | None = None  # if treatment value >= this, measure() signals OOM

    def required_params(self) -> dict:
        return self.manifest

    def apply_config(self, cfg: BenchmarkConfig, ctx) -> dict:
        self.applied = {k: p.value for k, p in cfg.params.items()}
        return {"applied": dict(self.applied)}

    def verify_config(self, cfg: BenchmarkConfig, ctx):
        rows = {}
        for cv in cfg.controlled_variables:
            declared = cfg.get(cv.name, cv.value)
            observed = self.live_overrides.get(cv.name, declared)
            rows[cv.name] = (declared, observed, str(declared) == str(observed))
        return rows

    def prep(self, cfg: BenchmarkConfig, ctx) -> PrepArtifact:
        return PrepArtifact(kind="fake-index", meta={"n_docs": 1000, "sig": cfg.signature()})

    def measure(self, cfg: BenchmarkConfig, prep: PrepArtifact, ctx) -> MeasureOutcome:
        tv = cfg.treatment_variable.value
        # simple monotone speed model: higher treatment -> faster (lower latency)
        p50 = max(1.0, 50.0 - 40.0 * float(tv))
        peak = 1000 + int(2000 * float(tv))
        if self.oom_at is not None and float(tv) >= self.oom_at:
            peak = 10 ** 9  # blow the budget
        return MeasureOutcome(
            metrics={"p50_ms": p50, "peak_rss_kb": peak},
            phases=[PhaseMetrics(name="search", duration_s=p50 / 1000.0, peak_rss_kb=peak)],
            functional_validation={"passed": True, "recall@10": 0.98},
        )


@pytest.fixture
def fake_manifest_file(tmp_path):
    p = tmp_path / "required_params.yaml"
    p.write_text(
        """
schema_version: "1.0"
domain: "fake"
required_params:
  fake.n_postings:
    reason: "controls posting list length"
    incident: "demo-1"
    default: 3500
    baseline_value: 3500
    verify: "noop"
  fake.heap_factor:
    reason: "search speed/quality knob"
    default: 0.7
    baseline_value: 0.7
    verify: "noop"
  __codepath_smoke:
    reason: "pseudo-entry, not a param"
    default: skipped
"""
    )
    return p


def make_base_config(treatment_value=0.7) -> BenchmarkConfig:
    cfg = BenchmarkConfig(
        domain="fake",
        hypothesis="higher heap_factor is faster",
        treatment_variable=TreatmentVariable(
            name="fake.heap_factor", baseline_value=0.7, value=treatment_value
        ),
    )
    cfg.set_param("fake.n_postings", 3500, source="inherited")
    cfg.set_param("fake.heap_factor", treatment_value, source="treatment")
    cfg.controlled_variables.append(ControlledVar("fake.n_postings", 3500, verify="noop"))
    cfg.resource_budget = ResourceBudget(total_ram_kb=10_000, estimated_peak_kb=3000)
    return cfg


@pytest.fixture
def base_config():
    return make_base_config()


def synthetic_splade_corpus(n_docs=500, vocab=3000, avg_nnz=40, seed=0):
    """Generate SPLADE-like sparse vectors: {term_id: weight}."""
    rng = random.Random(seed)
    docs = []
    for i in range(n_docs):
        nnz = max(1, int(rng.gauss(avg_nnz, avg_nnz * 0.2)))
        terms = rng.sample(range(vocab), min(nnz, vocab))
        docs.append({str(t): round(rng.uniform(0.1, 3.0), 3) for t in terms})
    return docs
