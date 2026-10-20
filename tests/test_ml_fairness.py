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


def test_lifecycle_blocks_eval_suite_mismatch(tmp_path):   # review Important 2: wire the gate
    from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
    from benchmark_engine.lifecycle import run_lifecycle
    from benchmark_domains.command import CommandDomain

    def _cfg(suite_version):
        c = BenchmarkConfig(domain="command", hypothesis="h",
                            treatment_variable=TreatmentVariable(name="n", baseline_value=1, value=1))
        c.set_param("n", 1, source="treatment")
        c.set_param("eval_suite", "mmlu", source="controlled")
        c.set_param("eval_suite_version", suite_version, source="controlled")
        return c

    spec = {"stages": [{"name": "m", "cmd": "echo '{\"acc\": 1}'", "kind": "measure",
                        "metrics_from": {"stdout": True, "fields": ["acc"]}}],
            "treatment_variable": "n"}
    # candidate on suite v2.0 vs a baseline on v1.0 → not comparable
    lr = run_lifecycle(_cfg("2.0"), CommandDomain(spec, workroot=str(tmp_path / "c")),
                       workdir=str(tmp_path / "r"), baseline=_cfg("1.0"))
    assert lr.result.status.value == "ABORTED_PREFLIGHT"
    assert "eval" in (lr.result.abort or {}).get("reason", "").lower()
