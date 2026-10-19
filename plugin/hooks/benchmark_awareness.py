#!/usr/bin/env python3
"""Benchmark-awareness hook for the unified benchmark plugin.

Detects benchmark/experiment work and injects prior context (results index,
lessons, recent runs) so the agent plans with memory. The single awareness hook
for the one `/benchmark` skill.
"""

import glob
import json
import os
import re
import sys

STRONG = [r"\bbenchmark\b", r"\bforce.?merge\b", r"\blatency\b", r"\bthroughput\b",
          r"\bp50\b", r"\bp95\b", r"\bp99\b", r"\bQPS\b", r"\brecall@\d+\b",
          r"\bSPLADE\b", r"\bSEISMIC\b", r"\bopensearch\b", r"\bOOM\b", r"\bpeak\s*mem",
          r"\bembedding\b", r"\bfine.?tun", r"\bcheckpoint\b", r"\beval\b"]
WEAK = [r"\bcompare\b", r"\bbaseline\b", r"\bfaster\b", r"\bslower\b",
        r"\bregress", r"\btune\b", r"\boptimi[sz]e\b", r"\bspeed\b"]


def find_home(cwd):
    path = os.path.abspath(cwd)
    for _ in range(5):
        cand = os.path.join(path, "benchmark_data")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return None


def emit(text):
    print(json.dumps({"hookSpecificOutput": {"additionalContext": text.strip()}}), flush=True)


def load_head(path, n=20):
    try:
        with open(path) as f:
            return "".join(f.readlines()[:n]).rstrip()
    except OSError:
        return ""


def handle(data):
    event = data.get("hook_event_name", "")
    cwd = data.get("cwd", os.getcwd())
    home = find_home(cwd)
    if not home:
        return

    if event == "UserPromptSubmit":
        prompt = data.get("prompt", "")
        strong = sum(1 for p in STRONG if re.search(p, prompt, re.I))
        weak = sum(1 for p in WEAK if re.search(p, prompt, re.I))
        if strong == 0 and weak < 2:
            return

    parts = []
    idx = os.path.join(home, "results_index.md")
    if os.path.exists(idx):
        parts.append("Prior benchmark results index:\n" + load_head(idx, 25))
    lessons = os.path.join(home, "lessons.md")
    if os.path.exists(lessons):
        parts.append("Lessons:\n" + load_head(lessons, 15))
    runs = sorted(glob.glob(os.path.join(home, "runs", "*")), reverse=True)[:5]
    if runs:
        parts.append("Recent runs:\n" + "\n".join("  - " + os.path.basename(r) for r in runs))
    if parts:
        hint = ("\n\nUse the benchmark skill (plan) to plan a fair, manifest-gated run "
                "before executing.")
        emit("[Benchmark Awareness]\n" + "\n\n".join(parts) + hint)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        handle(json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)


if __name__ == "__main__":
    main()
