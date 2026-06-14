#!/usr/bin/env python3
"""
Phase C — Post-Deploy Verify (mandatory preflight gate).

Query the cluster for the actual live values of every parameter declared in
config.yaml, then compare to the declared values. Exits non-zero on any
mismatch.

This catches:
  - Settings PUT returned 200 but value didn't stick (Final settings on existing index)
  - Plugin / codec silently overrode the requested value
  - apply_config.py applied a different setting than declared (typo)
  - OS-level setting (sysctl) drifted from declared
  - Plugin jar swapped without the version check catching it

Usage:
  postdeploy_check.py --run-dir /path/to/runs/<id> --es http://NODE:9200

The script reads which parameters to check from config.yaml's
`controlled_variables` section. Each must have a `verify` field — a shell
command that, when run, prints the current actual value to stdout.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed", file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--report-out", default=None)
    ap.add_argument("--ssh-fallback-node", default=None,
                    help="If set, run verify commands via ssh to this node "
                         "(useful when local port-forward isn't reliable)")
    args = ap.parse_args()

    cfg_path = Path(args.run_dir) / "config.yaml"
    if not cfg_path.exists():
        print(f"ERROR: {cfg_path} not found", file=sys.stderr)
        sys.exit(2)
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    controlled = cfg.get("controlled_variables") or []
    if not controlled:
        print("ERROR: config.yaml has no controlled_variables section to verify", file=sys.stderr)
        sys.exit(2)

    report_path = args.report_out or os.path.join(args.run_dir, "artifacts", "postdeploy_verify.txt")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    passes = 0
    fails = []

    with open(report_path, "w") as r:
        r.write("Phase C — Post-Deploy Verify\n")
        r.write(f"run: {args.run_dir}\n\n")
        for cv in controlled:
            name = cv.get("name", "<unnamed>")
            expected = cv.get("expected")
            verify_cmd = cv.get("verify")
            if not verify_cmd:
                r.write(f"  SKIP {name}: no verify command\n")
                continue
            cmd = verify_cmd
            if args.ssh_fallback_node:
                cmd = f"ssh -o ConnectTimeout=5 {args.ssh_fallback_node} {json.dumps(verify_cmd)}"
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=30
                )
                actual = (result.stdout or "").strip().strip('"').strip("'")
            except Exception as e:
                r.write(f"  ERROR {name}: verify command failed: {e}\n")
                fails.append((name, expected, f"verify-failed: {e}"))
                continue
            if str(actual) == str(expected):
                r.write(f"  PASS {name}: {actual}\n")
                passes += 1
            else:
                r.write(f"  FAIL {name}: declared={expected!r} actual={actual!r}\n")
                fails.append((name, expected, actual))

        r.write(f"\nsummary: pass={passes} fail={len(fails)}\n")

    print(f"pass={passes} fail={len(fails)}  report: {report_path}")
    if fails:
        print("\nPHASE C: FAIL", file=sys.stderr)
        for name, exp, act in fails:
            print(f"  {name}: declared={exp!r} actual={act!r}", file=sys.stderr)
        sys.exit(1)
    print("PHASE C: PASS")


if __name__ == "__main__":
    main()
