import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parents[1] / "plugin" / "hooks" / "benchmark_awareness.py"


def _run(payload: dict) -> str:
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=10)
    return p.stdout.strip()


def _make_home(tmp_path):
    home = tmp_path / "benchmark_data"
    (home / "runs" / "opensearch__seg=1__abc").mkdir(parents=True)
    (home / "results_index.md").write_text("# Benchmark Results Index\n## Active Baselines\n")
    (home / "lessons.md").write_text("# Lessons\n## L1 cold caches invert pruning results\n")
    return home


def test_hook_silent_without_home(tmp_path):
    out = _run({"hook_event_name": "SessionStart", "cwd": str(tmp_path)})
    assert out == ""


def test_hook_emits_context_on_session_start(tmp_path):
    _make_home(tmp_path)
    out = _run({"hook_event_name": "SessionStart", "cwd": str(tmp_path)})
    data = json.loads(out)
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert "Benchmark Awareness" in ctx
    assert "results index" in ctx.lower()
    assert "benchmark" in ctx.lower()


def test_hook_prompt_gating(tmp_path):
    _make_home(tmp_path)
    # weak/irrelevant prompt -> silent
    assert _run({"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path),
                 "prompt": "what's the weather"}) == ""
    # strong signal -> emits
    out = _run({"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path),
                "prompt": "benchmark SPLADE force-merge latency on opensearch"})
    assert "Benchmark Awareness" in out
