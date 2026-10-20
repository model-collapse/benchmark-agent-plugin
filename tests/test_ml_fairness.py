import pytest
from benchmark_engine.fingerprint import (
    env_fingerprint, assert_comparable_fingerprint, assert_comparable_eval,
    BaselineFingerprintMismatch, COMPARABILITY_KEYS)


def test_accelerator_in_fingerprint():
    fp = env_fingerprint()
    assert "accelerator" in fp and "accelerator" in COMPARABILITY_KEYS


def test_cross_accelerator_refused():
    a = dict(env_fingerprint()); a["accelerator"] = "A100"
    b = dict(a); b["accelerator"] = "H100"
    with pytest.raises(BaselineFingerprintMismatch):
        assert_comparable_fingerprint(a, b)


def test_eval_suite_mismatch_refused():
    with pytest.raises(BaselineFingerprintMismatch):
        assert_comparable_eval({"eval_suite": "mmlu", "eval_suite_version": "1.0"},
                               {"eval_suite": "mmlu", "eval_suite_version": "2.0"})


def test_eval_suite_match_ok():
    assert_comparable_eval({"eval_suite": "mmlu", "eval_suite_version": "1.0"},
                           {"eval_suite": "mmlu", "eval_suite_version": "1.0"})
