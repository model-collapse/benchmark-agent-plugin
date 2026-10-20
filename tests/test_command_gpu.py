from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_domains.command import CommandDomain


class _Probe:
    def __init__(self, mb):
        self._mb = mb

    def used_mb(self, device_ids):
        return self._mb


def _cfg(n=1):
    cfg = BenchmarkConfig(domain="command", hypothesis="h",
                          treatment_variable=TreatmentVariable(name="n", baseline_value=n, value=n))
    cfg.set_param("n", n, source="treatment")
    return cfg


def _spec():
    return {"stages": [
        {"name": "train", "cmd": "sleep 0.2; echo done > {ckpt}", "produces": ["ckpt"],
         "kind": "prep", "resources": {"gpus": 2, "vram_mb": 40000}},
        {"name": "eval", "cmd": "echo '{\"acc\": 0.9}'", "needs": ["train"], "kind": "measure",
         "metrics_from": {"stdout": True, "fields": ["acc"]}}],
        "treatment_variable": "n"}


def test_gpu_hours_recorded(tmp_path):
    d = CommandDomain(_spec(), workroot=str(tmp_path / "c"), gpu_probe=_Probe(1000))
    lr = run_lifecycle(_cfg(), d, workdir=str(tmp_path / "r"), baseline=_cfg())
    assert lr.result.status.value == "COMPLETED"
    assert lr.result.metrics["gpu_hours"] > 0        # 2 gpus × elapsed


def test_vram_oom_fails_loud(tmp_path):
    d = CommandDomain(_spec(), workroot=str(tmp_path / "c"), gpu_probe=_Probe(80000))  # > 40000 budget
    lr = run_lifecycle(_cfg(), d, workdir=str(tmp_path / "r"), baseline=_cfg())
    assert lr.result.status.value != "COMPLETED"      # VRAM-OOM aborts, not a clean run


def test_cuda_visible_devices_pinned(tmp_path):
    spec = {"stages": [
        {"name": "probe", "cmd": "echo \"{\\\"v\\\": \\\"${CUDA_VISIBLE_DEVICES:-unset}\\\"}\"",
         "kind": "measure", "resources": {"gpus": 2},
         "metrics_from": {"stdout": True, "fields": ["v"]}}],
        "treatment_variable": "n"}
    d = CommandDomain(spec, workroot=str(tmp_path / "c"), gpu_probe=_Probe(0))
    lr = run_lifecycle(_cfg(), d, workdir=str(tmp_path / "r"), baseline=_cfg())
    assert lr.result.metrics["v"] == "0,1"
