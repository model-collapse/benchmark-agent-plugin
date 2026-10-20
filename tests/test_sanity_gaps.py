"""Sanity-check acceptance scenarios closing the gaps identified in review:

  F5 — a fully-declared ML recipe actually RUNS end-to-end on CPU (not just gated).
  I1 — an experiment whose trials abort is BOUNDED by the loop guard (not a full grid).
  I2 — the GPU-hour budget is a stop-launching guard: overshoot <= one trial.
  A5 — the plugin manifests are well-formed and the one skill + hook are wired.

(E3/E4 — real-GPU VRAM behavior — require hardware; the unit suite covers the
 logic with an injected fake probe.)
"""

import json
from pathlib import Path

from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_engine.tuning import Tuner, TuneDim, LoopBudget, HaltReason
from benchmark_engine.domain import MeasureOutcome, PrepArtifact
from benchmark_domains.command import CommandDomain
from benchmark_domains.recipes.loader import load_recipe

from conftest import make_base_config

ROOT = Path(__file__).resolve().parents[1]


class _Probe:
    def used_mb(self, device_ids):
        return 0


# ----------------------------- F5 -----------------------------------------

def test_f5_llm_finetune_recipe_runs_end_to_end_on_cpu(tmp_path):
    spec = load_recipe("llm_finetune_eval")
    cfg = BenchmarkConfig(domain="command", hypothesis="tune lr",
                          treatment_variable=TreatmentVariable(name="train.lr", baseline_value=1e-4, value=1e-4))
    declared = {"base_model": "m", "dataset": "d", "tokenizer": "t", "precision": "bf16",
                "seed": 0, "eval_suite": "lm-eval-harness", "eval_suite_version": "0.4.3",
                "train.lr": 1e-4}
    for p, v in declared.items():
        cfg.set_param(p, v, source="treatment" if p == "train.lr" else "controlled")
    baseline = BenchmarkConfig.from_dict(cfg.to_dict())

    lr = run_lifecycle(cfg, CommandDomain(spec, workroot=str(tmp_path / "c"), gpu_probe=_Probe()),
                       workdir=str(tmp_path / "r"), baseline=baseline)
    assert lr.result.status.value == "COMPLETED"
    assert lr.result.metrics["mmlu_acc"] == 0.63
    assert lr.result.metrics["gsm8k_acc"] == 0.41
    assert lr.result.metrics["gpu_hours"] > 0        # train(4 gpus) + eval(1 gpu) accounted


# ----------------------------- I1 -----------------------------------------

class _AbortAfterBaseline:
    """Baseline treatment value completes; every other value's measure crashes."""
    name = "fake"

    def __init__(self, baseline_val):
        self.b = baseline_val

    def required_params(self): return {}
    def apply_config(self, cfg, ctx): return {}
    def verify_config(self, cfg, ctx): return {}
    def prep(self, cfg, ctx): return PrepArtifact(kind="fake")

    def measure(self, cfg, prep, ctx):
        if float(cfg.get("fake.heap_factor")) != self.b:
            raise RuntimeError("boom")        # non-baseline trial → run FAILED
        return MeasureOutcome(metrics={"p50_ms": 10.0, "gpu_hours": 1.0},
                              functional_validation={"passed": True, "recall@10": 0.99})


def test_i1_aborting_sweep_is_bounded_not_full_grid(tmp_path):
    base = make_base_config(0.7)
    t = Tuner(base, _AbortAfterBaseline(0.7), str(tmp_path), primary_metric="p50_ms", minimize=True,
              quality_metric="recall@10", quality_floor=0.0)
    big_grid = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]   # 8 values
    res = t.grid(TuneDim("fake.heap_factor", values=big_grid))
    assert res.halt.reason in (HaltReason.NONCOMPARABLE_STREAK, HaltReason.BUDGET_ABORTS)
    assert res.halt.needs_human is True                   # a broken experiment ASKs
    assert res.halt.total_trials < len(big_grid)          # bounded — did NOT run the whole grid


# ----------------------------- I2 -----------------------------------------

class _GpuDomain:
    name = "fake"

    def required_params(self): return {}
    def apply_config(self, cfg, ctx): return {}
    def verify_config(self, cfg, ctx): return {}
    def prep(self, cfg, ctx): return PrepArtifact(kind="fake")

    def measure(self, cfg, prep, ctx):
        return MeasureOutcome(metrics={"p50_ms": 10.0, "gpu_hours": 1.0},
                              functional_validation={"passed": True, "recall@10": 0.99})


def test_i2_gpu_budget_stop_launching_overshoot_bounded(tmp_path):
    base = make_base_config(0.7)
    t = Tuner(base, _GpuDomain(), str(tmp_path), primary_metric="p50_ms", minimize=True,
              quality_metric="recall@10", quality_floor=0.0,
              budget=LoopBudget(max_gpu_hours=1.5, hard_cap=64))
    big_grid = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]   # 8 values @ 1.0 gpu-hour each
    res = t.grid(TuneDim("fake.heap_factor", values=big_grid))
    assert res.halt.reason is HaltReason.BUDGET_GPU_HOURS
    # baseline (1.0) + exactly one candidate (2.0 >= 1.5) → stop; overshoot <= one trial
    assert res.halt.total_trials == 2
    assert res.halt.total_trials < len(big_grid)


# ----------------------------- A5 -----------------------------------------

def test_a5_plugin_manifests_valid_and_wired():
    # all plugin JSON parses
    mkt = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    json.loads((ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text())
    hooks = json.loads((ROOT / "plugin" / ".claude-plugin" / "hooks" / "hooks.json").read_text())
    assert mkt["plugins"][0]["source"] == "./plugin"

    # exactly one skill, with usable frontmatter
    skills_dir = ROOT / "plugin" / "skills"
    assert {p.name for p in skills_dir.iterdir() if p.is_dir()} == {"benchmark"}
    fm = (skills_dir / "benchmark" / "SKILL.md").read_text()
    assert "name: benchmark" in fm
    assert "user-invocable: true" in fm
    assert "argument-hint:" in fm

    # the awareness hook referenced by hooks.json exists and is the only one
    refs = {h["command"].split("hooks/")[-1].split('"')[0]
            for ev in hooks["hooks"].values() for grp in ev for h in grp["hooks"]}
    assert refs == {"benchmark_awareness.py"}
    assert (ROOT / "plugin" / "hooks" / "benchmark_awareness.py").exists()
    assert {p.name for p in (ROOT / "plugin" / "hooks").glob("*.py")} == {"benchmark_awareness.py"}
