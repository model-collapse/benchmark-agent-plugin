"""Report generation with the mandatory 'What Went Wrong' section (plugin Step 7)."""

from __future__ import annotations

from clusterbench_core.model import BenchmarkConfig, RunResult


def generate_report(cfg: BenchmarkConfig, result: RunResult, prior: RunResult | None = None) -> str:
    tv = cfg.treatment_variable
    fv = result.functional_validation
    fv_line = (
        f"Functional validation PASSED: {fv}" if fv.get("passed") else
        f"Functional validation {'FAILED' if fv.get('passed') is False else 'SKIPPED'}: {fv}"
    )
    L = [
        f"# Benchmark Run Report: {result.run_id}",
        "",
        "## Run Summary",
        f"- Signature: {result.signature}",
        f"- Hypothesis: {cfg.hypothesis}",
        f"- Treatment: {tv.name} = {tv.value} (baseline {tv.baseline_value})",
        f"- Status: {result.status.value}",
        f"- Reliability: {result.reliability_tag.value}",
        f"- {fv_line}",
        "",
        "## Primary Metrics",
        "",
        "| Metric | Observed | Prior | Delta |",
        "|--------|----------|-------|-------|",
    ]
    prior_metrics = (prior.metrics if prior else {}) or {}
    for k, v in result.metrics.items():
        pv = prior_metrics.get(k)
        delta = ""
        if isinstance(v, (int, float)) and isinstance(pv, (int, float)) and pv:
            delta = f"{(v - pv) / pv * 100:+.1f}%"
        L.append(f"| {k} | {v} | {pv if pv is not None else '-'} | {delta or '-'} |")

    L += [
        "",
        "## Mechanism Explanation",
        _mechanism(result),
        "",
        "## What Went Well",
        _what_went_well(result),
        "",
        "## What Went Wrong or Remained Unknown",
        "**THIS SECTION IS MANDATORY.**",
        _what_went_wrong(result),
        "",
        "## Risks and Limitations",
        _risks(result),
    ]
    if result.abort:
        L += ["", "## Abort", f"```\n{result.abort}\n```"]
    return "\n".join(L)


def _mechanism(r: RunResult) -> str:
    phase_bits = ", ".join(f"{p.name}={p.duration_s:.2f}s" for p in r.phases) or "no phase timing captured"
    return f"Time accounted across phases: {phase_bits}."


def _what_went_well(r: RunResult) -> str:
    if r.status.value == "COMPLETED":
        return "- Run completed; metrics captured per phase with resource monitoring."
    return "- (run did not complete; see abort)"


def _what_went_wrong(r: RunResult) -> str:
    bullets = list(r.notes)
    if not r.phases:
        bullets.append("No per-phase instrumentation captured — measurement validity unverified.")
    if r.functional_validation.get("passed") is not True:
        bullets.append("Functional validation did not pass — results cannot be cited as RELIABLE.")
    if r.abort:
        bullets.append(f"Run aborted: {r.abort.get('reason', 'unknown')}.")
    if not bullets:
        bullets.append("No anomalies detected in instrumentation; residual risk is scaling (see below).")
    return "\n".join(f"- {b}" for b in bullets)


def _risks(r: RunResult) -> str:
    return (
        "- Results measured at the tested scale; larger corpora may shift the memory/latency profile.\n"
        "- Single-environment measurement; cross-node variance not characterized unless reproduced."
    )
