# Unified Benchmark Harness — Phase 2 (ML Scenarios) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add GPU/accelerator guardrails + accounting, ML-aware two-gate fairness (seed-distribution replication, accelerator fingerprint, eval-suite comparability, provenance manifests), and embedding/LLM recipes — so the one `/benchmark` skill benchmarks embedding and LLM training/eval, not just retrieval.

**Architecture:** A new `benchmark_engine/resources.py` holds GPU budget + device pinning + GPU-hours/$ accounting behind an **injectable VRAM probe** (so every GPU path is testable with a fake — no hardware needed). CommandDomain stages gain a `resources:` block (pin devices, VRAM-OOM fail-loud, record gpu_hours/cost). The Tuner's `LoopBudget` gains GPU-hour/$ limits and a seed-replication mode. The fingerprint gains accelerator identity; a small eval-suite comparability check refuses cross-suite comparisons. Recipes ship for embedding/LLM with provenance-hard-gating manifests.

**Tech Stack:** Python 3.11, pure-stdlib engine; GPU probing via optional `pynvml` → `nvidia-smi` → null fallback. `pytest`. Env: `source /home/ubuntu/miniconda3/etc/profile.d/conda.sh && conda activate clusterbench`.

**Spec:** `docs/superpowers/specs/2026-10-19-unified-benchmark-harness-design.md` (§8 GPU, §9 ML fairness, §14 Phase 2).

## Global Constraints

- **License:** Apache-2.0; new `.py` files start `# SPDX-License-Identifier: Apache-2.0`.
- **Dependency rule (strict one-way):** `skill → benchmark_domains → benchmark_ops → benchmark_engine`.
- **Metric-agnostic core:** no hard-coded science-metric names in generic paths (gpu_hours/cost/vram are *resource* metrics, allowed).
- **No hardware in tests:** every GPU path is exercised through an injected fake VRAM probe; `pytest -m "not happy"` must pass on a CPU-only box.
- **TDD:** test watched to fail first; run `pytest -m "not happy"` before marking a task complete.
- **Commit attribution:** end every commit message with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Phase 1 baseline fast suite = **162 passed**; each task's Step 5 gives the expected running total.

## Review Focus

- **Null probe on a CPU box:** a stage declaring `resources.gpus` on a machine with no GPU/pynvml/nvidia-smi must behave deterministically (record gpu_hours by wall-time×gpus, skip VRAM polling) — never crash importing pynvml. (Test in Task 1/3.)
- **VRAM-OOM fail-loud:** a stage whose probe reports usage over `vram_mb` must abort the run (not record a comparable result). (Test in Task 3.)
- **GPU-hour/$ budget halts the sweep:** a tuning search must stop with the right halt reason once accumulated gpu_hours/cost crosses the budget — not run the whole grid. (Test in Task 4.)
- **Seed-distribution comparability:** improvement must be judged over the seed distribution; a single lucky seed must not be selected as a real win. (Test in Task 5.)
- **Eval-suite comparability refusal:** comparing two runs evaluated on different eval suites/versions must be refused, not silently compared. (Test in Task 6.)
- **Provenance manifest hard-gate:** an LLM/embedding config missing `seed`/`precision`/`base_model`/`dataset`/`eval_suite` must be blocked. (Test in Task 7.)

---

### Task 1: `benchmark_engine/resources.py` — GPU spec, pinning, accounting, probe interface

**Files:**
- Create: `benchmark_engine/resources.py`
- Create: `tests/test_resources.py`

**Interfaces:**
- Produces:
  - `@dataclass GpuSpec(gpus: int = 0, vram_mb: int | None = None, est_gpu_hours: float | None = None)`; `GpuSpec.from_dict(d: dict | None) -> GpuSpec`.
  - `pin_env(base_env: dict, device_ids: list[int]) -> dict` — returns a copy with `CUDA_VISIBLE_DEVICES` set to the comma-joined ids (empty list ⇒ unchanged).
  - `gpu_hours(gpus: int, seconds: float) -> float` = `gpus * seconds / 3600`.
  - `cost(gpu_hours: float, rate_per_gpu_hour: float) -> float`.
  - `class VramProbe(Protocol): def used_mb(self, device_ids: list[int]) -> int` (max across the given devices; `0` if unknown).
  - `NullProbe` (always 0), `NvmlProbe`, `SmiProbe`, and `default_probe() -> VramProbe` which tries pynvml, then `nvidia-smi`, else `NullProbe` — importing pynvml lazily and never raising.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_resources.py
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
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: benchmark_engine.resources`).
  Run: `python -m pytest tests/test_resources.py -q`

- [ ] **Step 3: Implement `resources.py`** per the Interfaces block. `default_probe` tries `import pynvml` (lazy, in a try/except), else checks `shutil.which("nvidia-smi")`, else `NullProbe`. `NvmlProbe.used_mb` queries per-device used memory and returns the max; `SmiProbe.used_mb` parses `nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i <ids>`.

- [ ] **Step 4: Run — expect PASS** (4 tests).

- [ ] **Step 5: Full suite** → `166 passed`. Run: `python -m pytest -m "not happy" -q`

- [ ] **Step 6: Commit**
```bash
git add benchmark_engine/resources.py tests/test_resources.py
git commit -m "feat(engine): GPU resource spec, device pinning, GPU-hours/cost accounting, VRAM probe

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: VRAM-OOM guard

