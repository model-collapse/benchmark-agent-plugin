"""The Domain protocol — the seam between the generic engine and a concrete
system (OpenSearch, SEISMIC, ...).

A Domain knows how to:
  - declare which parameters are mandatory (required_params manifest),
  - apply a BenchmarkConfig to the live system (Phase B),
  - read the live values back for verification (Phase C),
  - build the cacheable prep step and the always-run measurement step.

Everything here is defined against the pure-Python BenchmarkConfig so the
discipline layer can be exercised with a FakeDomain in unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from benchmark_engine.model import BenchmarkConfig, PhaseMetrics


@dataclass
class PrepArtifact:
    """Opaque handle to a deterministic prep result (e.g. a built index)."""

    kind: str
    path: str = ""
    handle: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class MeasureOutcome:
    """Result of the always-run measurement step."""

    metrics: dict[str, Any] = field(default_factory=dict)
    phases: list[PhaseMetrics] = field(default_factory=list)
    functional_validation: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Domain(Protocol):
    name: str

    def required_params(self) -> dict:
        """Return the parsed required-params manifest (see discipline.manifest)."""

    def apply_config(self, cfg: BenchmarkConfig, ctx: Any) -> dict:
        """Phase B: push every declared setting to the system. Return a log dict."""

    def verify_config(self, cfg: BenchmarkConfig, ctx: Any) -> dict[str, tuple[Any, Any, bool]]:
        """Phase C: read live values. Return {param: (declared, observed, ok)}."""

    def prep(self, cfg: BenchmarkConfig, ctx: Any) -> PrepArtifact:
        """Deterministic, cacheable build (corpus/index). Keyed by signature."""

    def measure(self, cfg: BenchmarkConfig, prep: PrepArtifact, ctx: Any) -> MeasureOutcome:
        """Always-run measurement (latency/throughput/recall)."""
