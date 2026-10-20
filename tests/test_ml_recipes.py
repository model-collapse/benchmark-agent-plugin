import pytest
from benchmark_domains.recipes.loader import load_recipe
from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_domains.command import CommandDomain


@pytest.mark.parametrize("name", ["embedding_train_eval", "llm_finetune_eval", "llm_eval_only"])
def test_recipe_loads_and_gates_provenance(name, tmp_path):
    spec = load_recipe(name)
    req = spec["required_params"]
    assert {"base_model", "dataset", "precision", "seed", "eval_suite"} <= set(req)
    cfg = BenchmarkConfig(domain="command", hypothesis="h",
                          treatment_variable=TreatmentVariable(name="lr", baseline_value=1e-4, value=1e-4))
    cfg.set_param("lr", 1e-4, source="treatment")   # omit the provenance params
    lr = run_lifecycle(cfg, CommandDomain(spec, workroot=str(tmp_path / name)),
                       workdir=str(tmp_path / (name + "_r")), baseline=cfg)
    assert lr.result.status.value == "ABORTED_PREFLIGHT"
