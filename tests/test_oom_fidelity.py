"""High-fidelity OOM test: a REAL kernel-enforced memory cgroup (Docker --memory,
no swap) proves the harness guard preempts the kernel OOM-killer.

Opt-in (`-m oom_fidelity`) — needs Docker and pulls python:3.11-slim.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
# `oom_fidelity` selects it specifically; `happy` keeps it out of the default
# fast suite (`-m "not happy"`), since it's opt-in real-infra like the happy paths.
pytestmark = [pytest.mark.oom_fidelity, pytest.mark.happy]


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def _run(mode: str) -> dict:
    """Run the in-container runner under a 700 MB hard cgroup (no swap)."""
    cmd = [
        "docker", "run", "--rm",
        "--memory=700m", "--memory-swap=700m",      # hard cap, no swap → real OOM
        "-v", f"{REPO}:/repo:ro", "-w", "/repo",
        "python:3.11-slim", "bash", "-c",
        f"pip install -q psutil >/dev/null 2>&1 && PYTHONPATH=/repo "
        f"python tests/oom_fidelity_runner.py {mode}",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    m = re.search(r"MODE=(\S+) ACTION=(\S+) CHILD_RC=(\S+) OOM_KILL=(\S+)", out.stdout)
    assert m, f"runner produced no result line.\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}"
    return {"mode": m[1], "action": m[2], "child_rc": int(m[3]), "oom_kill": int(m[4]),
            "docker_rc": out.returncode}


@pytest.mark.skipif(not _docker_ok(), reason="Docker not available")
def test_guard_preempts_kernel_oom_killer():
    guard = _run("guard")
    noguard = _run("noguard")

    # GUARD ON: the harness killed the runaway before the kernel had to —
    # the cgroup OOM-killer never fired.
    assert guard["action"] in ("HARD_KILL", "EMERGENCY_KILL"), guard
    assert guard["child_rc"] < 0, guard            # child died from a signal (the guard's)
    assert guard["oom_kill"] == 0, guard           # kernel OOM-killer did NOT fire

    # GUARD OFF: the same runaway hits the kernel cgroup cap and the OOM-killer
    # fires — exactly the machine-threatening event the guard prevents.
    assert noguard["action"] == "NONE", noguard
    assert noguard["oom_kill"] >= 1, noguard       # kernel OOM-killer fired

    # the contrast is the proof: guard preempts the kernel (0 vs >=1 oom_kills)
    assert guard["oom_kill"] < noguard["oom_kill"]
