#!/usr/bin/env python3
"""
Experiment Awareness Hook for Benchmark Agent Plugin

Transparently detects when a user is doing benchmark/empirical work and
injects relevant context (prior results, lessons, in-flight experiment status)
into Claude's prompt without requiring explicit skill invocation.

Hook events handled:
  - SessionStart: Check for in-flight experiments, surface completions/failures
  - UserPromptSubmit: Detect benchmark signals, load relevant history
  - PostToolUse[Bash]: Detect metric-producing commands, enrich reasoning

Output: JSON to stdout with hookSpecificOutput.additionalContext
"""

import glob
import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# Signal detection patterns
# ---------------------------------------------------------------------------

STRONG_SIGNALS = [
    r'\bbenchmark\b',
    r'\bperformance\b',
    r'\blatency\b',
    r'\bthroughput\b',
    r'\bRSS\b',
    r'\bpeak\s*memory\b',
    r'\bp50\b',
    r'\bp95\b',
    r'\bp99\b',
    r'\bQPS\b',
    r'\bforce.?merge\b',
    r'\brecall@\d+\b',
    r'\bIOPS\b',
    r'\bops/s\b',
]

WEAK_SIGNALS = [
    r'\bbefore and after\b',
    r'\bcompare\b',
    r'\bregress\b',
    r'\bimprove\b',
    r'\bfaster\b',
    r'\bslower\b',
    r'\boverhead\b',
    r'\bbaseline\b',
    r'\bprofil\w+\b',
]

METRIC_PATTERNS = [
    r'(\d+\.?\d*)\s*(ms|seconds?|s)\b',
    r'(\d+\.?\d*)\s*(GB|MB|KB)\b',
    r'(\d+\.?\d*)\s*(docs?/s|req/s|QPS|ops/s)\b',
    r'p(50|95|99|999)\s*[:=]\s*(\d+)',
    r'Peak\s+RSS',
    r'elapsed\s+\d+[:.]\d+',
]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def find_benchmark_home(cwd):
    """Walk up from cwd looking for benchmark_data/ directory."""
    path = os.path.abspath(cwd)
    for _ in range(5):
        candidate = os.path.join(path, "benchmark_data")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return None


def emit_context(text):
    """Output hook response that injects context into Claude's prompt."""
    output = {
        "hookSpecificOutput": {
            "additionalContext": text.strip()
        }
    }
    print(json.dumps(output), flush=True)


def check_pid_alive(pid_file):
    """Check if process in PID file is still running."""
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def load_section(filepath, section_header, max_lines=15):
    """Load a specific section from a markdown file."""
    try:
        with open(filepath) as f:
            lines = f.readlines()
    except (FileNotFoundError, PermissionError):
        return ""

    capturing = False
    result = []
    for line in lines:
        if section_header in line:
            capturing = True
            result.append(line.rstrip())
            continue
        if capturing:
            if line.startswith("## ") and len(result) > 1:
                break
            result.append(line.rstrip())
            if len(result) >= max_lines:
                break

    return "\n".join(result) if result else ""


def get_latest_reliable_run(bench_home):
    """Get the most recent RELIABLE run from results index."""
    index_file = os.path.join(bench_home, "results_index.md")
    try:
        with open(index_file) as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        return None

    in_active = False
    for line in content.split("\n"):
        if "Active Baselines" in line:
            in_active = True
            continue
        if in_active and line.startswith("| ") and not line.startswith("| Run") and not line.startswith("|--"):
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 4:
                return {"id": parts[0], "date": parts[1], "type": parts[2], "summary": parts[3]}
    return None


def find_relevant_lessons(lessons_file, prompt, max_lessons=3):
    """Find lessons that are relevant to the user's prompt."""
    try:
        with open(lessons_file) as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        return []

    lessons = []
    current_lesson = []
    for line in content.split("\n"):
        if line.startswith("## L") or line.startswith("## "):
            if current_lesson:
                lessons.append("\n".join(current_lesson))
            current_lesson = [line]
        elif current_lesson:
            current_lesson.append(line)
    if current_lesson:
        lessons.append("\n".join(current_lesson))

    prompt_lower = prompt.lower()
    keywords = set(re.findall(r'\b\w{4,}\b', prompt_lower))

    scored = []
    for lesson in lessons:
        lesson_lower = lesson.lower()
        score = sum(1 for kw in keywords if kw in lesson_lower)
        if score > 0:
            header = lesson.split("\n")[0]
            scored.append((score, header))

    scored.sort(reverse=True)
    return [header for _, header in scored[:max_lessons]]


def load_latest_settings(bench_home):
    """Load a one-line summary of the most recent cluster settings."""
    settings_dir = os.path.join(bench_home, "settings")
    if not os.path.isdir(settings_dir):
        return None

    files = sorted(glob.glob(os.path.join(settings_dir, "*.md")),
                   key=os.path.getmtime, reverse=True)
    if not files:
        return None

    try:
        with open(files[0]) as f:
            lines = f.readlines()
    except (FileNotFoundError, PermissionError):
        return None

    summary_parts = []
    for line in lines[:30]:
        if "Endpoint" in line or "endpoint" in line:
            summary_parts.append(line.strip().strip("|").strip())
        elif "SSH" in line or "ssh" in line:
            summary_parts.append(line.strip().strip("|").strip())

    return "; ".join(summary_parts[:2]) if summary_parts else os.path.basename(files[0])


