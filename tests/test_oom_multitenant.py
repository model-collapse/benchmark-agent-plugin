"""Multi-tenant OOM: in a shared memory cgroup, the harness guard protects an
innocent neighbor by killing the runaway experiment before the kernel OOM-killer
has to pick a victim (which, left to the kernel, is the larger innocent tenant).

Opt-in (`-m oom_fidelity`) — needs Docker; pulls python:3.11-slim.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.oom_fidelity, pytest.mark.happy]


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def _run(mode: str) -> dict:
    cmd = [
        "docker", "run", "--rm",
        "--memory=1100m", "--memory-swap=1100m",   # shared hard cap, no swap
        "-v", f"{REPO}:/repo:ro", "-w", "/repo",
        "python:3.11-slim", "bash", "-c",
        f"pip install -q psutil >/dev/null 2>&1 && PYTHONPATH=/repo "
        f"python tests/oom_multitenant_runner.py {mode}",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    m = re.search(r"MODE=(\S+) ACTION=(\S+) EXP_RC=(\S+) CO_RC=(\S+) CO_ALIVE=(\S+) OOM_KILL=(\S+)",
                  out.stdout)
    assert m, f"runner produced no result line.\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}"
    return {"mode": m[1], "action": m[2], "exp_rc": int(m[3]), "co_rc": int(m[4]),
            "co_alive": m[5] == "True", "oom_kill": int(m[6])}


@pytest.mark.skipif(not _docker_ok(), reason="Docker not available")
def test_guard_protects_the_innocent_neighbor():
    guard = _run("guard")
    noguard = _run("noguard")

    # GUARD ON: the harness terminated the runaway experiment at its budget; the
    # shared cap was never reached, so the kernel never fired and the neighbor lives.
    assert guard["action"] in ("HARD_KILL", "EMERGENCY_KILL"), guard
    assert guard["co_alive"] is True, guard
    assert guard["oom_kill"] == 0, guard

    # GUARD OFF: the runaway drives the shared cgroup to its cap; the kernel
    # OOM-killer fires and sacrifices the INNOCENT neighbor (the larger tenant).
    assert noguard["oom_kill"] >= 1, noguard
    assert noguard["co_alive"] is False, noguard

    # the contrast is the proof: the guard is what keeps the neighbor alive.
    assert guard["co_alive"] and not noguard["co_alive"]
