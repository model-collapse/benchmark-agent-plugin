# SPDX-License-Identifier: Apache-2.0
from benchmark_engine.engine.launcher import InProcessLauncher, LocalProcessLauncher
from benchmark_engine.engine.step import Step
from benchmark_engine.model import ResourceBudget


def _step(fn):
    return Step(name="t", fn=fn, inputs={}, cache_key=None, cacheable=False, depends_on=[])


def test_inprocess_runs_and_captures(tmp_path):
    r = InProcessLauncher().run(_step("benchmark_engine.engine.sample_steps:add"), {"a": 2, "b": 3}, tmp_path / "a")
    assert r.status == "COMPLETED"
    assert r.metrics["s"] == 5
    assert r.effective_params == {"a": 2}


def test_inprocess_failure_is_captured(tmp_path):
    r = InProcessLauncher().run(_step("benchmark_engine.engine.sample_steps:boom"), {}, tmp_path / "b")
    assert r.status == "FAILED" and "intentional failure" in r.error


def test_launcher_parity(tmp_path):
    a = InProcessLauncher().run(_step("benchmark_engine.engine.sample_steps:add"), {"a": 2, "b": 3}, tmp_path / "ip")
    b = LocalProcessLauncher().run(_step("benchmark_engine.engine.sample_steps:add"), {"a": 2, "b": 3}, tmp_path / "lp")
    assert a.status == b.status == "COMPLETED"
    assert a.metrics["s"] == b.metrics["s"] == 5


def test_localprocess_guard_aborts_overbudget(tmp_path):
    budget = ResourceBudget(total_ram_kb=100 * 1024)  # emergency ~94 MB; hog uses ~150 MB
    r = LocalProcessLauncher(budget=budget).run(
        _step("benchmark_engine.engine.sample_steps:hog"), {}, tmp_path / "hog"
    )
    assert r.status == "ABORTED_GUARDRAIL"


def test_localprocess_normal_exit_under_budget_does_not_hang(tmp_path):
    # a normally-exiting child under a (never-breached) budget must return COMPLETED,
    # not hang on a zombie process the parent hasn't reaped
    from benchmark_engine.model import ResourceBudget
    budget = ResourceBudget(total_ram_kb=200 * 1024 * 1024)  # 200 GB, never breached
    r = LocalProcessLauncher(budget=budget).run(
        _step("benchmark_engine.engine.sample_steps:add"), {"a": 2, "b": 3}, tmp_path / "ok")
    assert r.status == "COMPLETED" and r.metrics["s"] == 5
