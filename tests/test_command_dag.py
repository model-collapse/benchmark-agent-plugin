from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_domains.command import CommandDomain


def _cfg(n=3):
    cfg = BenchmarkConfig(domain="command", hypothesis="h",
                          treatment_variable=TreatmentVariable(name="n", baseline_value=n, value=n))
    cfg.set_param("n", n, source="treatment")
    return cfg


def test_cycle_blocks():
    spec = {"stages": [
        {"name": "a", "cmd": "echo {x}", "needs": ["b"], "kind": "prep"},
        {"name": "b", "cmd": "echo {y}", "needs": ["a"], "kind": "prep"}]}
    assert any("cycle" in e.lower() for e in CommandDomain(spec).validate(_cfg()))


def test_missing_needs_blocks():
    spec = {"stages": [{"name": "m", "cmd": "echo hi", "needs": ["ghost"], "kind": "measure"}]}
    assert any("ghost" in e for e in CommandDomain(spec).validate(_cfg()))


def test_unknown_placeholder_blocks():   # Review Focus
    spec = {"stages": [{"name": "m", "cmd": "echo {nope}", "kind": "measure"}]}
    assert any("nope" in e for e in CommandDomain(spec).validate(_cfg()))


def test_preflight_blocks_on_bad_dag(tmp_path):
    spec = {"stages": [{"name": "m", "cmd": "echo {nope}", "kind": "measure"}]}
    lr = run_lifecycle(_cfg(), CommandDomain(spec, workroot=str(tmp_path / "c")),
                       workdir=str(tmp_path / "r"), baseline=_cfg())
    assert lr.result.status.value == "ABORTED_PREFLIGHT"


def test_effective_from_trips_gate(tmp_path):
    # the measure stage "resolves" n=99 regardless of declared n=3 → effective != declared
    spec = {"stages": [
        {"name": "prep", "cmd": "echo x > {idx}", "produces": ["idx"], "kind": "prep"},
        {"name": "measure",
         "cmd": "python -c \"import json; json.dump({'n':99}, open('eff.json','w')); print(json.dumps({'score':1}))\"",
         "needs": ["prep"], "kind": "measure",
         "metrics_from": {"stdout": True, "fields": ["score"]},
         "effective_from": {"file": "eff.json"}}],
        "treatment_variable": "n"}
    lr = run_lifecycle(_cfg(3), CommandDomain(spec, workroot=str(tmp_path / "c")),
                       workdir=str(tmp_path / "r"), baseline=_cfg(3))
    assert lr.result.signature_diff          # n declared 3, effective 99
    assert lr.result.reliability_tag.value == "UNRELIABLE"
