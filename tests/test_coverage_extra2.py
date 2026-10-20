# SPDX-License-Identifier: Apache-2.0
"""Guard's real-kill branch, exercised against a real over-budget subprocess."""

import subprocess
import sys
import time

from benchmark_engine.guard import GuardAction, monitor_process
from benchmark_engine.model import ResourceBudget


def test_guard_kills_real_overbudget_process():
    # Child allocates ~150 MB resident and sleeps; budget emergency ceiling ~92 MB.
    code = "a=b'x'*(150*1024*1024)\nimport time; time.sleep(30)\n"
    proc = subprocess.Popen([sys.executable, "-c", code])
    time.sleep(0.6)  # let it fault in the allocation
    budget = ResourceBudget(total_ram_kb=100 * 1024)  # emergency ~ 94 MB
    try:
        action = monitor_process(proc.pid, budget, interval=0.2, max_seconds=15)
        assert action in (GuardAction.HARD_KILL, GuardAction.EMERGENCY_KILL)
        time.sleep(0.3)
        assert proc.poll() is not None  # the guard actually killed it
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
