"""Reliability tagging + the reproduction requirement (plugin "Reliability Tags").

RELIABLE requires: full instrumentation, mechanism explained, functional
validation passed, no confounds, AND independent reproduction within tolerance.
A single-run measurement is QUALIFIED at most.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clusterbench_core.model import ReliabilityTag, RunResult

# Default reproduction tolerances (relative unless noted).
# p99 is intentionally NOT a gate metric: from ~N<=1000 queries it is dominated
# by tail noise and would cap good runs at QUALIFIED forever (it stays available
# as a diagnostic). p50 is tightened to 10% (a clean bench has CV<5%); recall is
# 0.5pp so it stays strictly inside the tuner's 1pp selection band.
DEFAULT_TOLERANCES: dict[str, float] = {
    "peak_rss_kb": 0.10,
    "p50_ms": 0.10,
    "p95_ms": 0.20,
    "build_time_s": 0.30,
    "forcemerge_s": 0.30,
    "search_time_s": 0.20,
    "recall@10": 0.005,  # absolute (percentage-point style)
}
_ABSOLUTE_METRICS = {"recall@10", "recall@100"}


@dataclass
class ReproCheck:
    reproduced: bool
    details: dict[str, tuple[float, float, float, bool]]  # metric -> (a, b, tol, ok)

    def render(self) -> str:
        L = ["Reproduction check:"]
        for m, (a, b, tol, ok) in self.details.items():
            L.append(f"  [{'OK' if ok else 'FAIL'}] {m}: {a} vs {b} (tol {tol})")
        L.append("REPRODUCED" if self.reproduced else "NOT REPRODUCED")
        return "\n".join(L)


def reproduced_within_tolerance(
    a: RunResult, b: RunResult, tolerances: dict[str, float] | None = None
) -> ReproCheck:
    tol = {**DEFAULT_TOLERANCES, **(tolerances or {})}
    details: dict[str, tuple[float, float, float, bool]] = {}
    all_metrics = {**a.metrics, **a.functional_validation}
    bmetrics = {**b.metrics, **b.functional_validation}
    for m, av in all_metrics.items():
        if m not in bmetrics or m not in tol:
            continue
        bv = bmetrics[m]
        try:
            av_f, bv_f = float(av), float(bv)
        except (TypeError, ValueError):
            continue
        t = tol[m]
        if m in _ABSOLUTE_METRICS:
            ok = abs(av_f - bv_f) <= t
        else:
            denom = max(abs(av_f), 1e-9)
            ok = abs(av_f - bv_f) / denom <= t
        details[m] = (av_f, bv_f, t, ok)
    reproduced = bool(details) and all(ok for *_, ok in details.values())
    return ReproCheck(reproduced=reproduced, details=details)


@dataclass
class ClassifyInput:
    has_critical_bug: bool = False
    gross_confound: bool = False
    minor_confound: bool = False
    mechanism_explained: bool = True
    functional_validation_passed: bool | None = True  # None = skipped
    multivariable_or_first_of_kind: bool = False
    reproduced: bool = False
    effective_matches_declared: bool = True  # Gate 1: effective == declared params


def classify(inp: ClassifyInput) -> tuple[ReliabilityTag, str]:
    """Return (tag, rationale). Precedence matches the plugin's rules."""
    if not inp.effective_matches_declared:
        return ReliabilityTag.UNRELIABLE, "effective params deviated from declared — not comparable"
    if inp.has_critical_bug or inp.gross_confound:
        return ReliabilityTag.UNRELIABLE, "critical bug / gross confound invalidates the measurement"
    if inp.multivariable_or_first_of_kind:
        return ReliabilityTag.EXPLORATORY, "multi-variable or first-of-kind — informational only"
    if inp.functional_validation_passed is False:
        return ReliabilityTag.UNRELIABLE, "functional validation FAILED (data integrity) — not comparable"
    if inp.functional_validation_passed is None:
        return ReliabilityTag.EXPLORATORY, "functional validation skipped — never RELIABLE without it"
    if not inp.mechanism_explained:
        return ReliabilityTag.QUALIFIED, "mechanism not fully explained"
    if not inp.reproduced:
        return ReliabilityTag.QUALIFIED, "single-run measurement — reproduction required for RELIABLE"
    if inp.minor_confound:
        return ReliabilityTag.QUALIFIED, "valid data with a minor known caveat"
    return ReliabilityTag.RELIABLE, "reproduced, mechanism explained, validated, no confounds"


def citation_allowed(tag: ReliabilityTag) -> bool:
    return tag in (ReliabilityTag.RELIABLE, ReliabilityTag.QUALIFIED)


def fairness_assert(result) -> None:
    """Fail-loud engine invariant: a run whose effective params deviated from
    declared can NEVER be RELIABLE/QUALIFIED. classify() enforces this; this
    assertion catches any future code path that tries to bypass it."""
    if result.signature_diff and result.reliability_tag in (
        ReliabilityTag.RELIABLE, ReliabilityTag.QUALIFIED
    ):
        raise AssertionError(
            f"fail-loud: {result.run_id} has effective!=declared "
            f"({list(result.signature_diff)}) but tag {result.reliability_tag.value}"
        )


# --- forbidden-behavior auditing -------------------------------------------

_FORBIDDEN_PATTERNS = [
    ("no regression", "claims 'no regression' — requires a functional validation benchmark"),
    ("as expected", "says 'as expected' — requires a pre-documented expectation"),
]


def audit_claims(report: str, functional_validation_passed: bool | None) -> list[str]:
    """Return a list of forbidden-behavior violations found in a report string."""
    violations: list[str] = []
    low = report.lower()
    if "no regression" in low and functional_validation_passed is not True:
        violations.append("'no regression' claimed without a passing validation benchmark")
    if "## what went wrong" not in low and "what went wrong or remained unknown" not in low:
        violations.append("missing mandatory 'What Went Wrong' section")
    return violations