**Files:**
- Modify: `benchmark_engine/resources.py` (add `VramExceeded`, `vram_check`)
- Create: `tests/test_vram_guard.py`

**Interfaces:**
- Consumes: `VramProbe`, `GpuSpec`.
- Produces:
  - `class VramExceeded(RuntimeError)`.
  - `vram_check(probe: VramProbe, device_ids: list[int], vram_mb: int | None) -> None` — raises `VramExceeded` if `vram_mb` is set and `probe.used_mb(device_ids) > vram_mb`; a `None` budget or `0`/unknown probe reading is a no-op.

- [ ] **Step 1: Failing tests**
```python
# tests/test_vram_guard.py
import pytest
from benchmark_engine.resources import vram_check, VramExceeded

class _Fake:
    def __init__(self, mb): self._mb = mb
    def used_mb(self, device_ids): return self._mb

def test_vram_check_raises_over_budget():
    with pytest.raises(VramExceeded):
        vram_check(_Fake(80000), [0], 72000)

def test_vram_check_ok_within_budget():
    vram_check(_Fake(40000), [0], 72000)   # no raise

def test_vram_check_noop_without_budget():
    vram_check(_Fake(999999), [0], None)   # no raise
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError: vram_check`).

- [ ] **Step 3: Implement** `VramExceeded` + `vram_check`.

- [ ] **Step 4: Run — expect PASS** (3 tests).

- [ ] **Step 5: Full suite** → `169 passed`.

- [ ] **Step 6: Commit**
```bash
git add benchmark_engine/resources.py tests/test_vram_guard.py
git commit -m "feat(engine): VRAM-OOM guard (fail loud when a stage exceeds its VRAM budget)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wire GPU resources into CommandDomain stage execution

**Files:**
- Modify: `benchmark_ops/command.py` (`run_command_stage` gains `gpu`, `probe`, `rate_per_gpu_hour`)
- Modify: `benchmark_domains/command.py` (pass each stage's `resources` + a probe; add gpu_hours/cost to metrics)
- Create: `tests/test_command_gpu.py`

**Interfaces:**
- Consumes: `GpuSpec`, `pin_env`, `vram_check`, `gpu_hours`, `cost`, `default_probe`, `VramProbe`.
- Produces:
  - `run_command_stage(..., gpu: GpuSpec | None = None, probe=None, rate_per_gpu_hour: float = 0.0)` — when `gpu` and `gpu.gpus > 0`: pins `CUDA_VISIBLE_DEVICES` to `range(gpu.gpus)` in the subprocess env, times the command, after it runs calls `vram_check(probe, devices, gpu.vram_mb)` (fail-loud) and injects `gpu_hours` and (if `rate>0`) `cost` into the returned `metrics`.
  - `CommandDomain(spec, name="command", workroot=None, gpu_probe: VramProbe | None = None)` — threads `gpu_probe` (default `default_probe()`) and the config's `cost.rate_per_gpu_hour` param (default 0) into each stage's `run_command_stage`. A stage's `resources` dict → `GpuSpec`.

Note: VRAM is polled once after the stage returns (not a live monitor) in this phase — enough to catch an over-budget peak a stage reports via the probe; a live monitor is a future refinement. Document this.

- [ ] **Step 1: Failing tests** (fake probe injected; no GPU needed)
```python
# tests/test_command_gpu.py
import pytest
from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_domains.command import CommandDomain

class _Probe:
    def __init__(self, mb): self._mb = mb
    def used_mb(self, device_ids): return self._mb

