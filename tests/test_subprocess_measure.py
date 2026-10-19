# SPDX-License-Identifier: Apache-2.0
"""Issue #3: opt-in subprocess measurement → per-trial attributable RSS."""

import benchmark_domains.demo as demo
from benchmark_domains.demo import DemoDomain
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_engine.model import BenchmarkConfig, RunStatus, TreatmentVariable


def _cfg(knob=0.5):
    c = BenchmarkConfig(domain="demo", hypothesis="h",
                        treatment_variable=TreatmentVariable("demo.knob", 0.5, knob))
    c.set_param("demo.knob", knob)
    c.set_param("demo.n", 1000)
    return c


def test_in_process_measure_is_memory_noncomparable(tmp_path):
    lr = run_lifecycle(_cfg(), DemoDomain(), workdir=tmp_path)
    assert lr.result.status is RunStatus.COMPLETED
    assert lr.result.measurement_flags["memory_comparable"] is False


def test_subprocess_measure_is_memory_comparable(tmp_path):
    lr = run_lifecycle(_cfg(), DemoDomain(), workdir=tmp_path, measure_in_subprocess=True)
    assert lr.result.status is RunStatus.COMPLETED
    assert lr.result.measurement_flags["memory_comparable"] is True
    # effective params captured in the subprocess still surface + gate passes
    assert lr.result.reliability_tag.value in ("RELIABLE", "QUALIFIED")
    assert lr.result.metrics["p50_ms"] == 12.5  # 10 + 5*0.5, same as in-process
