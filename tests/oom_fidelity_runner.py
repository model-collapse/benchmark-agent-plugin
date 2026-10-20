# SPDX-License-Identifier: Apache-2.0
"""In-container runner for the high-fidelity OOM test.

Runs INSIDE a Docker container with a real kernel-enforced memory cgroup
(`--memory=... --memory-swap=...`, no swap). It spawns a runaway child that
allocates without bound and, in `guard` mode, runs the ACTUAL harness guard
(`benchmark_engine.guard.monitor_process`) against it with a budget tighter than
the cgroup cap.

Prints one line the test parses:
    MODE=<guard|noguard> ACTION=<...> CHILD_RC=<int> OOM_KILL=<int>

Expected contrast:
  guard   → ACTION=HARD_KILL/EMERGENCY_KILL, OOM_KILL=0   (harness preempts the kernel)
  noguard → ACTION=NONE,                     OOM_KILL>=1  (kernel OOM-killer fires)
"""

import subprocess
import sys

sys.path.insert(0, "/repo")

from benchmark_engine.guard import monitor_process          # noqa: E402
from benchmark_engine.model import ResourceBudget           # noqa: E402

# a runaway: allocate 20 MB of resident memory every 50 ms, forever
_CHILD = [sys.executable, "-c",
          "import time\nb=[]\nwhile True:\n b.append(bytearray(20*1024*1024)); time.sleep(0.05)"]


def _oom_kills() -> int:
    """cgroup v2 oom_kill counter for this container's own cgroup."""
    try:
        for line in open("/sys/fs/cgroup/memory.events"):
            if line.startswith("oom_kill "):
                return int(line.split()[1])
    except Exception:  # noqa: BLE001
        return -1
    return 0


def main() -> None:
    mode = sys.argv[1]
    child = subprocess.Popen(_CHILD)
    action = "NONE"
    if mode == "guard":
        # budget total 400 MB ⇒ emergency ≈ 368 MB, well under the container cap
        a = monitor_process(child.pid, ResourceBudget(total_ram_kb=400 * 1024), interval=0.1)
        action = a.value
    child.wait()   # noguard: blocks until the kernel OOM-killer reaps the child
    print(f"MODE={mode} ACTION={action} CHILD_RC={child.returncode} OOM_KILL={_oom_kills()}")


if __name__ == "__main__":
    main()
