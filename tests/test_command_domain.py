import pytest
from pathlib import Path
from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_domains.command import CommandDomain


def _cfg(n=3):
    cfg = BenchmarkConfig(domain="command", hypothesis="h",
                          treatment_variable=TreatmentVariable(name="n", baseline_value=n, value=n))
    cfg.set_param("n", n, source="treatment")
    return cfg


def _spec(build='echo {n} > {idx}'):
    return {"stages": [
        {"name": "prep", "cmd": build, "produces": ["idx"], "kind": "prep"},
        {"name": "measure", "cmd": 'echo \'{"score": 7}\'', "needs": ["prep"],
         "kind": "measure", "metrics_from": {"stdout": True, "fields": ["score"]}}],
        "treatment_variable": "n"}


def test_pipeline_runs_end_to_end(tmp_path):
    lr = run_lifecycle(_cfg(), CommandDomain(_spec()), workdir=str(tmp_path), baseline=_cfg())
    assert lr.result.status.value == "COMPLETED"
    assert lr.result.metrics["score"] == 7


def test_prep_stage_is_cached_across_runs(tmp_path):
    marker = tmp_path / "ran"
    spec = {"stages": [
        {"name": "prep",
         "cmd": "python -c \"open('{idx}','w').write('x'); open('%s','a').write('1')\"" % marker,
         "produces": ["idx"], "kind": "prep"},
        {"name": "measure", "cmd": 'echo \'{"score": 7}\'', "needs": ["prep"],
         "kind": "measure", "metrics_from": {"stdout": True, "fields": ["score"]}}],
        "treatment_variable": "n"}
    d = CommandDomain(spec, workroot=str(tmp_path / "cache"))
    run_lifecycle(_cfg(), d, workdir=str(tmp_path / "a"), baseline=_cfg())
    run_lifecycle(_cfg(), d, workdir=str(tmp_path / "b"), baseline=_cfg())
    assert marker.read_text() == "1"   # prep ran once; 2nd run hit the inner cache


def test_cache_key_includes_cmd(tmp_path):   # Review Focus: changed cmd invalidates cache
    shared = str(tmp_path / "shared")
    read_measure = {"name": "measure",
                    "cmd": "python -c \"import json;print(json.dumps({'v': open('{idx}').read().strip()}))\"",
                    "needs": ["prep"], "kind": "measure",
                    "metrics_from": {"stdout": True, "fields": ["v"]}}
    specA = {"stages": [{"name": "prep", "cmd": "echo A > {idx}", "produces": ["idx"], "kind": "prep"}, read_measure],
             "treatment_variable": "n"}
    specB = {"stages": [{"name": "prep", "cmd": "echo B > {idx}", "produces": ["idx"], "kind": "prep"}, read_measure],
             "treatment_variable": "n"}
    a = run_lifecycle(_cfg(), CommandDomain(specA, workroot=shared), workdir=str(tmp_path / "a"), baseline=_cfg())
    b = run_lifecycle(_cfg(), CommandDomain(specB, workroot=shared), workdir=str(tmp_path / "b"), baseline=_cfg())
    assert a.result.metrics["v"] == "A"
    assert b.result.metrics["v"] == "B"   # different cmd ⇒ cache miss, not a stale "A"


def test_failed_measure_stage_marks_run_failed(tmp_path):   # review Critical 1
    spec = {"stages": [
        {"name": "prep", "cmd": "echo x > {idx}", "produces": ["idx"], "kind": "prep"},
        {"name": "measure", "cmd": "exit 7", "needs": ["prep"], "kind": "measure"}],
        "treatment_variable": "n"}
    lr = run_lifecycle(_cfg(), CommandDomain(spec, workroot=str(tmp_path / "c")),
                       workdir=str(tmp_path / "r"), baseline=_cfg())
    assert lr.result.status.value != "COMPLETED"        # a crashed measure is NOT a clean run
    assert lr.result.reliability_tag.value != "QUALIFIED"


def test_downstream_prep_cache_tracks_upstream_change(tmp_path):   # review Critical 2
    shared = str(tmp_path / "shared")

    def spec():
        return {"stages": [
            {"name": "a", "cmd": "echo built-with-n={n} > {xa}", "produces": ["xa"], "kind": "prep"},
            {"name": "b", "cmd": "cp {xa} {xb}", "needs": ["a"], "produces": ["xb"], "kind": "prep"},
            {"name": "measure",
             "cmd": "python -c \"import json;print(json.dumps({'v': open('{xb}').read().strip()}))\"",
             "needs": ["b"], "kind": "measure", "metrics_from": {"stdout": True, "fields": ["v"]}}],
            "treatment_variable": "n"}
    r3 = run_lifecycle(_cfg(3), CommandDomain(spec(), workroot=shared), workdir=str(tmp_path / "a"), baseline=_cfg(3))
    r7 = run_lifecycle(_cfg(7), CommandDomain(spec(), workroot=shared), workdir=str(tmp_path / "b"), baseline=_cfg(7))
    assert r3.result.metrics["v"] == "built-with-n=3"
    assert r7.result.metrics["v"] == "built-with-n=7"   # downstream prep must NOT serve a stale n=3 artifact
