"""Three-phase preflight gate (plugin Step 3 / Step 2.5).

Phase A — baseline diff: mechanically classify every parameter against the
          baseline config (match / treatment / allowed_drift / unexpected / missing).
Phase B — apply config: push config.yaml -> system (domain.apply_config).
Phase C — post-deploy verify: read live values back, compare to declared.

Each phase is a hard gate; any unexpected/missing param or verify mismatch blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from benchmark_engine.model import BenchmarkConfig


# ----------------------------- Phase A -------------------------------------


@dataclass
class BaselineDiff:
    matches: list[str] = field(default_factory=list)
    treatments: list[tuple[str, Any, Any]] = field(default_factory=list)
    allowed_drift: list[tuple[str, Any, Any, str]] = field(default_factory=list)
    unexpected: list[tuple[str, Any, Any]] = field(default_factory=list)
    missing_from_new: list[tuple[str, Any]] = field(default_factory=list)
    extra_in_new: list[tuple[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unexpected and not self.missing_from_new

    def render(self) -> str:
        L = ["Phase A — Baseline Diff"]
        L.append(f"  matches={len(self.matches)} treatments={len(self.treatments)} "
                 f"allowed_drift={len(self.allowed_drift)} unexpected={len(self.unexpected)} "
                 f"missing={len(self.missing_from_new)}")
        for k, b, n in self.unexpected:
            L.append(f"  UNEXPECTED {k}: baseline={b} new={n}")
        for k, b in self.missing_from_new:
            L.append(f"  MISSING {k} (baseline={b})")
        L.append("PHASE A: " + ("PASS" if self.ok else "FAIL"))
        return "\n".join(L)


def baseline_diff(new: BenchmarkConfig, baseline: BenchmarkConfig) -> BaselineDiff:
    d = BaselineDiff()
    tv = new.treatment_variable.name
    allowed = {e["parameter"]: e for e in (new.expected_diff_from_baseline or [])}

    new_vals = {k: p.value for k, p in new.params.items()}
    base_vals = {k: p.value for k, p in baseline.params.items()}

    for k, bv in base_vals.items():
        if k not in new_vals:
            d.missing_from_new.append((k, bv))
            continue
        nv = new_vals[k]
        if str(nv) == str(bv):
            d.matches.append(k)
        elif k == tv or k.endswith(tv):
            d.treatments.append((k, bv, nv))
        elif k in allowed:
            d.allowed_drift.append((k, bv, nv, allowed[k].get("reason", "")))
        else:
            d.unexpected.append((k, bv, nv))

    for k, nv in new_vals.items():
        if k not in base_vals:
            d.extra_in_new.append((k, nv))
    return d


# ----------------------------- Phase C -------------------------------------


@dataclass
class VerifyResult:
    rows: dict[str, tuple[Any, Any, bool]]  # param -> (declared, observed, ok)

    @property
    def ok(self) -> bool:
        return all(ok for _, _, ok in self.rows.values())

    @property
    def mismatches(self) -> list[str]:
        return [k for k, (_, _, ok) in self.rows.items() if not ok]

    def render(self) -> str:
        L = ["Phase C — Post-Deploy Verify"]
        for k, (decl, obs, ok) in self.rows.items():
            L.append(f"  [{'OK' if ok else 'FAIL'}] {k}: declared={decl} observed={obs}")
        L.append("PHASE C: " + ("PASS" if self.ok else "FAIL"))
        return "\n".join(L)


# --------------------------- orchestration ---------------------------------


@dataclass
class PreflightResult:
    phase_a: BaselineDiff | None
    phase_b_log: dict | None
    phase_c: VerifyResult | None
    passed: bool
    blocked_reason: str = ""

    def render(self) -> str:
        parts = []
        if self.phase_a is not None:
            parts.append(self.phase_a.render())
        else:
            parts.append("Phase A SKIPPED: no baseline declared")
        parts.append("Phase B: " + ("applied" if self.phase_b_log is not None else "skipped"))
        if self.phase_c is not None:
            parts.append(self.phase_c.render())
        parts.append("PREFLIGHT: " + ("PASS" if self.passed else f"BLOCKED ({self.blocked_reason})"))
        return "\n".join(parts)


def run_preflight(
    cfg: BenchmarkConfig,
    domain,
    ctx: Any,
    baseline: BenchmarkConfig | None = None,
    apply: bool = True,
) -> PreflightResult:
    # Phase A
    pa = baseline_diff(cfg, baseline) if baseline is not None else None
    if pa is not None and not pa.ok:
        return PreflightResult(pa, None, None, False, "phase_a_baseline_diff")

    # Phase B
    pb_log = None
    if apply:
        pb_log = domain.apply_config(cfg, ctx)

    # Phase C
    pc = VerifyResult(domain.verify_config(cfg, ctx))
    if not pc.ok:
        return PreflightResult(pa, pb_log, pc, False, f"phase_c_verify:{','.join(pc.mismatches)}")

    return PreflightResult(pa, pb_log, pc, True)
