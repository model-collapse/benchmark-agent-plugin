"""Aggregate run folders into a results_index.md grouped by reliability tag
(the memory-continuity artifact the awareness hook and planner read back)."""

from __future__ import annotations

from pathlib import Path

import yaml

from clusterbench_core.model import ReliabilityTag

_SECTIONS = [
    (ReliabilityTag.RELIABLE, "Active Baselines (RELIABLE)"),
    (ReliabilityTag.QUALIFIED, "Qualified Runs"),
    (ReliabilityTag.UNRELIABLE, "Invalidated Runs (NOT for citation)"),
    (ReliabilityTag.EXPLORATORY, "Exploratory Runs"),
]


def update_index(workdir: str | Path) -> Path:
    workdir = Path(workdir)
    runs: list[dict] = []
    for rp in sorted(workdir.glob("*/results.yaml")):
        try:
            runs.append(yaml.safe_load(rp.read_text()))
        except Exception:  # noqa: BLE001
            continue

    lines = ["# Benchmark Results Index", ""]
    for tag, title in _SECTIONS:
        rows = [r for r in runs if r.get("reliability_tag") == tag.value]
        lines.append(f"## {title}")
        if rows:
            lines.append("| Run ID | Status | p50_ms | recall@10 | Key |")
            lines.append("|--------|--------|--------|-----------|-----|")
            for r in rows:
                m = r.get("metrics", {})
                fv = r.get("functional_validation", {})
                key = m.get("forcemerge_s") or m.get("build_time_s") or ""
                lines.append(f"| {r['run_id']} | {r['status']} | {m.get('p50_ms','-')} "
                             f"| {fv.get('recall@10','-')} | {key} |")
        else:
            lines.append("_none_")
        lines.append("")

    out = workdir.parent / "results_index.md" if workdir.name == "runs" else workdir / "results_index.md"
    out.write_text("\n".join(lines))
    return out
