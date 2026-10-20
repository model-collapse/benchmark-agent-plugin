from benchmark_engine.resources import (
    GpuSpec, pin_env, gpu_hours, cost, NullProbe, default_probe)


def test_gpuspec_from_dict():
    g = GpuSpec.from_dict({"gpus": 4, "vram_mb": 72000, "est_gpu_hours": 6})
    assert (g.gpus, g.vram_mb, g.est_gpu_hours) == (4, 72000, 6)
    assert GpuSpec.from_dict(None).gpus == 0


def test_pin_env_sets_visible_devices():
    env = pin_env({"PATH": "/x"}, [0, 2, 3])
    assert env["CUDA_VISIBLE_DEVICES"] == "0,2,3"
    assert env["PATH"] == "/x"
    assert pin_env({"A": "1"}, []) == {"A": "1"}


def test_accounting_math():
    assert gpu_hours(4, 3600) == 4.0
    assert cost(4.0, 2.5) == 10.0


def test_null_probe_and_default_never_crash():
    assert NullProbe().used_mb([0, 1]) == 0
    p = default_probe()                 # CPU box → NullProbe; must not raise
    assert p.used_mb([0]) >= 0
