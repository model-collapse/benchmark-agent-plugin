# SPDX-License-Identifier: Apache-2.0
from benchmark_engine.engine.launcher import LocalProcessLauncher
from benchmark_engine.engine.step import Step
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_engine.model import RunStatus
from conftest import FakeDomain, make_base_config


def test_subprocess_rss_is_attributable(tmp_path):
    step = Step(name="m", fn="benchmark_engine.engine.sample_steps:mem_report", inputs={}, cacheable=False)
    r = LocalProcessLauncher().run(step, {}, tmp_path / "m")
    assert r.status == "COMPLETED"
    # a fresh child that allocated ~80 MB has an attributable peak well above it
    assert r.metrics["peak_rss_kb"] >= 70 * 1024


def test_inprocess_lifecycle_flags_memory_noncomparable(tmp_path):
    lr = run_lifecycle(make_base_config(0.9), FakeDomain(), workdir=tmp_path,
                       baseline=make_base_config(0.7))
    assert lr.result.status is RunStatus.COMPLETED
    assert lr.result.measurement_flags["memory_comparable"] is False
