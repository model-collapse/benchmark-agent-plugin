# SPDX-License-Identifier: Apache-2.0
"""Harness gap #1: a researcher's custom metric must be reproduction-gated when a
tolerance is declared on the config (not only the built-in IR/latency metrics)."""

from benchmark_engine.lifecycle import run_lifecycle
from benchmark_engine.model import ReliabilityTag, RunResult, RunStatus
from benchmark_engine.discipline.reliability import reproduced_within_tolerance

from conftest import FakeDomain, make_base_config


def test_config_declared_tolerance_gates_custom_metric():
    a = RunResult("a", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED, metrics={"ndcg@10": 0.50})
    b = RunResult("b", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED, metrics={"ndcg@10": 0.60})
    # 20% apart: reproduces under a loose tol, fails under a tight one
    assert reproduced_within_tolerance(a, b, tolerances={"ndcg@10": 0.30}).reproduced
    assert not reproduced_within_tolerance(a, b, tolerances={"ndcg@10": 0.05}).reproduced


def test_lifecycle_uses_config_tolerances(tmp_path):
    # a custom metric with a tight declared tolerance → a divergent reproduction is caught
    class NDCGDomain(FakeDomain):
        def __init__(self, score):
            super().__init__()
            self._score = score

        def measure(self, cfg, prep, ctx):
            out = super().measure(cfg, prep, ctx)
            out.metrics["ndcg@10"] = self._score
            return out

    cfg = make_base_config(0.9)
    cfg.reproduction_tolerances = {"ndcg@10": 0.02}
    first = run_lifecycle(cfg, NDCGDomain(0.50), workdir=tmp_path, baseline=make_base_config(0.7))
    cfg2 = make_base_config(0.9); cfg2.repro_nonce = 1
    cfg2.reproduction_tolerances = {"ndcg@10": 0.02}
    second = run_lifecycle(cfg2, NDCGDomain(0.40), workdir=tmp_path,  # 20% worse ndcg
                           baseline=make_base_config(0.7), prior=first.result)
    assert "NOT reproduced" in " ".join(second.result.notes)


def test_absolute_tolerance_dict_form():
    a = RunResult("a", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED, metrics={"accuracy": 0.90})
    b = RunResult("b", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED, metrics={"accuracy": 0.905})
    tol = {"accuracy": {"tol": 0.01, "absolute": True}}
    assert reproduced_within_tolerance(a, b, tol).reproduced            # +0.005 within 0.01
    b.metrics["accuracy"] = 0.95
    assert not reproduced_within_tolerance(a, b, tol).reproduced        # +0.05 out


def test_absolute_works_near_zero_where_relative_fails():
    a = RunResult("a", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED, metrics={"delta": 0.0})
    b = RunResult("b", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED, metrics={"delta": 0.0005})
    assert reproduced_within_tolerance(a, b, {"delta": {"tol": 0.001, "absolute": True}}).reproduced
    assert not reproduced_within_tolerance(a, b, {"delta": 0.001}).reproduced  # relative: /~0 → fails