def _cfg(n=1):
    cfg = BenchmarkConfig(domain="command", hypothesis="h",
                          treatment_variable=TreatmentVariable(name="n", baseline_value=n, value=n))
    cfg.set_param("n", n, source="treatment")
    return cfg

def _spec():
    return {"stages": [
        {"name": "train", "cmd": "sleep 0.2 > /dev/null; echo done > {ckpt}", "produces": ["ckpt"],
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
```

- [ ] **Step 2: Run — expect FAIL** (`run_command_stage` has no `gpu`/`probe`; metrics lack gpu_hours).

- [ ] **Step 3: Implement.** `run_command_stage`: build env via `pin_env` for the pinned devices, pass `env=` to `subprocess.run`, time it, `vram_check` after, inject `gpu_hours`/`cost`. `CommandDomain._to_step`: parse `stage["resources"]` → `GpuSpec`, assign `device_ids=list(range(gpu.gpus))`, pass `gpu`, `self._probe`, `rate`. For a `prep` stage the gpu_hours/cost ride in that stage's result; sum resource metrics across all stages in `prep()`/`measure()` into the outcome (prep-side resource metrics surface via `PrepArtifact.meta["resource_metrics"]`, merged by `measure()` into `MeasureOutcome.metrics`).

- [ ] **Step 4: Run — expect PASS** (3 tests).

- [ ] **Step 5: Full suite** → `172 passed`.

- [ ] **Step 6: Commit**
```bash
git add benchmark_ops/command.py benchmark_domains/command.py tests/test_command_gpu.py
git commit -m "feat(domains): GPU pinning + VRAM guard + GPU-hours/cost accounting for command stages

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: LoopBudget GPU-hour / $ budgets

**Files:**
- Modify: `benchmark_engine/tuning.py` (`LoopBudget` fields, `HaltReason`, accumulation, `_check_halt`)
- Create: `tests/test_gpu_budget_halt.py`

**Interfaces:**
- Consumes: trial results carrying `gpu_hours`/`cost` in `metrics`.
- Produces: `LoopBudget.max_gpu_hours: float | None = None`, `LoopBudget.max_cost: float | None = None`; `HaltReason.BUDGET_GPU_HOURS`, `HaltReason.BUDGET_COST` (auto-halt, not ASK); the Tuner accumulates `self._gpu_hours`/`self._cost` from each evaluated trial's result metrics and halts when a budget is crossed.

- [ ] **Step 1: Failing test** (FakeDomain that emits gpu_hours per run)
```python
# tests/test_gpu_budget_halt.py
from benchmark_engine.tuning import Tuner, TuneDim, LoopBudget, HaltReason
from conftest import make_base_config
from benchmark_engine.domain import MeasureOutcome, PrepArtifact

class GpuDomain:
    name = "fake"
    def required_params(self): return {}
    def apply_config(self, cfg, ctx): return {}
    def verify_config(self, cfg, ctx): return {}
    def prep(self, cfg, ctx): return PrepArtifact(kind="fake")
    def measure(self, cfg, prep, ctx):
        return MeasureOutcome(metrics={"p50_ms": 10.0, "gpu_hours": 1.0},
                              functional_validation={"passed": True, "recall@10": 0.99})

def test_halts_on_gpu_hour_budget(tmp_path):
    base = make_base_config(0.7)
    t = Tuner(base, GpuDomain(), str(tmp_path), primary_metric="p50_ms", minimize=True,
              quality_metric="recall@10", quality_floor=0.0,
              budget=LoopBudget(max_gpu_hours=2.5, hard_cap=64))
    res = t.grid(TuneDim("fake.heap_factor", values=[0.7, 0.8, 0.9, 1.0, 1.1, 1.2]))
    assert res.halt.reason is HaltReason.BUDGET_GPU_HOURS
    assert res.halt.total_trials <= 3            # ~2.5 gpu-hours ⇒ stop after 3 trials
```

- [ ] **Step 2: Run — expect FAIL** (`LoopBudget` has no `max_gpu_hours`).

- [ ] **Step 3: Implement.** Add the fields + enum members; in `_reset_guard` init `self._gpu_hours = self._cost = 0.0`; in `_eval` after building the trial, add the completed runs' `gpu_hours`/`cost`; in `_check_halt` add the two budget checks (before NO_PROGRESS). Add messages in `_halt_message`.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Full suite** → `173 passed`.

- [ ] **Step 6: Commit**
```bash
git add benchmark_engine/tuning.py tests/test_gpu_budget_halt.py
git commit -m "feat(tuning): GPU-hour and cost loop budgets with auto-halt reasons

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Seed-distribution replication in the Tuner

**Files:**
- Modify: `benchmark_engine/tuning.py` (`Tuner` gains `seed_param` + `seeds`)
- Create: `tests/test_seed_replication.py`

**Interfaces:**
- Produces: `Tuner(..., seed_param: str | None = None, seeds: list | None = None)`. When set, `_eval` runs the config once per seed (setting `coords[seed_param]=s` and `repro_nonce` per seed) and aggregates the per-seed primaries into the existing `MeasureStats` distribution used by `is_real_improvement` — so a win must beat noise across seeds, not a single lucky seed. Without `seed_param`, behavior is unchanged (replicates path).

- [ ] **Step 1: Failing test** — a domain whose primary depends on the seed; a config that is only "better" on one seed must NOT be selected.
```python
# tests/test_seed_replication.py
from benchmark_engine.tuning import Tuner, TuneDim
from benchmark_engine.domain import MeasureOutcome, PrepArtifact
from conftest import make_base_config

class SeedNoisyDomain:
    name = "fake"
    def required_params(self): return {}
    def apply_config(self, cfg, ctx): return {}
    def verify_config(self, cfg, ctx): return {}
    def prep(self, cfg, ctx): return PrepArtifact(kind="fake")
    def measure(self, cfg, prep, ctx):
        seed = int(cfg.get("fake.seed", 0))
        hf = float(cfg.get("fake.heap_factor"))
        # p50 is pure seed noise (±) with no real dependence on heap_factor
        p50 = 10.0 + (3.0 if seed % 2 else -3.0)
        return MeasureOutcome(metrics={"p50_ms": p50},
                              functional_validation={"passed": True, "recall@10": 0.99})

def test_single_seed_luck_not_selected(tmp_path):
    base = make_base_config(0.7)
    base.set_param("fake.seed", 0, source="controlled")
    t = Tuner(base, SeedNoisyDomain(), str(tmp_path), primary_metric="p50_ms", minimize=True,
              quality_metric="recall@10", quality_floor=0.0,
              seed_param="fake.seed", seeds=[1, 2, 3, 4])
    res = t.grid(TuneDim("fake.heap_factor", values=[0.7, 0.9]))
    # p50 has no real heap_factor signal across seeds ⇒ no comparable improvement selected
    assert res.recommendation is None or res.improvement is None or res.improvement <= 1.0
```

- [ ] **Step 2: Run — expect FAIL** (`Tuner` has no `seed_param`).

- [ ] **Step 3: Implement.** In `_eval`, when `self.seed_param`: build the replicate set by varying `seed_param` over `self.seeds` (each a `_run_once` with that seed + distinct nonce); feed the per-seed primaries into the same `MeasureStats`/`is_real_improvement` path. Guard `comparable` with the across-seed CV as today.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Full suite** → `174 passed`.

- [ ] **Step 6: Commit**
```bash
git add benchmark_engine/tuning.py tests/test_seed_replication.py
git commit -m "feat(tuning): seed-distribution replication so wins must beat across-seed noise

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Accelerator fingerprint + eval-suite comparability

**Files:**
- Modify: `benchmark_engine/fingerprint.py` (accelerator in fingerprint; `assert_comparable_eval`)
- Create: `tests/test_ml_fairness.py`

**Interfaces:**
- Produces:
  - `env_fingerprint()` gains an `"accelerator"` key (GPU name + driver/CUDA via the probe, best-effort; `"absent"` on a CPU box) and `"accelerator"` is added to `COMPARABILITY_KEYS` so a cross-accelerator baseline reuse is refused.
  - `assert_comparable_eval(baseline: dict, current: dict) -> None` — raises `BaselineFingerprintMismatch` if `eval_suite` or `eval_suite_version` differ (each a dict of those two keys).

- [ ] **Step 1: Failing tests**
```python
# tests/test_ml_fairness.py
import pytest
from benchmark_engine.fingerprint import (
    env_fingerprint, assert_comparable_fingerprint, assert_comparable_eval,
    BaselineFingerprintMismatch, COMPARABILITY_KEYS)

def test_accelerator_in_fingerprint():
    fp = env_fingerprint()
    assert "accelerator" in fp and "accelerator" in COMPARABILITY_KEYS

def test_cross_accelerator_refused():
    a = env_fingerprint(); b = dict(a); b["accelerator"] = "H100"; a = dict(a); a["accelerator"] = "A100"
    with pytest.raises(BaselineFingerprintMismatch):
        assert_comparable_fingerprint(a, b)

def test_eval_suite_mismatch_refused():
    with pytest.raises(BaselineFingerprintMismatch):
        assert_comparable_eval({"eval_suite": "mmlu", "eval_suite_version": "1.0"},
                               {"eval_suite": "mmlu", "eval_suite_version": "2.0"})

def test_eval_suite_match_ok():
    assert_comparable_eval({"eval_suite": "mmlu", "eval_suite_version": "1.0"},
                           {"eval_suite": "mmlu", "eval_suite_version": "1.0"})
```

- [ ] **Step 2: Run — expect FAIL** (`assert_comparable_eval` missing; no `accelerator`).

- [ ] **Step 3: Implement.** Add an `_accelerator()` helper (lazy pynvml → `nvidia-smi --query-gpu=name,driver_version` → `"absent"`); add it to `env_fingerprint` and `COMPARABILITY_KEYS`. Add `assert_comparable_eval`.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Full suite** → `178 passed`. (Note: adding `accelerator` to `env_fingerprint` — confirm no existing fingerprint test pins the exact key set; update it if so, noting the change in the ledger.)

- [ ] **Step 6: Commit**
```bash
git add benchmark_engine/fingerprint.py tests/test_ml_fairness.py
git commit -m "feat(fairness): accelerator fingerprint + eval-suite comparability refusal

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Embedding/LLM recipes + provenance manifests

**Files:**
- Create: `benchmark_domains/recipes/embedding_train_eval.yaml`, `llm_finetune_eval.yaml`, `llm_eval_only.yaml`
- Create: `tests/test_ml_recipes.py`

**Interfaces:**
- Consumes: `load_recipe`, `CommandDomain`, the manifest hard-gate.
- Produces: three recipes, each a stages spec (`train`/`eval` with `resources` GPU blocks; `llm_eval_only` is a single measure stage) + a `required_params` manifest mandating the ML provenance params: `base_model`, `dataset`, `tokenizer`, `precision`, `seed`, `eval_suite`.

- [ ] **Step 1: Failing tests**
```python
# tests/test_ml_recipes.py
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
    cfg.set_param("lr", 1e-4, source="treatment")   # omit provenance params
    lr = run_lifecycle(cfg, CommandDomain(spec, workroot=str(tmp_path / name)),
                       workdir=str(tmp_path / (name + "_r")), baseline=cfg)
    assert lr.result.status.value == "ABORTED_PREFLIGHT"
```

- [ ] **Step 2: Run — expect FAIL** (recipes missing).

- [ ] **Step 3: Implement** the three YAML recipes with illustrative CPU-safe placeholder commands (so a fully-declared config could run on CI without GPUs — the `resources` blocks are declared but a Null probe makes them CPU-safe), each with the provenance `required_params` manifest.

- [ ] **Step 4: Run — expect PASS** (3 params).

- [ ] **Step 5: Full suite** → `181 passed`.

- [ ] **Step 6: Commit**
```bash
git add benchmark_domains/recipes tests/test_ml_recipes.py
git commit -m "feat(domains): embedding/LLM recipes with GPU stages + provenance hard-gate manifests

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Docs

**Files:**
- Modify: `docs/benchmark/README.md`, `docs/benchmark/DOMAIN_API.md`, root `README.md`

**Interfaces:** none (docs). The existing `tests/test_no_stale_refs.py` guard still applies.

- [ ] **Step 1: Update docs** — document the `resources:` block (gpus/vram_mb/est_gpu_hours), GPU-hours/$ accounting + loop budgets, seed-distribution replication, accelerator fingerprint + eval-suite comparability, and the three ML recipes. Add a `llm-finetune-eval` YAML example to README.

- [ ] **Step 2: Run the stale-ref guard** → `python -m pytest tests/test_no_stale_refs.py -q` → PASS.

- [ ] **Step 3: Full suite** → `181 passed`.

- [ ] **Step 4: Commit**
```bash
git add README.md docs/benchmark
git commit -m "docs: GPU resources, GPU/$ budgets, seed replication, ML fairness + recipes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the implementer
- Test counts in each Step 5 are the expected running totals from the Phase-1 baseline of 162; reconcile and ledger if a pre-existing fingerprint test needs updating for the new `accelerator` key (Task 6).
- No GPU hardware is assumed anywhere: every GPU path is exercised via an injected fake `VramProbe`; on CI the `default_probe()` resolves to `NullProbe`.
- VRAM guarding is a post-stage poll in this phase (documented); a live monitor during the stage subprocess is a future refinement.