# ---------------------------------------------------------------------------
# Hook handlers
# ---------------------------------------------------------------------------

def handle_session_start(input_data):
    """Check for in-flight experiments and load baseline context."""
    cwd = input_data.get("cwd", os.getcwd())
    bench_home = find_benchmark_home(cwd)
    if not bench_home:
        return

    messages = []

    monitors_dir = os.path.join(bench_home, "monitors")
    if not os.path.isdir(monitors_dir):
        return

    running = glob.glob(os.path.join(monitors_dir, "*.running"))
    for f in running:
        run_id = os.path.basename(f).replace(".running", "")
        complete_file = os.path.join(monitors_dir, f"{run_id}.complete")
        failed_file = os.path.join(monitors_dir, f"{run_id}.failed")

        if os.path.exists(complete_file):
            messages.append(
                f"Benchmark '{run_id}' completed while you were away. "
                f"Run /benchmark_agent analyze {run_id} for full analysis."
            )
            try:
                os.remove(f)
            except OSError:
                pass
        elif os.path.exists(failed_file):
            events_file = os.path.join(monitors_dir, f"{run_id}_events.log")
            last_event = ""
            try:
                with open(events_file) as ef:
                    lines = ef.readlines()
                    if lines:
                        last_event = f" Last event: {lines[-1].strip()}"
            except (FileNotFoundError, PermissionError):
                pass
            messages.append(
                f"Benchmark '{run_id}' FAILED.{last_event} "
                f"Investigate with /benchmark_agent analyze {run_id}"
            )
            try:
                os.remove(f)
            except OSError:
                pass
        else:
            pid_file = os.path.join(monitors_dir, f"{run_id}_monitor.pid")
            alive = check_pid_alive(pid_file)
            status = "monitor alive" if alive else "monitor DEAD — needs restart"
            messages.append(
                f"Benchmark '{run_id}' is in progress ({status}). "
                f"Use /benchmark_run resume to reconnect."
            )

    if messages:
        emit_context("[Experiment Awareness]\n" + "\n".join(messages))


def handle_user_prompt_submit(input_data):
    """Detect benchmark signals and inject experiment context."""
    prompt = input_data.get("prompt", "")
    if not prompt:
        return

    cwd = input_data.get("cwd", os.getcwd())
    bench_home = find_benchmark_home(cwd)
    if not bench_home:
        return

    strong_count = sum(1 for p in STRONG_SIGNALS if re.search(p, prompt, re.IGNORECASE))
    weak_count = sum(1 for p in WEAK_SIGNALS if re.search(p, prompt, re.IGNORECASE))

    if strong_count == 0 and weak_count < 2:
        return

    context_parts = []

    index_file = os.path.join(bench_home, "results_index.md")
    if os.path.exists(index_file):
        section = load_section(index_file, "Active Baselines", max_lines=15)
        if section:
            context_parts.append(section)

    if re.search(r'compare|vs|versus|before|prior|baseline|regress', prompt, re.IGNORECASE):
        latest = get_latest_reliable_run(bench_home)
        if latest:
            context_parts.append(
                f"Most recent RELIABLE baseline: {latest['id']} ({latest['date']}) — {latest['summary']}"
            )

    if strong_count >= 1:
        lessons_file = os.path.join(bench_home, "lessons.md")
        if os.path.exists(lessons_file):
            relevant = find_relevant_lessons(lessons_file, prompt, max_lessons=3)
            if relevant:
                context_parts.append("Relevant lessons:\n" + "\n".join(f"  - {h}" for h in relevant))

    if strong_count >= 2:
        settings = load_latest_settings(bench_home)
        if settings:
            context_parts.append(f"Cluster: {settings}")

    if context_parts:
        emit_context("[Experiment Awareness]\n" + "\n\n".join(context_parts))


def handle_post_tool_use(input_data):
    """Detect metric-producing commands and enrich reasoning."""
    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
        return

    tool_output = input_data.get("tool_output", "")
    if not tool_output:
        return

    metric_count = sum(1 for p in METRIC_PATTERNS if re.search(p, tool_output))
    if metric_count < 2:
        return

    cwd = input_data.get("cwd", os.getcwd())
    bench_home = find_benchmark_home(cwd)
    if not bench_home:
        return

    emit_context(
        "[Experiment Awareness] The command above produced metric/timing data. "
        "When interpreting these results: (1) account for every unit of the metric, "
        "(2) check measurement validity before celebrating, "
        "(3) verify comparison fairness if comparing to prior results. "
        "Prior baselines: benchmark_data/results_index.md"
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            sys.exit(0)
        input_data = json.loads(raw_input)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    hook_event = input_data.get("hook_event_name", "")

    if hook_event == "SessionStart":
        handle_session_start(input_data)
    elif hook_event == "UserPromptSubmit":
        handle_user_prompt_submit(input_data)
    elif hook_event == "PostToolUse":
        handle_post_tool_use(input_data)


if __name__ == "__main__":
    main()
