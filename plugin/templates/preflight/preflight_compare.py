#!/usr/bin/env python3
"""
Phase A — Baseline Diff (mandatory preflight gate).

Mechanically diff a new run's config.yaml against the baseline's config.yaml.
Every parameter is classified:
  match | treatment_variable | allowed_drift | unexpected_diff | missing_from_new

Exit 0 if all parameters fall into match / treatment_variable / allowed_drift.
Exit non-zero (with diff written to stderr + artifacts) on any unexpected
or missing parameter.

Usage:
  preflight_compare.py --new-run /path/to/runs/<new_id> \
                       --baseline /path/to/runs/<baseline_id>
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


def flatten(obj, prefix=""):
    """Flatten nested dict to {dotted.key: value}. Skips lists at leaves."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_prefix = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                # Special case: parameter records like {value, source, note}
                # are leaves keyed by the path
                if "value" in v and not isinstance(v.get("value"), dict):
                    out[new_prefix] = v["value"]
                else:
                    out.update(flatten(v, new_prefix))
            elif isinstance(v, list):
                out[new_prefix] = json.dumps(v, sort_keys=True)
            else:
                out[new_prefix] = v
    return out


def load_config(run_dir):
    p = Path(run_dir) / "config.yaml"
    if not p.exists():
        print(f"ERROR: {p} does not exist", file=sys.stderr)
        sys.exit(2)
    with open(p) as f:
        return yaml.safe_load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new-run", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--report-out", default=None,
                    help="Path to write the full diff (default: <new-run>/artifacts/preflight_baseline_diff.txt)")
    args = ap.parse_args()

    new_cfg = load_config(args.new_run)
    base_cfg = load_config(args.baseline)

    # Treatment variable from new config
    treatment_var = (new_cfg.get("treatment_variable") or {}).get("name")
    treatment_path = treatment_var  # may be a dotted path like "index.merge.scheduler.max_thread_count"

    # Allowed-drift entries
    allowed = {e["parameter"]: e for e in new_cfg.get("expected_diff_from_baseline") or []}

    new_flat = flatten(new_cfg)
    base_flat = flatten(base_cfg)

    matches = []
    treatments = []
    drifts_allowed = []
    drifts_unexpected = []
    missing_from_new = []

    for key, base_v in base_flat.items():
        if key not in new_flat:
            missing_from_new.append((key, base_v))
            continue
        new_v = new_flat[key]
        if str(new_v) == str(base_v):
            matches.append((key, new_v))
            continue
        # value differs
        if treatment_path and key.endswith(treatment_path):
            treatments.append((key, base_v, new_v))
        elif key in allowed:
            drifts_allowed.append((key, base_v, new_v, allowed[key].get("reason", "")))
        else:
            drifts_unexpected.append((key, base_v, new_v))

    extra_in_new = [(k, v) for k, v in new_flat.items() if k not in base_flat]

    # Write report
    report_path = args.report_out or os.path.join(args.new_run, "artifacts", "preflight_baseline_diff.txt")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as r:
        r.write(f"Phase A — Baseline Diff\n")
        r.write(f"new run:  {args.new_run}\n")
        r.write(f"baseline: {args.baseline}\n\n")
        r.write(f"=== matches ({len(matches)}) ===\n")
        for k, v in matches:
            r.write(f"  {k} = {v}\n")
        r.write(f"\n=== treatment variable ({len(treatments)}) ===\n")
        for k, b, n in treatments:
            r.write(f"  {k}: {b} -> {n}\n")
        r.write(f"\n=== allowed drift ({len(drifts_allowed)}) ===\n")
        for k, b, n, reason in drifts_allowed:
            r.write(f"  {k}: {b} -> {n} ({reason})\n")
        r.write(f"\n=== UNEXPECTED diff ({len(drifts_unexpected)}) ===\n")
        for k, b, n in drifts_unexpected:
            r.write(f"  {k}: {b} -> {n}\n")
        r.write(f"\n=== MISSING from new ({len(missing_from_new)}) ===\n")
        for k, v in missing_from_new:
            r.write(f"  {k} = {v} (baseline)\n")
        r.write(f"\n=== extra in new (informational) ({len(extra_in_new)}) ===\n")
        for k, v in extra_in_new:
            r.write(f"  {k} = {v}\n")

    fail = (len(drifts_unexpected) > 0) or (len(missing_from_new) > 0)
    print(f"matches={len(matches)} treatments={len(treatments)} allowed_drift={len(drifts_allowed)} "
          f"unexpected={len(drifts_unexpected)} missing={len(missing_from_new)} extra={len(extra_in_new)}")
    print(f"report: {report_path}")
    if fail:
        print("\nPHASE A: FAIL", file=sys.stderr)
        if drifts_unexpected:
            print("\nUnexpected diffs (must add to expected_diff_from_baseline or revert):", file=sys.stderr)
            for k, b, n in drifts_unexpected:
                print(f"  {k}: baseline={b} new={n}", file=sys.stderr)
        if missing_from_new:
            print("\nMissing from new config (must declare):", file=sys.stderr)
            for k, v in missing_from_new:
                print(f"  {k} (baseline value: {v})", file=sys.stderr)
        sys.exit(1)
    print("PHASE A: PASS")


if __name__ == "__main__":
    main()
