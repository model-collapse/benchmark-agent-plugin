"""Aggregate run folders into a results_index.md grouped by reliability tag
(the memory-continuity artifact the awareness hook and planner read back)."""

from __future__ import annotations

from pathlib import Path

import yaml

from benchmark_engine.model import ReliabilityTag

_SECTIONS = [
    (ReliabilityTag.RELIABLE, "Active Baselines (RELIABLE)"),
    (ReliabilityTag.QUALIFIED, "Qualified Runs"),
    (ReliabilityTag.UNRELIABLE, "Invalidated Runs (NOT for citation)"),
    (ReliabilityTag.EXPLORATORY, "Exploratory Runs"),
]

DEFAULT_WORKDIR = "./benchmark_data/runs"


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
            # metric-agnostic: columns are the sorted union of every metric name
            # that appears in this section's runs — no hard-coded metric names.
            cols = sorted({k for r in rows for k in (r.get("metrics") or {})})
            header = ["Run ID", "Status", *cols]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "|".join(["---"] * len(header)) + "|")
            for r in rows:
                m = r.get("metrics", {})
                cells = [str(r.get("run_id", "")), str(r.get("status", ""))]
                cells += [str(m.get(c, "-")) for c in cols]
                lines.append("| " + " | ".join(cells) + " |")
        else:
            lines.append("_none_")
        lines.append("")

    out = workdir.parent / "results_index.md" if workdir.name == "runs" else workdir / "results_index.md"
    out.write_text("\n".join(lines))
    return out


def load_runs(workdir: str | Path) -> list[dict]:
    """Flatten persisted RunResults into rows for analysis (pandas/notebook):
    one dict per run with run_id, status, reliability_tag, treatment, every metric,
    recall@10, and passed."""
    workdir = Path(workdir)
    rows: list[dict] = []
    for rp in sorted(workdir.glob("*/results.yaml")):
        try:
            r = yaml.safe_load(rp.read_text())
        except Exception:  # noqa: BLE001
            continue
        row = {"run_id": r["run_id"], "status": r["status"],
               "reliability_tag": r["reliability_tag"]}
        row.update(r.get("metrics", {}))
        fv = r.get("functional_validation", {})
        row["passed"] = fv.get("passed")
        # metric-agnostic: flatten every functional-validation value (recall@10,
        # ndcg@10, accuracy, …), not a hard-coded metric name.
        for k, v in fv.items():
            if k != "passed":
                row[k] = v
        cfg_p = rp.parent / "config.yaml"
        if cfg_p.exists():
            tv = (yaml.safe_load(cfg_p.read_text()) or {}).get("treatment_variable", {})
            row["treatment"] = tv.get("name")
            row["treatment_value"] = tv.get("value")
        rows.append(row)
    return rows
