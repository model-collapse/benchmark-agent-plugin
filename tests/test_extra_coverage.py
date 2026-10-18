"""Targeted tests for branches not hit by the happy/xpm paths."""

import os
import subprocess
import sys
import time

import pytest

from clusterbench_core.guard import GuardAction, monitor_process
from clusterbench_core.model import BenchmarkConfig, ResourceBudget, TreatmentVariable
from clusterbench_domains.demo import DemoDomain


def _cfg(v=0.5):
    cfg = BenchmarkConfig(domain="demo", hypothesis="h",
                          treatment_variable=TreatmentVariable("demo.knob", 1.0, v))
    cfg.set_param("demo.knob", v)
    return cfg


def test_demo_domain_in_process():
    d = DemoDomain()
    assert d.required_params() == {}
    assert "apply" in d.apply_config(_cfg(), None)["note"]
    assert d.verify_config(_cfg(), None) == {}
    art = d.prep(_cfg(), None)
    out = d.measure(_cfg(0.5), art, None)
    assert out.metrics["p50_ms"] == 12.5
    assert out.functional_validation["recall@10"] == 0.98
    assert out.phases[0].name == "measure"


def test_monitor_process_clean_exit():
    # a short-lived low-memory process stays under budget -> OK
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    budget = ResourceBudget(total_ram_kb=200 * 1024 * 1024)  # 200 GB, never breached
    action = monitor_process(proc.pid, budget, interval=0.1, max_seconds=5)
    assert action is GuardAction.OK
    proc.wait()


def test_monitor_process_missing_pid():
    # a pid that doesn't exist -> OK (nothing to guard)
    assert monitor_process(2_000_000_000, ResourceBudget(total_ram_kb=1000)) is GuardAction.OK


def test_guard_render_paths():
    from clusterbench_core.discipline.preflight import BaselineDiff, VerifyResult
    d = BaselineDiff(unexpected=[("x", 1, 2)], missing_from_new=[("y", 3)])
    assert "UNEXPECTED x" in d.render() and "MISSING y" in d.render()
    v = VerifyResult({"a": (1, 1, True), "b": (1, 2, False)})
    assert "PHASE C: FAIL" in v.render()


def test_reliability_render_and_report_abort():
    from clusterbench_core.discipline import analysis
    from clusterbench_core.discipline.reliability import reproduced_within_tolerance
    from clusterbench_core.model import ReliabilityTag, RunResult, RunStatus
    a = RunResult("a", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED,
                  metrics={"p50_ms": 10.0})
    b = RunResult("b", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED,
                  metrics={"p50_ms": 10.5})
    assert "REPRODUCED" in reproduced_within_tolerance(a, b).render()
    aborted = RunResult("r", "s", RunStatus.ABORTED_GUARDRAIL, ReliabilityTag.UNRELIABLE,
                        abort={"reason": "peak breached"})
    rep = analysis.generate_report(_cfg(), aborted)
    assert "## Abort" in rep and "peak breached" in rep
