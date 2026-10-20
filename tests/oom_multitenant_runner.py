# SPDX-License-Identifier: Apache-2.0
"""In-container runner for the MULTI-TENANT OOM test.

A shared memory cgroup (Docker --memory, no swap) holds two tenants:
  - CO : an innocent neighbor holding ~600 MB (must survive)
  - EXP: a runaway experiment the harness monitors

Hazard: when the shared cap is hit, the kernel OOM-killer picks the LARGEST
process — which (while EXP is still growing) is the innocent CO. Raw cgroup
limits can therefore sacrifice the wrong tenant.

Claim: the harness guard kills EXP at its own budget, BEFORE the shared cap is
reached, so CO survives and the kernel OOM-killer never fires.

Prints one line the test parses:
    MODE=<guard|noguard> ACTION=<...> EXP_RC=<int> CO_RC=<int> CO_ALIVE=<bool> OOM_KILL=<int>
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, "/repo")

from benchmark_engine.guard import monitor_process          # noqa: E402
from benchmark_engine.model import ResourceBudget           # noqa: E402

# Protect the reporter itself from the OOM-killer, and ensure single-victim
# (not whole-cgroup) OOM so we can observe WHICH tenant the kernel picks.
for path, val in (("/proc/self/oom_score_adj", "-1000"),
                  ("/sys/fs/cgroup/memory.oom.group", "0")):
    try:
        open(path, "w").write(val)
    except Exception:  # noqa: BLE001
        pass

_CO = [sys.executable, "-c",
       "import time; a = bytearray(600*1024*1024); open('/tmp/co_ready','w').write('1'); time.sleep(600)"]
_EXP = [sys.executable, "-c",
        "import time\nb=[]\nwhile True:\n b.append(bytearray(20*1024*1024)); time.sleep(0.05)"]


def _oom_kills() -> int:
    try:
        for line in open("/sys/fs/cgroup/memory.events"):
            if line.startswith("oom_kill "):
                return int(line.split()[1])
    except Exception:  # noqa: BLE001
        return -1
    return 0


def main() -> None:
    mode = sys.argv[1]
    co = subprocess.Popen(_CO)
    for _ in range(100):                      # wait until the neighbor is resident
        if os.path.exists("/tmp/co_ready"):
            break
        time.sleep(0.1)
    exp = subprocess.Popen(_EXP)

    action = "NONE"
    if mode == "guard":
        # EXP budget 300 MB ⇒ emergency ≈ 276 MB; 600(CO)+276(EXP)+overhead < cap
        a = monitor_process(exp.pid, ResourceBudget(total_ram_kb=300 * 1024), interval=0.1)
        action = a.value
    else:
        t0 = time.time()                      # wait for the kernel to OOM-kill a tenant
        while time.time() - t0 < 25:
            if co.poll() is not None or exp.poll() is not None:
                break
            time.sleep(0.1)

    co_alive = co.poll() is None              # sample BEFORE cleanup
    for p in (co, exp):
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    print(f"MODE={mode} ACTION={action} EXP_RC={exp.returncode} CO_RC={co.returncode} "
          f"CO_ALIVE={co_alive} OOM_KILL={_oom_kills()}")


if __name__ == "__main__":
    main()
