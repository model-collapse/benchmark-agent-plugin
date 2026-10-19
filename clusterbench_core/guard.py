"""OOM guard (plugin's guardrail).

Pure decision logic in `OOMGuard` (deterministically unit-tested) plus a real
polling sidecar `monitor_process` for the happy paths. Thresholds come from the
BenchmarkConfig's ResourceBudget, never magic numbers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from clusterbench_core.model import ResourceBudget


class GuardAction(str, Enum):
    OK = "OK"
    WARN = "WARN"
    HARD_KILL = "HARD_KILL"
    EMERGENCY_KILL = "EMERGENCY_KILL"


@dataclass
class OOMGuard:
    budget: ResourceBudget
    warn_sustained: int = 6     # samples
    hard_sustained: int = 2
    _warn_count: int = 0
    _hard_count: int = 0

    def observe(self, rss_kb: int) -> GuardAction:
        """Feed one RSS sample; return the action to take now."""
        if rss_kb > self.budget.emergency_kb:
            return GuardAction.EMERGENCY_KILL
        if rss_kb > self.budget.hard_kb:
            self._hard_count += 1
            self._warn_count = 0
            if self._hard_count >= self.hard_sustained:
                return GuardAction.HARD_KILL
            return GuardAction.WARN
        if rss_kb > self.budget.warn_kb:
            self._hard_count = 0
            self._warn_count += 1
            return GuardAction.WARN
        self._warn_count = 0
        self._hard_count = 0
        return GuardAction.OK


def evaluate_stream(budget: ResourceBudget, samples: list[int], **kw) -> GuardAction:
    """Run a guard over a list of samples; return the first terminal action, else
    the last non-terminal action."""
    g = OOMGuard(budget=budget, **kw)
    last = GuardAction.OK
    for s in samples:
        a = g.observe(s)
        if a in (GuardAction.HARD_KILL, GuardAction.EMERGENCY_KILL):
            return a
        last = a
    return last


def monitor_process(pid: int, budget: ResourceBudget, interval: float = 1.0,
                    on_event=None, max_seconds: float | None = None):
    """Poll a process tree's RSS; SIGTERM then SIGKILL on breach. Returns the
    terminal GuardAction (or OK if the process exited cleanly). Used by the real
    happy-path runs; not exercised in deterministic unit tests."""
    import os
    import signal

    import psutil

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return GuardAction.OK
    guard = OOMGuard(budget=budget)
    start = time.time()
    while True:
        if not proc.is_running():
            return GuardAction.OK
        try:
            rss = proc.memory_info().rss
            for ch in proc.children(recursive=True):
                try:
                    rss += ch.memory_info().rss
                except psutil.Error:
                    pass
        except psutil.Error:
            return GuardAction.OK
        action = guard.observe(rss // 1024)
        if on_event and action != GuardAction.OK:
            on_event(action, rss // 1024)
        if action in (GuardAction.HARD_KILL, GuardAction.EMERGENCY_KILL):
            sig = signal.SIGKILL if action == GuardAction.EMERGENCY_KILL else signal.SIGTERM
            try:
                os.kill(pid, sig)
                if sig == signal.SIGTERM:
                    time.sleep(5)
                    if proc.is_running():
                        os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return action
        if max_seconds and (time.time() - start) > max_seconds:
            return GuardAction.OK
        time.sleep(interval)
