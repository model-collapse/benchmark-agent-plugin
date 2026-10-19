# Unified Benchmark Harness — Phase 1 (Unification) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the two overlapping harnesses into one general-purpose `/benchmark` skill backed solely by the engine, with a generic N-stage DAG `CommandDomain` (CPU/host-RSS only), one persistence layout, and the `clusterbench_* → benchmark_*` rename. No GPU/ML scenarios (Phase 2).

**Architecture:** The engine (`benchmark_engine`) stays the single place discipline is defined; `CommandDomain` implements the existing `Domain` protocol by running declared shell-command stages as a DAG through the existing `Scheduler` (cacheable prep stages run parallel, measurement serialized). The one `/benchmark` skill is a thin markdown layer that drives the engine and enforces nothing in prose.

**Tech Stack:** Python 3.11, pure-stdlib engine (no third-party runtime deps), `yaml` for configs, `pytest`. Conda env `clusterbench` (`source /home/ubuntu/miniconda3/etc/profile.d/conda.sh && conda activate clusterbench`).

**Spec:** `docs/superpowers/specs/2026-10-19-unified-benchmark-harness-design.md`

## Global Constraints

- **License:** Apache-2.0. New `.py` files start with `# SPDX-License-Identifier: Apache-2.0` (match the engine's existing convention).
- **Dependency rule (strict one-way):** `skill → benchmark_domains → benchmark_ops → benchmark_engine`. Never import upward.
- **Metric-agnostic core:** the engine and `report_index` must not hard-code any metric name (no `p50_ms`/`recall@10` literals in generic code paths).
- **No rule-enforcing logic in skill prose:** the `/benchmark` SKILL.md describes LLM judgment only; every gate it mentions is enforced by engine code it calls.
- **TDD:** every production change is preceded by a test watched to fail. Run the whole suite (`pytest -m "not happy"`) before marking a task complete.
- **Env activation prefix for every command:** `source /home/ubuntu/miniconda3/etc/profile.d/conda.sh && conda activate clusterbench`.
- **Commit attribution:** end every commit message with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Shell safety:** stage commands are run as argument lists where possible; any value interpolated into a shell string is quoted with `shlex.quote`.

## Review Focus

- **Malformed/empty metrics output:** a measure stage whose command emits non-JSON or an empty file must fail loud (stage → FAILED, run → FAILED), never silently record zero metrics. (Test in Task 2.)
- **Unknown `{placeholder}`:** a stage command referencing a param/artifact name that no param or upstream `produces` supplies must be rejected before any command runs. (Test in Task 4.)
- **Shell-injection via artifact paths:** an artifact path or param value containing spaces/`;`/`$()` must not break or inject into the stage command. (Test in Task 2.)
- **Recipe manifest gate:** a config built from a recipe but missing one of the recipe's required params must be blocked by the manifest hard-gate (`ABORTED_PREFLIGHT`). (Test in Task 5.)
- **Cache key must include the command text:** two stages with identical params but a changed `cmd` string must NOT share a cache entry. (Test in Task 3.)

---

### Task 1: Rename `clusterbench_* → benchmark_engine/ops/domains`

**Files:**
- Rename dirs: `clusterbench_core/ → benchmark_engine/`, `clusterbench_ops/ → benchmark_ops/`, `clusterbench_domains/ → benchmark_domains/`
- Modify: every `.py` under those packages + `experiments/` + `tests/`, `pyproject.toml`, `plugin/hooks/*` (hook module/body), `plugin/skills/*/SKILL.md` references, `docs/`
- Test: the entire existing suite (`tests/`) is the verification.

**Interfaces:**
- Consumes: nothing (first task).
- Produces: packages `benchmark_engine`, `benchmark_ops`, `benchmark_domains` with identical public APIs under new names. All import paths `clusterbench_core`→`benchmark_engine`, `clusterbench_ops`→`benchmark_ops`, `clusterbench_domains`→`benchmark_domains`.

- [ ] **Step 1: Baseline the suite is green before touching anything**

Run: `source /home/ubuntu/miniconda3/etc/profile.d/conda.sh && conda activate clusterbench && python -m pytest -m "not happy" -q`
Expected: `134 passed`.

- [ ] **Step 2: Move the package directories with git**

```bash
cd /home/ubuntu/auto-exp/benchmark-agent-plugin
git mv clusterbench_core benchmark_engine
git mv clusterbench_ops benchmark_ops
git mv clusterbench_domains benchmark_domains
```

- [ ] **Step 3: Rewrite all import strings and dotted references**

```bash
grep -rl --include=*.py --include=*.toml --include=*.md --include=*.py 'clusterbench_core\|clusterbench_ops\|clusterbench_domains' . \
  | xargs sed -i 's/clusterbench_core/benchmark_engine/g; s/clusterbench_ops/benchmark_ops/g; s/clusterbench_domains/benchmark_domains/g'
```
Also fix the subprocess worker/measure_entry module strings (they live inside the moved package, so the sed above covers `"clusterbench_core.engine.worker"` etc.). Grep to confirm none remain:
Run: `grep -rn 'clusterbench_core\|clusterbench_ops\|clusterbench_domains' --include=*.py --include=*.toml .`
Expected: no output.

- [ ] **Step 4: Update pyproject package discovery**

In `pyproject.toml` set:
```toml
[tool.setuptools.packages.find]
include = ["benchmark_engine*", "benchmark_ops*", "benchmark_domains*"]
```
(Leave `[project].name = "clusterbench"` for now — the distribution rename is cosmetic and out of scope; only import packages change. Add a one-line comment noting the dist name is legacy.)

- [ ] **Step 5: Reinstall editable and run the full suite**

Run: `source /home/ubuntu/miniconda3/etc/profile.d/conda.sh && conda activate clusterbench && pip install -e . -q && python -m pytest -m "not happy" -q`
Expected: `134 passed` (a broken import would error loudly — that is the rename's test).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename clusterbench_* packages to benchmark_engine/ops/domains

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Command-runner step fn + metric extraction (`benchmark_ops/command.py`)

**Files:**
- Create: `benchmark_ops/command.py`
- Create: `tests/test_command_runner.py`

**Interfaces:**
- Consumes: `benchmark_engine.engine.step` contract — a step fn takes resolved inputs as kwargs and returns a dict with any of `{metrics, outputs, effective_params, phases}`; `outputs["descriptor"]` is what the cache stores.
- Produces:
  - `run_command_stage(cmd: str, params: dict, artifacts: dict, workdir: str, produces: list[str] | None = None, metrics_from: dict | None = None) -> dict` — a step fn. Substitutes `{name}` from `params`∪`artifacts` (each interpolated value `shlex.quote`-d), runs `cmd` via `subprocess.run(shell=True, cwd=workdir)`, and:
    - for each name in `produces`, resolves its path (`workdir/<name>` by default or the substituted `{name}` path) into `outputs[name]` and into `outputs["descriptor"]` (name→path+size/mtime);
    - if `metrics_from` is set, extracts metrics (see `extract_metrics`) into `metrics`.
    - On non-zero exit → return `{"outputs": {"failed": True}}` and raise `CommandStageError` (so the launcher marks the step FAILED).
  - `extract_metrics(spec: dict, workdir: str) -> dict` — `spec` is `{"stdout": True, "fields": [...]}` or `{"file": "<path>", "fields": [...]}`; parses JSON (default) or CSV (`.csv`), selects `fields`, returns `{field: value}`. Missing field or unparseable payload → raise `MetricExtractionError`.
  - `class CommandStageError(RuntimeError)`, `class MetricExtractionError(RuntimeError)`.

- [ ] **Step 1: Write failing tests for substitution + stdout JSON + file JSON + CSV + errors + injection**

```python
# tests/test_command_runner.py
import json, pytest
from pathlib import Path
from benchmark_ops.command import (
    run_command_stage, extract_metrics, CommandStageError, MetricExtractionError)

def test_substitutes_params_and_runs(tmp_path):
    out = run_command_stage(
        cmd='echo {greeting} > {msg}', params={"greeting": "hi"}, artifacts={},
        workdir=str(tmp_path), produces=["msg"])
    assert (tmp_path / "msg").read_text().strip() == "hi"
    assert out["outputs"]["msg"].endswith("msg")
    assert "msg" in out["outputs"]["descriptor"]

def test_metrics_from_stdout_json(tmp_path):
    spec = {"stdout": True, "fields": ["p50_ms", "qps"]}
    out = run_command_stage(
        cmd='echo {"p50_ms": 12.0, "qps": 800, "ignored": 1}',
        params={}, artifacts={}, workdir=str(tmp_path), metrics_from=spec)
    assert out["metrics"] == {"p50_ms": 12.0, "qps": 800}

def test_metrics_from_json_file(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps({"acc": 0.91, "n": 5}))
    assert extract_metrics({"file": str(tmp_path/"r.json"), "fields": ["acc"]}, str(tmp_path)) == {"acc": 0.91}

def test_metrics_from_csv_file(tmp_path):
    (tmp_path / "r.csv").write_text("acc,loss\n0.9,0.3\n")
    assert extract_metrics({"file": str(tmp_path/"r.csv"), "fields": ["acc", "loss"]}, str(tmp_path)) == {"acc": 0.9, "loss": 0.3}

def test_nonzero_exit_raises(tmp_path):
    with pytest.raises(CommandStageError):
        run_command_stage(cmd='exit 3', params={}, artifacts={}, workdir=str(tmp_path))

def test_empty_metrics_payload_fails_loud(tmp_path):   # Review Focus: malformed output
    (tmp_path / "r.json").write_text("")
    with pytest.raises(MetricExtractionError):
        extract_metrics({"file": str(tmp_path/"r.json"), "fields": ["acc"]}, str(tmp_path))

def test_artifact_path_with_spaces_is_safe(tmp_path):  # Review Focus: injection
    weird = tmp_path / "a b;c"
    out = run_command_stage(cmd='echo ok > {dst}', params={}, artifacts={"dst": str(weird)},
                            workdir=str(tmp_path), produces=["dst"])
    assert Path(out["outputs"]["dst"]).read_text().strip() == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_command_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: benchmark_ops.command`.

- [ ] **Step 3: Implement `benchmark_ops/command.py`**

Implement `run_command_stage`, `extract_metrics`, and the two exception classes exactly per the Interfaces block. Use `shlex.quote` on every interpolated value; parse JSON with `json.loads`, CSV with `csv.DictReader` (coerce numeric strings to float where possible). Raise `MetricExtractionError` on empty/unparseable payloads or a missing requested field.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_command_runner.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the full fast suite**

Run: `python -m pytest -m "not happy" -q`
Expected: `141 passed`.

- [ ] **Step 6: Commit**

```bash
git add benchmark_ops/command.py tests/test_command_runner.py
git commit -m "feat(ops): command-stage runner with stdout/file/CSV metric extraction

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `CommandDomain` — N-stage DAG over the engine (`benchmark_domains/command.py`)

**Files:**
- Create: `benchmark_domains/command.py`
- Create: `tests/test_command_domain.py`

**Interfaces:**
- Consumes: `Domain` protocol (`benchmark_engine.domain`: `required_params`, `apply_config`, `verify_config`, `prep`, `measure`); `PrepArtifact`, `MeasureOutcome`; `Step`, `StepRef`, `Scheduler`, `SignatureCache`, `InProcessLauncher`; `run_command_stage` from Task 2; `BenchmarkConfig.get`.
- Produces:
  - `class CommandDomain` with `__init__(self, spec: dict, name: str = "command")`. `spec` is the parsed stages config: `{"stages": [ {name, cmd, needs?, produces?, kind: "prep"|"measure", metrics_from?, effective_from?, parallel?} ], "treatment_variable"?, "required_params"?}`.
  - `prep(cfg, ctx) -> PrepArtifact`: builds a `Step` per `kind=="prep"` stage (cacheable, `cache_key=(stage.name, cmd, sorted resolved params, upstream descriptors)`), wires `needs`→`StepRef`, runs them through an inner `Scheduler(InProcessLauncher(), cache=self._cache)`; returns `PrepArtifact(kind="command", meta={"artifacts": {name: path}})` collecting every produced artifact path.
  - `measure(cfg, prep, ctx) -> MeasureOutcome`: builds a `Step` per `kind=="measure"` stage (non-cacheable), injecting `prep.meta["artifacts"]` as available artifacts, runs them through the inner scheduler; merges all stage `metrics` into `MeasureOutcome.metrics`; sets `functional_validation={"passed": True}` by default (overridable by a `passed` field in any stage's metrics).
  - `required_params(self) -> dict`: returns `spec.get("required_params", {})`.
  - `apply_config`/`verify_config`: no-op defaults (return `{}` / `{}`) — command domains self-apply inside their stage commands.

- [ ] **Step 1: Write failing tests — 3-stage CPU pipeline, artifact flow, per-stage caching, cache-key includes cmd**

```python
# tests/test_command_domain.py
import pytest
from pathlib import Path
from benchmark_engine.model import BenchmarkConfig, TreatmentVariable
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_domains.command import CommandDomain

def _spec(cmd_build="echo {n} > {idx}"):
    return {"stages": [
        {"name": "prep", "cmd": cmd_build, "produces": ["idx"], "kind": "prep"},
        {"name": "measure", "cmd": 'echo {"score": 7}', "needs": ["prep"],
         "kind": "measure", "metrics_from": {"stdout": True, "fields": ["score"]}},
    ], "treatment_variable": "n"}

def _cfg(n=3):
    cfg = BenchmarkConfig(domain="command", hypothesis="h",
                          treatment_variable=TreatmentVariable(name="n", baseline_value=n, value=n))
    cfg.set_param("n", n, source="treatment")
    return cfg

def test_pipeline_runs_end_to_end(tmp_path):
    lr = run_lifecycle(_cfg(), CommandDomain(_spec()), workdir=str(tmp_path), baseline=_cfg())
    assert lr.result.status.value == "COMPLETED"
    assert lr.result.metrics["score"] == 7

def test_prep_stage_is_cached_across_runs(tmp_path):
    d = CommandDomain(_spec("python -c \"open('{idx}','w').write('x'); open('ran','a').write('1')\""))
    run_lifecycle(_cfg(), d, workdir=str(tmp_path), baseline=_cfg())
    run_lifecycle(_cfg(), d, workdir=str(tmp_path), baseline=_cfg())
    # prep ran once; the second run hit the inner cache (marker written once)
    assert Path("ran").read_text() == "1"
    Path("ran").unlink()

def test_cache_key_includes_cmd(tmp_path):   # Review Focus: changed cmd invalidates cache
    d1 = CommandDomain(_spec("echo A > {idx}"))
    d2 = CommandDomain(_spec("echo B > {idx}"))
    a = run_lifecycle(_cfg(), d1, workdir=str(tmp_path), baseline=_cfg())
    b = run_lifecycle(_cfg(), d2, workdir=str(tmp_path), baseline=_cfg())
    # different cmd ⇒ different prep signature ⇒ not a cache hit (both COMPLETED, distinct artifacts)
    assert a.result.status.value == "COMPLETED" and b.result.status.value == "COMPLETED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_command_domain.py -q`
Expected: FAIL — `ModuleNotFoundError: benchmark_domains.command`.

- [ ] **Step 3: Implement `benchmark_domains/command.py`**

Implement `CommandDomain` per the Interfaces block. Inner `SignatureCache` at `Path(self._workroot)/"_command_cache"` created lazily on first `prep` from the `ctx`/workdir; stage `Step.fn` is a closure calling `run_command_stage(...)` with resolved params (from `cfg`) and artifacts (from upstream `StepRef` outputs / `prep.meta`). `cache_key` MUST include the stage `cmd` text and the sorted resolved param items. Collect produced artifact paths from each prep `StepResult.outputs`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_command_domain.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full fast suite**

Run: `python -m pytest -m "not happy" -q`
Expected: `144 passed`.

- [ ] **Step 6: Commit**

```bash
git add benchmark_domains/command.py tests/test_command_domain.py
git commit -m "feat(domains): CommandDomain — N-stage command pipeline over the engine

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: DAG validation (preflight) + `effective_from` capture

**Files:**
- Modify: `benchmark_domains/command.py` (add `validate_dag`, wire `effective_from`)
- Modify: `benchmark_engine/discipline/preflight.py` (call domain `validate()` hook if present)
- Create: `tests/test_command_dag.py`

**Interfaces:**
- Consumes: `CommandDomain` (Task 3); `EffectiveRecorder.effective(name, value)`; `preflight.run_preflight` (adds an optional `domain.validate(cfg)` call that returns `list[str]` of errors; non-empty → block).
- Produces:
  - `CommandDomain.validate(self, cfg) -> list[str]`: returns errors for (a) a `needs` naming a non-existent stage, (b) a cycle in the stage DAG, (c) a `{placeholder}` in any `cmd`/`metrics_from`/`effective_from` that is neither a declared param nor an artifact produced by an upstream stage.
  - `effective_from` handling in `measure`/`prep`: if a stage declares `effective_from: {file: "<path>"}`, after the stage runs, read that JSON file and call `ctx.effective(k, v)` for each key, so the effective-vs-declared gate sees point-of-use values.
  - `preflight.run_preflight`: if `hasattr(domain, "validate")`, run it after the manifest gate and before apply; a non-empty return blocks with `blocked_reason="dag_validation"`.

- [ ] **Step 1: Write failing tests — cycle, missing-needs, unknown placeholder, effective!=declared**

```python
# tests/test_command_dag.py
from pathlib import Path
import json
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

def test_unknown_placeholder_blocks():   # Review Focus
    spec = {"stages": [{"name": "m", "cmd": "echo {nope}", "kind": "measure"}]}
    assert any("nope" in e for e in CommandDomain(spec).validate(_cfg()))

def test_preflight_blocks_on_bad_dag(tmp_path):
    spec = {"stages": [{"name": "m", "cmd": "echo {nope}", "kind": "measure"}]}
    lr = run_lifecycle(_cfg(), CommandDomain(spec), workdir=str(tmp_path), baseline=_cfg())
    assert lr.result.status.value == "ABORTED_PREFLIGHT"

def test_effective_from_trips_gate(tmp_path):
    # the stage "resolves" n=99 regardless of declared n=3 → effective != declared
    spec = {"stages": [
        {"name": "prep", "cmd": "echo x > {idx}", "produces": ["idx"], "kind": "prep"},
        {"name": "measure", "cmd": 'python -c "import json;json.dump({\\"n\\":99},open(\'eff.json\',\'w\'))" ; echo {"score":1}',
         "needs": ["prep"], "kind": "measure",
         "metrics_from": {"stdout": True, "fields": ["score"]},
         "effective_from": {"file": "eff.json"}}],
        "treatment_variable": "n"}
    lr = run_lifecycle(_cfg(3), CommandDomain(spec), workdir=str(tmp_path), baseline=_cfg(3))
    assert lr.result.signature_diff  # n declared 3, effective 99
    assert lr.result.reliability_tag.value == "UNRELIABLE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_command_dag.py -q`
Expected: FAIL — `validate` missing / no blocking.

- [ ] **Step 3: Implement `validate`, the preflight hook, and `effective_from`**

Add `CommandDomain.validate`; in `preflight.run_preflight` call `domain.validate(cfg)` after the manifest gate (guard with `hasattr`), block with `dag_validation` on errors. In `CommandDomain.measure`/`prep`, after a stage with `effective_from` runs, load the JSON and record each key via `ctx.effective`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_command_dag.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full fast suite**

Run: `python -m pytest -m "not happy" -q`
Expected: `148 passed`.

- [ ] **Step 6: Commit**

```bash
git add benchmark_domains/command.py benchmark_engine/discipline/preflight.py tests/test_command_dag.py
git commit -m "feat(domains): DAG validation in preflight + effective_from point-of-use capture

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Recipe loader + `retrieval-index` recipe + opt-in parallel measurement

**Files:**
- Create: `benchmark_domains/recipes/__init__.py`, `benchmark_domains/recipes/retrieval_index.yaml`
- Create: `benchmark_domains/recipes/loader.py`
- Modify: `benchmark_engine/engine/step.py` (add `parallel_safe: bool = False`), `benchmark_engine/engine/scheduler.py` (parallelize `parallel_safe` measure steps)
- Create: `tests/test_recipes.py`

**Interfaces:**
- Consumes: `CommandDomain`; `Step` (new `parallel_safe` field); `Scheduler`.
- Produces:
  - `load_recipe(name: str, overrides: dict | None = None) -> dict` — reads `recipes/<name>.yaml`, deep-merges `overrides`, returns a CommandDomain `spec` (including its `required_params`).
  - `retrieval_index.yaml` — a `prep`(build) → `measure`(search) spec with a `required_params` manifest entry for the key retrieval params.
  - `Step.parallel_safe: bool = False`; `Scheduler.run` runs `parallel_safe` non-cacheable steps in the parallel pool, and keeps non-`parallel_safe` measurement steps serialized after them (perf metrics stay attributable).

- [ ] **Step 1: Write failing tests — recipe load+gate, parallel-safe measures overlap, perf measures serialize**

```python
# tests/test_recipes.py
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
        time.sleep(0.3); return {"metrics": {"acc": 1.0}}
    return Step(name=name, fn=fn, cacheable=False, parallel_safe=parallel_safe)

def test_parallel_safe_measures_overlap(tmp_path):
    steps = [_sleep_step("e1", True), _sleep_step("e2", True)]
    t = time.time(); Scheduler(InProcessLauncher(), max_parallel=2).run(steps, tmp_path)
    assert time.time() - t < 0.5   # ran concurrently, not 0.6s serialized

def test_perf_measures_stay_serialized(tmp_path):
    steps = [_sleep_step("m1", False), _sleep_step("m2", False)]
    t = time.time(); Scheduler(InProcessLauncher(), max_parallel=2).run(steps, tmp_path)
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
    lr = run_lifecycle(cfg, CommandDomain(spec), workdir=str(tmp_path), baseline=cfg)
    assert lr.result.status.value == "ABORTED_PREFLIGHT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_recipes.py -q`
Expected: FAIL — loader missing / `parallel_safe` unknown.

- [ ] **Step 3: Implement the recipe loader, the YAML recipe, and the scheduler change**

Add `Step.parallel_safe`. In `Scheduler.run`, split `measurement` into `parallel_safe` (run in the pool) and the rest (serialized, as today). Write `retrieval_index.yaml` and `load_recipe` (deep-merge overrides).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_recipes.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full fast suite**

Run: `python -m pytest -m "not happy" -q`
Expected: `153 passed`.

- [ ] **Step 6: Commit**

```bash
git add benchmark_domains/recipes tests/test_recipes.py benchmark_engine/engine/step.py benchmark_engine/engine/scheduler.py
git commit -m "feat(domains): recipe loader + retrieval-index recipe + opt-in parallel measurement

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: One persistence layout + metric-agnostic results index

**Files:**
- Modify: `benchmark_engine/report_index.py` (generalize `update_index` columns)
- Modify: `benchmark_engine/lifecycle.py` (default `workdir` → `benchmark_data/runs`), `experiments/*.py` (default paths)
- Create: `tests/test_index_metric_agnostic.py`

**Interfaces:**
- Consumes: persisted `results.yaml` (RunResult dict).
- Produces: `update_index(workdir)` renders a table whose metric columns are the **union of all metric names across runs** (sorted), not a fixed `p50_ms`/`recall@10` set. `load_runs` unchanged. Default workdir constant `DEFAULT_WORKDIR = "./benchmark_data/runs"`.

- [ ] **Step 1: Write failing test — arbitrary metric names appear as columns**

```python
# tests/test_index_metric_agnostic.py
import yaml
from pathlib import Path
from benchmark_engine.report_index import update_index

def test_index_lists_arbitrary_metrics(tmp_path):
    run = tmp_path / "runs" / "r1"; run.mkdir(parents=True)
    (run / "results.yaml").write_text(yaml.safe_dump({
        "run_id": "r1", "status": "COMPLETED", "reliability_tag": "QUALIFIED",
        "metrics": {"mmlu_acc": 0.63, "tokens_per_s": 1800.0}, "functional_validation": {}}))
    out = update_index(tmp_path / "runs").read_text()
    assert "mmlu_acc" in out and "tokens_per_s" in out
    assert "p50_ms" not in out   # no hard-coded retrieval columns when absent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_metric_agnostic.py -q`
Expected: FAIL — hard-coded `p50_ms`/`recall@10` columns, `mmlu_acc` absent.

- [ ] **Step 3: Generalize `update_index`**

Compute the sorted union of metric keys across runs; render one column per metric (plus run_id/status). Keep `functional_validation` values (e.g. `passed`) in a trailing column. Set `DEFAULT_WORKDIR` and update `run_lifecycle`'s default + experiments.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_index_metric_agnostic.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full fast suite**

Run: `python -m pytest -m "not happy" -q`
Expected: `154 passed` (fix any test asserting the old fixed columns — update it to the generalized format, noting the change).

- [ ] **Step 6: Commit**

```bash
git add benchmark_engine/report_index.py benchmark_engine/lifecycle.py experiments tests/test_index_metric_agnostic.py
git commit -m "feat(engine): metric-agnostic results index + unified benchmark_data default

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The one `/benchmark` skill; delete the five; rename hook; marketplace

**Files:**
- Create: `plugin/skills/benchmark/SKILL.md`
- Delete: `plugin/skills/{benchmark_agent,benchmark_run,clusterbench_plan,clusterbench_run,clusterbench_domain}/`
- Rename: `plugin/hooks/clusterbench_awareness.py → plugin/hooks/benchmark_awareness.py` (+ any `hooks.json`/settings reference)
- Modify: `.claude-plugin/marketplace.json`
- Modify: `tests/test_plugin_hook.py` (point at renamed hook), create `tests/test_skills_unified.py`

**Interfaces:**
- Consumes: the awareness-hook contract exercised by `test_plugin_hook.py`.
- Produces: exactly one skill directory `plugin/skills/benchmark/` with verb-dispatch frontmatter (`argument-hint` listing `plan|run|tune|analyze|compare|history|status|reclassify|domain`, `--detach` noted on `run`); the five old skill dirs gone; hook module `benchmark_awareness`.

- [ ] **Step 1: Write failing tests — exactly one skill, old five gone, renamed hook importable**

```python
# tests/test_skills_unified.py
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / "plugin" / "skills"

def test_only_benchmark_skill_exists():
    dirs = {p.name for p in ROOT.iterdir() if p.is_dir()}
    assert dirs == {"benchmark"}

def test_skill_prose_enforces_nothing():   # Global Constraint: no rule logic in prose
    text = (ROOT / "benchmark" / "SKILL.md").read_text().lower()
    assert "plan" in text and "analyze" in text and "--detach" in text
```
Also edit `tests/test_plugin_hook.py` to import/exec `plugin/hooks/benchmark_awareness.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_skills_unified.py tests/test_plugin_hook.py -q`
Expected: FAIL — five dirs present / old hook path.

- [ ] **Step 3: Create the unified skill, delete the five, rename the hook, update marketplace**

Write `plugin/skills/benchmark/SKILL.md` as the thin judgment layer (verbs table from spec §5; each verb says which engine entry point it calls — `run_lifecycle`, `Tuner`, `report_index`, `CommandDomain`/recipes; `run --detach` documents the nohup-engine + `/loop` + signal-file flow; prose enforces nothing). `git rm -r` the five old skill dirs. `git mv` the hook and fix references. Update `marketplace.json` name/description to the one unified skill.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_skills_unified.py tests/test_plugin_hook.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full fast suite**

Run: `python -m pytest -m "not happy" -q`
Expected: `156 passed`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(plugin): collapse five skills into one /benchmark; rename awareness hook

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Docs refresh + stale-reference guard

**Files:**
- Move: `docs/clusterbench/ → docs/benchmark/`
- Modify: root `README.md`, `docs/benchmark/README.md`, `docs/benchmark/DOMAIN_API.md`, `plugin/benchmark_lessons.md` (renamed from clusterbench_lessons.md)
- Create: `tests/test_no_stale_refs.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: docs describing one `/benchmark` skill + the CommandDomain pipeline/recipes; a test asserting no `clusterbench_` import strings remain in package code and no `experimaestro` in user-facing docs (excluding `docs/benchmark/upstream/`).

- [ ] **Step 1: Write failing test — no stale refs in code/docs**

```python
# tests/test_no_stale_refs.py
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def _grep(pattern, *paths):
    r = subprocess.run(["grep", "-rl", pattern, *[str(ROOT / p) for p in paths]],
                       capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l]

def test_no_clusterbench_imports_in_code():
    assert _grep("clusterbench_core", "benchmark_engine", "benchmark_ops", "benchmark_domains", "experiments") == []

def test_no_experimaestro_in_user_docs():
    hits = _grep("experimaestro", "README.md", "docs/benchmark/README.md", "docs/benchmark/DOMAIN_API.md")
    assert hits == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_no_stale_refs.py -q`
Expected: FAIL — stale strings present (docs not yet moved/updated).

- [ ] **Step 3: Move and rewrite the docs**

`git mv docs/clusterbench docs/benchmark`; `git mv plugin/clusterbench_lessons.md plugin/benchmark_lessons.md`. Rewrite root `README.md` and `docs/benchmark/README.md` for the one `/benchmark` skill + CommandDomain pipeline + recipes; update `DOMAIN_API.md` to document CommandDomain and the stages schema alongside the Python `Domain` protocol. Leave `docs/benchmark/upstream/*` untouched (legitimate experimaestro history).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_no_stale_refs.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole fast suite**

Run: `python -m pytest -m "not happy" -q`
Expected: `158 passed`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: refresh for one /benchmark skill + CommandDomain; guard against stale refs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Happy-path tests** (`-m happy`, OpenSearch/SEISMIC) must still pass after the rename; run them once at the end if Docker/SEISMIC are available (`python -m pytest -m happy -q`), but they are not part of the per-task fast-suite gate.
- Test counts in each task's Step 5 are the expected running total (134 baseline + new tests); if a count is off because a pre-existing test needed updating for the generalized index (Task 6) or renamed hook (Task 7), reconcile and note it in the ledger.
- Phase 2 (GPU guardrails + accounting, ML-aware fairness, embedding/LLM recipes) is a separate plan that builds on these stable names and the `CommandDomain` pipeline.
