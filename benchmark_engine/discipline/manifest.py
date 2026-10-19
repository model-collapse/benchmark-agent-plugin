"""Required-parameters manifest — the HARD GATE (plugin Layer 1).

A parameter is in the manifest because a prior run was invalidated by a silent
change to it. Every BenchmarkConfig must declare each required parameter
explicitly (even if the value equals the default, so future readers see it was
considered, not forgotten). Missing a required parameter blocks the plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from benchmark_engine.model import BenchmarkConfig


@dataclass
class ManifestEntry:
    path: str
    reason: str = ""
    incident: str = ""
    default: object = None
    baseline_value: object = None
    verify: str = ""
    impact_if_drift: str = ""


@dataclass
class MissingParam:
    path: str
    reason: str
    default: object
    suggested: object
    incident: str

    def render(self) -> str:
        return (
            f"  - {self.path}\n"
            f"      Reason: {self.reason}" + (f" (incident: {self.incident})" if self.incident else "") + "\n"
            f"      Default: {self.default} | Suggested: {self.suggested}"
        )


@dataclass
class ManifestCheck:
    ok: bool
    missing: list[MissingParam]

    def render(self) -> str:
        if self.ok:
            return "DOMAIN MANIFEST CHECK: PASS"
        lines = ["DOMAIN MANIFEST CHECK FAILED:", "", "Missing required parameters in plan:"]
        lines += [m.render() for m in self.missing]
        lines += [
            "",
            "These parameters MUST be declared explicitly. The manifest exists because",
            "prior runs were invalidated by silent changes to these. Add them and re-submit.",
        ]
        return "\n".join(lines)


def load_manifest(path: str | Path) -> dict[str, ManifestEntry]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    out: dict[str, ManifestEntry] = {}
    for p, spec in (data.get("required_params") or {}).items():
        spec = spec or {}
        out[p] = ManifestEntry(
            path=p,
            reason=spec.get("reason", ""),
            incident=spec.get("incident", ""),
            default=spec.get("default"),
            baseline_value=spec.get("baseline_value"),
            verify=spec.get("verify", ""),
            impact_if_drift=spec.get("impact_if_drift", ""),
        )
    return out


def check_manifest(cfg: BenchmarkConfig, manifest: dict[str, ManifestEntry]) -> ManifestCheck:
    """HARD GATE: every manifest param must be declared in cfg.params."""
    missing: list[MissingParam] = []
    for p, entry in manifest.items():
        if p.startswith("__"):  # pseudo-entries (e.g. __codepath_smoke_test_required) are checks, not params
            continue
        if p not in cfg.params:
            suggested = entry.baseline_value if entry.baseline_value is not None else entry.default
            missing.append(
                MissingParam(
                    path=p,
                    reason=entry.reason,
                    default=entry.default,
                    suggested=suggested,
                    incident=entry.incident,
                )
            )
    return ManifestCheck(ok=not missing, missing=missing)


def autofill_from_manifest(cfg: BenchmarkConfig, manifest: dict[str, ManifestEntry]) -> list[str]:
    """Fill any missing manifest params with their baseline/default value,
    sourced 'default'. Returns the list of filled paths. (Advisory helper for
    the planner — the gate still runs afterwards.)"""
    filled: list[str] = []
    for p, entry in manifest.items():
        if p.startswith("__") or p in cfg.params:
            continue
        val = entry.baseline_value if entry.baseline_value is not None else entry.default
        cfg.set_param(p, val, source="default", note="autofilled from manifest baseline")
        filled.append(p)
    return filled
