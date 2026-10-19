# SPDX-License-Identifier: Apache-2.0
"""Launchers: how a step's function is actually run.

A step function takes its resolved inputs as kwargs and returns an optional dict
with any of {metrics, outputs, effective_params, phases}. Two launchers:

- ``InProcessLauncher`` — call it here. Fast; shares the process (so memory is not
  per-trial attributable — see the measurement-comparability gate).
- ``LocalProcessLauncher`` — run it in a subprocess via ``worker.py`` with the OOM
  guard monitoring the child; attributable RSS and crash isolation. Default when
  memory is a reported/selected metric.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from clusterbench_core.engine.step import Step, StepResult
from clusterbench_core.guard import GuardAction, monitor_process
from clusterbench_core.model import ResourceBudget

_RESULT_KEYS = ("metrics", "outputs", "effective_params", "phases")
_REPO_ROOT = str(Path(__file__).resolve().parents[2])


class InProcessLauncher:
    # NB: does NOT chdir — cwd is process-global and the scheduler may run steps in
    # parallel threads. Step fns do not rely on cwd; the subprocess launcher chdirs
    # safely in its own process.
    def run(self, step: Step, resolved_inputs: dict[str, Any], workdir: str | Path) -> StepResult:
        Path(workdir).mkdir(parents=True, exist_ok=True)
        try:
            if callable(step.fn):
                f = step.fn
            else:
                mod, _, fn = step.fn.partition(":")
                f = getattr(importlib.import_module(mod), fn)
            out = f(**resolved_inputs) or {}
            return StepResult(status="COMPLETED", **{k: out[k] for k in _RESULT_KEYS if k in out})
        except Exception as e:  # noqa: BLE001
            return StepResult(status="FAILED", error=repr(e))


class LocalProcessLauncher:
    def __init__(self, budget: ResourceBudget | None = None, poll_interval: float = 0.2):
        self.budget = budget
        self.poll_interval = poll_interval

    def run(self, step: Step, resolved_inputs: dict[str, Any], workdir: str | Path) -> StepResult:
        if not isinstance(step.fn, str):
            raise TypeError("LocalProcessLauncher needs a 'module:function' fn, not a callable")
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        result_path = workdir / "result.json"
        spec = {"fn": step.fn, "inputs": resolved_inputs,
                "workdir": str(workdir), "result_path": str(result_path)}
        spec_file = workdir / "spec.json"
        spec_file.write_text(json.dumps(spec))

        env = dict(os.environ)
        env["PYTHONPATH"] = _REPO_ROOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

        proc = subprocess.Popen(
            [sys.executable, "-m", "clusterbench_core.engine.worker", str(spec_file)], env=env
        )
        if self.budget is not None:
            # Monitor in a thread while the main thread reaps the child. Reaping is
            # what lets monitor_process see the process end (an unreaped exited child
            # is a zombie that psutil still reports as running → the guard would spin).
            import threading
            result: dict = {}

            def _mon():
                result["action"] = monitor_process(proc.pid, self.budget, interval=self.poll_interval)

            th = threading.Thread(target=_mon, daemon=True)
            th.start()
            proc.wait()
            th.join(timeout=5)
            if result.get("action") in (GuardAction.HARD_KILL, GuardAction.EMERGENCY_KILL):
                return StepResult(status="ABORTED_GUARDRAIL", error=f"guard {result['action'].value}")
        else:
            proc.wait()

        if not result_path.exists():
            return StepResult(status="FAILED", error="worker produced no result")
        d = json.loads(result_path.read_text())
        return StepResult(
            status=d.get("status", "FAILED"),
            metrics=d.get("metrics") or {},
            outputs=d.get("outputs") or {},
            effective_params=d.get("effective_params") or {},
            phases=d.get("phases") or [],
            error=d.get("error", ""),
        )
