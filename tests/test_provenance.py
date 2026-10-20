# SPDX-License-Identifier: Apache-2.0
import pytest

from benchmark_engine.discipline.reliability import fairness_assert
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_engine.model import ReliabilityTag, RunResult, RunStatus

from conftest import FakeDomain, make_base_config


def test_provenance_fields_present(tmp_path):
    lr = run_lifecycle(make_base_config(0.9), FakeDomain(), workdir=tmp_path,
                       baseline=make_base_config(0.7))
    p = lr.result.provenance
    for key in ("declared_signature", "effective_signature", "code_version",
                "host", "launcher", "timestamp", "resource_limits"):
        assert key in p
    assert p["launcher"] == "InProcessLauncher"


def test_fairness_assert_catches_contradiction():
    bad = RunResult("r", "s", RunStatus.COMPLETED, ReliabilityTag.RELIABLE,
                    signature_diff={"x": {"declared": 1, "effective": 2}})
    with pytest.raises(AssertionError):
        fairness_assert(bad)


def test_fairness_assert_ok_when_unreliable():
    ok = RunResult("r", "s", RunStatus.COMPLETED, ReliabilityTag.UNRELIABLE,
                   signature_diff={"x": {"declared": 1, "effective": 2}})
    fairness_assert(ok)  # no raise — UNRELIABLE with a diff is the correct outcome


def test_lifecycle_freezes_config(tmp_path):
    from benchmark_engine.model import FrozenConfigError
    import pytest
    cfg = make_base_config(0.9)
    run_lifecycle(cfg, FakeDomain(), workdir=tmp_path, baseline=make_base_config(0.7))
    # Gate 1 enforced in the pipeline: the submitted config is now frozen
    with pytest.raises(FrozenConfigError):
        cfg.set_param("fake.n_postings", 1)
