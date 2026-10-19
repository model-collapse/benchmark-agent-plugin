import time
from benchmark_engine.engine.step import Step
from benchmark_engine.engine.scheduler import Scheduler
from benchmark_engine.engine.launcher import InProcessLauncher
from benchmark_domains.recipes.loader import load_recipe


def test_recipe_loads_with_required_params():
    spec = load_recipe("retrieval_index")
    assert spec["stages"] and spec.get("required_params")


def test_recipe_override_merges():
    spec = load_recipe("retrieval_index", {"treatment_variable": "forcemerge.max_num_segments"})
    assert spec["treatment_variable"] == "forcemerge.max_num_segments"


def _sleep_step(name, parallel_safe):
    def fn(**_):
        time.sleep(0.3)
        return {"metrics": {"acc": 1.0}}
    return Step(name=name, fn=fn, cacheable=False, parallel_safe=parallel_safe)


def test_parallel_safe_measures_overlap(tmp_path):
    steps = [_sleep_step("e1", True), _sleep_step("e2", True)]
    t = time.time()
    Scheduler(InProcessLauncher(), max_parallel=2).run(steps, tmp_path)
    assert time.time() - t < 0.5   # ran concurrently, not 0.6s serialized


def test_perf_measures_stay_serialized(tmp_path):
    steps = [_sleep_step("m1", False), _sleep_step("m2", False)]
    t = time.time()
    Scheduler(InProcessLauncher(), max_parallel=2).run(steps, tmp_path)
    assert time.time() - t >= 0.6   # serialized


def test_recipe_missing_required_param_is_blocked(tmp_path):   # Review Focus: recipe gate
    from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
    from benchmark_engine.lifecycle import run_lifecycle
    from benchmark_domains.command import CommandDomain
    spec = load_recipe("retrieval_index")
    req = next(iter(spec["required_params"]))          # a param the recipe mandates
    cfg = BenchmarkConfig(domain="command", hypothesis="h",
                          treatment_variable=TreatmentVariable(name="n", baseline_value=1, value=1))
    cfg.set_param("n", 1, source="treatment")          # deliberately omit `req`
    lr = run_lifecycle(cfg, CommandDomain(spec, workroot=str(tmp_path / "c")),
                       workdir=str(tmp_path / "r"), baseline=cfg)
    assert lr.result.status.value == "ABORTED_PREFLIGHT"
    assert req  # the recipe does mandate at least one param
