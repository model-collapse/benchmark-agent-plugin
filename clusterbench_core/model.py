"""Typed benchmark configuration and result schema.

These are plain dataclasses (pure Python, no experimaestro runtime needed) so the
discipline layer and the result schema are cheap to unit-test. The execution
layer (clusterbench_ops) renders a BenchmarkConfig into experimaestro Tasks.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FrozenConfigError(RuntimeError):
    """Raised when a frozen BenchmarkConfig is mutated (mutate ⇒ new run)."""


class ReliabilityTag(str, Enum):
    RELIABLE = "RELIABLE"
    QUALIFIED = "QUALIFIED"
    UNRELIABLE = "UNRELIABLE"
    EXPLORATORY = "EXPLORATORY"


class RunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED_PREFLIGHT = "ABORTED_PREFLIGHT"
    ABORTED_GUARDRAIL = "ABORTED_GUARDRAIL"


# --- parameter records -----------------------------------------------------

ParamSource = str  # "default" | "inherited" | "treatment" | "matches_baseline" | ...


@dataclass
class Param:
    """A single declared parameter: value + provenance (never a bare value)."""

    value: Any
    source: ParamSource = "default"
    note: str = ""

    def to_dict(self) -> dict:
        d = {"value": self.value, "source": self.source}
        if self.note:
            d["note"] = self.note
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "Param":
        if isinstance(d, dict) and "value" in d:
            return cls(value=d["value"], source=d.get("source", "default"), note=d.get("note", ""))
        # bare scalar -> treat as a default-sourced param
        return cls(value=d, source="default")


@dataclass
class TreatmentVariable:
    """The single variable intentionally changed between runs."""

    name: str  # dotted path, e.g. "seismic.heap_factor"
    baseline_value: Any = None
    value: Any = None

    def to_dict(self) -> dict:
        return {"name": self.name, "baseline_value": self.baseline_value, "value": self.value}

    @classmethod
    def from_dict(cls, d: dict) -> "TreatmentVariable":
        return cls(name=d["name"], baseline_value=d.get("baseline_value"), value=d.get("value"))


@dataclass
class ControlledVar:
    name: str
    value: Any
    verify: str = ""  # command/expression that reads the live value

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "verify": self.verify}

    @classmethod
    def from_dict(cls, d: dict) -> "ControlledVar":
        return cls(name=d["name"], value=d["value"], verify=d.get("verify", ""))


@dataclass
class ResourceBudget:
    """Memory budget in KB. Thresholds are fractions of total RAM."""

    total_ram_kb: int
    estimated_peak_kb: int = 0
    warn_frac: float = 0.75
    hard_frac: float = 0.85
    emergency_frac: float = 0.92

    @property
    def warn_kb(self) -> int:
        return int(self.total_ram_kb * self.warn_frac)

    @property
    def hard_kb(self) -> int:
        return int(self.total_ram_kb * self.hard_frac)

    @property
    def emergency_kb(self) -> int:
        return int(self.total_ram_kb * self.emergency_frac)

    @property
    def verdict(self) -> str:
        """GO if estimated peak fits under the hard ceiling, else REJECT."""
        if self.estimated_peak_kb and self.estimated_peak_kb > self.hard_kb:
            return "REJECT"
        return "GO"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ResourceBudget":
        return cls(**{k: v for k, v in d.items() if k in {f.name for f in dataclasses.fields(cls)}})


# --- the benchmark config --------------------------------------------------


@dataclass
class BenchmarkConfig:
    """Canonical, declarative description of a benchmark run.

    `params` holds *every* parameter the run depends on, keyed by dotted path,
    each a Param (value + source). This is the single source of truth that the
    manifest gate, preflight diff, and apply/verify all read from.
    """

    domain: str
    hypothesis: str
    treatment_variable: TreatmentVariable
    params: dict[str, Param] = field(default_factory=dict)
    controlled_variables: list[ControlledVar] = field(default_factory=list)
    resource_budget: ResourceBudget | None = None
    baseline_run: str | None = None
    expected_diff_from_baseline: list[dict] = field(default_factory=list)
    repro_nonce: int = 0  # bump to force a fresh (reproduction) measurement

    # ---- freeze (Gate 1: mutate ⇒ new run) ----
    def freeze(self) -> "BenchmarkConfig":
        """Freeze the config at submit; subsequent set_param raises. The signature
        is recorded so assert_unchanged() can detect even direct param mutation."""
        object.__setattr__(self, "_frozen", True)
        object.__setattr__(self, "_frozen_sig", self.signature())
        return self

    def assert_unchanged(self) -> None:
        if getattr(self, "_frozen", False) and self.signature() != getattr(self, "_frozen_sig", None):
            raise FrozenConfigError("frozen config was mutated after freeze")

    # ---- param helpers ----
    def set_param(self, path: str, value: Any, source: str = "default", note: str = "") -> None:
        if getattr(self, "_frozen", False):
            raise FrozenConfigError(f"cannot set {path!r}: config is frozen (mutate ⇒ new run)")
        self.params[path] = Param(value=value, source=source, note=note)

    def get(self, path: str, default: Any = None) -> Any:
        p = self.params.get(path)
        return p.value if p is not None else default

    # ---- (de)serialization ----
    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "hypothesis": self.hypothesis,
            "treatment_variable": self.treatment_variable.to_dict(),
            "params": {k: v.to_dict() for k, v in self.params.items()},
            "controlled_variables": [c.to_dict() for c in self.controlled_variables],
            "resource_budget": self.resource_budget.to_dict() if self.resource_budget else None,
            "baseline_run": self.baseline_run,
            "expected_diff_from_baseline": self.expected_diff_from_baseline,
            "repro_nonce": self.repro_nonce,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BenchmarkConfig":
        return cls(
            domain=d["domain"],
            hypothesis=d.get("hypothesis", ""),
            treatment_variable=TreatmentVariable.from_dict(d["treatment_variable"]),
            params={k: Param.from_dict(v) for k, v in (d.get("params") or {}).items()},
            controlled_variables=[ControlledVar.from_dict(c) for c in d.get("controlled_variables") or []],
            resource_budget=ResourceBudget.from_dict(d["resource_budget"]) if d.get("resource_budget") else None,
            baseline_run=d.get("baseline_run"),
            expected_diff_from_baseline=d.get("expected_diff_from_baseline") or [],
            repro_nonce=d.get("repro_nonce", 0),
        )

    # ---- signature / identity ----
    def signature_payload(self) -> dict:
        """Everything that defines run identity: all param values + treatment +
        the repro nonce. Excludes prose (hypothesis) and bookkeeping."""
        return {
            "domain": self.domain,
            "params": {k: p.value for k, p in sorted(self.params.items())},
            "treatment": self.treatment_variable.to_dict(),
            "repro_nonce": self.repro_nonce,
        }

    def signature(self) -> str:
        blob = json.dumps(self.signature_payload(), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def run_id(self) -> str:
        tv = self.treatment_variable
        slug = f"{tv.name}={tv.value}".replace("/", "_").replace(" ", "")
        return f"{self.domain}__{slug}__{self.signature()}"


# --- results ---------------------------------------------------------------


@dataclass
class PhaseMetrics:
    name: str
    duration_s: float = 0.0
    peak_rss_kb: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PhaseMetrics":
        return cls(
            name=d["name"],
            duration_s=d.get("duration_s", 0.0),
            peak_rss_kb=d.get("peak_rss_kb", 0),
            extra=d.get("extra", {}),
        )


@dataclass
class RunResult:
    run_id: str
    signature: str
    status: RunStatus
    reliability_tag: ReliabilityTag
    metrics: dict[str, Any] = field(default_factory=dict)
    phases: list[PhaseMetrics] = field(default_factory=list)
    functional_validation: dict[str, Any] = field(default_factory=dict)
    abort: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    # Fairness Gate 1 (effective-param integrity)
    effective_params: dict[str, Any] = field(default_factory=dict)
    effective_signature: str = ""
    signature_diff: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    measurement_flags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "signature": self.signature,
            "status": self.status.value,
            "reliability_tag": self.reliability_tag.value,
            "metrics": self.metrics,
            "phases": [p.to_dict() for p in self.phases],
            "functional_validation": self.functional_validation,
            "abort": self.abort,
            "notes": self.notes,
            "effective_params": self.effective_params,
            "effective_signature": self.effective_signature,
            "signature_diff": self.signature_diff,
            "provenance": self.provenance,
            "measurement_flags": self.measurement_flags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RunResult":
        return cls(
            run_id=d["run_id"],
            signature=d["signature"],
            status=RunStatus(d["status"]),
            reliability_tag=ReliabilityTag(d["reliability_tag"]),
            metrics=d.get("metrics", {}),
            phases=[PhaseMetrics.from_dict(p) for p in d.get("phases", [])],
            functional_validation=d.get("functional_validation", {}),
            abort=d.get("abort"),
            notes=d.get("notes", []),
            effective_params=d.get("effective_params", {}),
            effective_signature=d.get("effective_signature", ""),
            signature_diff=d.get("signature_diff", {}),
            provenance=d.get("provenance", {}),
            measurement_flags=d.get("measurement_flags", {}),
        )
