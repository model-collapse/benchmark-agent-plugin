import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _grep(pattern, *paths, include="*"):
    existing = [str(ROOT / p) for p in paths if (ROOT / p).exists()]
    if not existing:
        return []
    # -I skips binary (stale .pyc); include scopes to source so build artifacts
    # under __pycache__ don't trip the guard.
    r = subprocess.run(["grep", "-rlI", f"--include={include}", pattern, *existing],
                       capture_output=True, text=True)
    return [line for line in r.stdout.splitlines() if line]


def test_no_clusterbench_imports_in_code():
    assert _grep("clusterbench_core", "benchmark_engine", "benchmark_ops",
                 "benchmark_domains", "experiments", include="*.py") == []


def test_no_experimaestro_in_user_docs():
    assert _grep("experimaestro", "README.md", "docs/benchmark/README.md",
                 "docs/benchmark/DOMAIN_API.md") == []
