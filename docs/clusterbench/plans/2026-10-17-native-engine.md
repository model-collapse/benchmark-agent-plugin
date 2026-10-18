# ClusterBench Native Engine + Two-Gate Fairness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace experimaestro with a clean-room Apache-2.0 execution engine merged into `clusterbench_core`, add the two-gate experiment-fairness system + loop guard, fix the §14 shipped-code defects, and relicense the project — then contribute to the benchmark plugin.

**Architecture:** Approach C — reuse our dataclass configs + `signature()`; add a `Step`/`StepRef`/`SignatureCache`/`Launcher`/`Scheduler` layer (no typed-Param metaclass). Fairness is two gates (parameter-identity + measurement-comparability) feeding one `comparable` verdict a loop guard keys off. Caller-facing APIs (`run_lifecycle`, `Tuner`, experiments, domains) keep their signatures.

**Tech Stack:** Python 3.11, dataclasses, hashlib/json, multiprocessing/subprocess, psutil, pyyaml, opensearch-py, pyseismic-lsr. No GPL deps.

**Spec:** `docs/superpowers/specs/2026-10-17-native-engine-design.md` (read it; this plan argues from it).

## Global Constraints

- Python ≥ 3.10; conda env `clusterbench` (`source /home/ubuntu/miniconda3/etc/profile.d/conda.sh && conda activate clusterbench`).
- **No GPL dependency** anywhere in the base install; `import experimaestro` must fail in the base env after Phase 0.
- License: **Apache-2.0** (SPDX `Apache-2.0`); every new source file gets `# SPDX-License-Identifier: Apache-2.0`.
- Strict one-way deps: `plugin → clusterbench_domains → clusterbench_ops → clusterbench_core(.engine)`. The engine imports nothing from upper layers.
- Caller-facing APIs unchanged: `run_lifecycle(cfg, domain, ...) -> LifecycleResult`, `Tuner(...).grid/refine/coordinate(...) -> TuningResult`, experiment `run(...)`.
- Thresholds are the team defaults, all in `LoopBudget`: R=7, MDE=3%, K=3, M=5, CV≤15%, 30 trials / 7200 s / 5 aborts.
- Every task: TDD cycle — (1) write failing test, (2) run it, confirm it FAILS for the stated reason, (3) minimal implementation, (4) run it, confirm PASS, (5) `git add` + `git commit`. Run tests with the env active. The cycle is identical for every task; each task below gives its task-specific test, implementation shape, and commit message.

## Review Focus

Inputs/failure modes the spec implies that no single task's happy-path tests exercise — each is pinned to a test in the owning task:
- **Effective capture by re-reading cfg instead of point-of-use** (red-team rank-1): the gate silently passes a clamped run. → Task 3.2 clamp-injection test asserts the recorded value is the *clamped* one.
- **In-process RSS compared across trials** (monotonic high-water mark): later trials inherit earlier peaks. → Task 4.3 asserts in-process RSS is tagged non-comparable and subprocess RSS is attributable.
- **A run that reports `passed=True` while dropping work** (partial ingest / client retry): bypasses the loop guard's UNRELIABLE exclusion. → Task 4.1 partial-ingest test asserts `passed=False` → UNRELIABLE.
- **Sub-noise "speedup" chosen as the winner** (no replication/variance): tuner optimizes noise. → Task 5.1 asserts a delta below the noise band is rejected and NO_PROGRESS fires.
- **Non-comparable run becomes the recommendation** (safety): → Task 6.2 asserts `_better` can never select a non-comparable trial and `recommendation` is `None` when none are comparable.

---

## Phase 0 — Relicense & de-GPL

### Task 0.1: Apache-2.0 relicense + drop experimaestro

**Files:**
- Replace: `LICENSE` (GPL-3.0 → Apache-2.0 full text)
- Modify: `pyproject.toml` (`license = {text = "Apache-2.0"}`; remove `experimaestro` from `dependencies`; drop the `experimaestro` import in any extras)
- Delete: `clusterbench_core/xpm.py`, `tests/test_xpm.py`
- Modify: `plugin/.claude-plugin/plugin.json` (`"license": "Apache-2.0"`), `README.md` license line
- Test: `tests/test_license.py`

**Interfaces:**
- Produces: an Apache-2.0 base install with no experimaestro.

- [ ] **Test** (`tests/test_license.py`):
```python
import importlib, pathlib
def test_experimaestro_not_a_dependency():
    pp = pathlib.Path("pyproject.toml").read_text()
    assert "experimaestro" not in pp
def test_license_is_apache():
    assert "Apache License" in pathlib.Path("LICENSE").read_text()
def test_xpm_module_removed():
    import pytest
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("clusterbench_core.xpm")
```
- [ ] Run → FAIL (xpm still present, GPL license). 
- [ ] Implement: write Apache-2.0 `LICENSE`; edit `pyproject.toml`; `git rm clusterbench_core/xpm.py tests/test_xpm.py`; update plugin.json/README; add SPDX header to a shared `clusterbench_core/engine/__init__.py` stub.
- [ ] Run → PASS.
- [ ] Commit: `chore: relicense Apache-2.0, drop experimaestro + xpm`

---

## Phase 1 — Engine core

### Task 1.1: `engine/signature.py` — content-hash

**Files:** Create `clusterbench_core/engine/signature.py`; Test `tests/engine/test_signature.py`
**Interfaces:** Produces `signature(payload: dict) -> str` (sha256 of canonical JSON, 16 hex chars); `field_diff(a: dict, b: dict) -> dict[str, tuple]` (per-key declared/effective where differing).

- [ ] **Test:**
```python
from clusterbench_core.engine.signature import signature, field_diff
def test_signature_stable_and_order_independent():
    assert signature({"a":1,"b":2}) == signature({"b":2,"a":1})
def test_signature_sensitive():
    assert signature({"a":1}) != signature({"a":2})
def test_field_diff_names_changed_keys():
    assert field_diff({"x":1,"y":2}, {"x":1,"y":9}) == {"y": (2, 9)}
```
- [ ] Implement: `json.dumps(payload, sort_keys=True, default=str)` → `hashlib.sha256(...).hexdigest()[:16]`; `field_diff` compares stringified values.
- [ ] Commit: `feat(engine): content-hash signature + field_diff`

### Task 1.2: `engine/cache.py` — on-disk content-addressed cache + descriptor verify

**Files:** Create `clusterbench_core/engine/cache.py`; Test `tests/engine/test_cache.py`
**Interfaces:** Produces `SignatureCache(root)` with `.path_for(step, sig) -> Path`, `.has(step, sig) -> bool`, `.store(step, sig, descriptor: dict, producer: Callable[[Path], None]) -> Path`, `.load(step, sig, expect_descriptor: dict) -> Path` (raises `StaleArtifact` if the stored descriptor ≠ expected).

- [ ] **Test:**
```python
from clusterbench_core.engine.cache import SignatureCache, StaleArtifact
import pytest
def test_store_then_hit(tmp_path):
    c = SignatureCache(tmp_path)
    assert not c.has("prep","sig1")
    c.store("prep","sig1",{"docs":100}, lambda p:(p/"idx").write_text("x"))
    assert c.has("prep","sig1")
    assert (c.load("prep","sig1",{"docs":100})/"idx").read_text()=="x"
def test_descriptor_mismatch_is_stale(tmp_path):
    c = SignatureCache(tmp_path)
    c.store("prep","sig1",{"docs":100}, lambda p:(p/"idx").write_text("x"))
    with pytest.raises(StaleArtifact):
        c.load("prep","sig1",{"docs":999})
```
- [ ] Implement: layout `root/<step>/<sig>/`; write a `descriptor.json` next to the artifact; `load` compares it to `expect_descriptor`.
- [ ] Commit: `feat(engine): on-disk signature cache with descriptor verify`

### Task 1.3: `engine/step.py` — Step/StepRef/StepResult

**Files:** Create `clusterbench_core/engine/step.py`; Test `tests/engine/test_step.py`
**Interfaces:** Produces dataclasses `StepRef(step_name)`, `StepResult(status, outputs, metrics, phases, effective_params, provenance)`, and `Step(name, fn: str, inputs: dict, cache_key: tuple|None, cacheable: bool, depends_on: list[str])`; helper `edges(steps) -> dict[str,set[str]]` deriving dependencies from `depends_on` + any `StepRef` in `inputs`.

- [ ] **Test:**
```python
from clusterbench_core.engine.step import Step, StepRef, edges
def test_edges_from_ref_and_explicit():
    prep = Step("prep", fn="m:build", inputs={}, cache_key=("c",), cacheable=True, depends_on=[])
    meas = Step("measure", fn="m:run", inputs={"idx": StepRef("prep")}, cache_key=None, cacheable=False, depends_on=[])
    assert edges([prep, meas])["measure"] == {"prep"}
```
- [ ] Implement dataclasses + `edges`.
- [ ] Commit: `feat(engine): Step/StepRef/StepResult + edge derivation`

### Task 1.4: `engine/launcher.py` + `engine/worker.py` — InProcess/LocalProcess + OOM guard

**Files:** Create `clusterbench_core/engine/launcher.py`, `clusterbench_core/engine/worker.py`; Test `tests/engine/test_launcher.py`
**Interfaces:** Produces `Launcher` protocol `run(step, resolved_inputs, workdir) -> StepResult`; `InProcessLauncher`; `LocalProcessLauncher(budget: ResourceBudget|None)` which serializes `(fn, inputs, workdir)` to `worker.py`, runs it as a subprocess with its `sys.path`/`PYTHONPATH` set explicitly (L5), and monitors the child with `OOMGuard`/`monitor_process` (reuse `clusterbench_core.guard`).

- [ ] **Test (parity + guard):**
```python
from clusterbench_core.engine.launcher import InProcessLauncher, LocalProcessLauncher
from clusterbench_core.engine.step import Step
# toy fn defined in an importable test helper module (tests/engine/_toy.py: def add(a,b): return {"metrics":{"s":a+b}})
def _step(): return Step("t", fn="tests.engine._toy:add", inputs={"a":2,"b":3}, cache_key=None, cacheable=False, depends_on=[])
def test_inprocess_and_subprocess_parity(tmp_path):
    a = InProcessLauncher().run(_step(), {"a":2,"b":3}, tmp_path/"a")
    b = LocalProcessLauncher().run(_step(), {"a":2,"b":3}, tmp_path/"b")
    assert a.metrics["s"] == b.metrics["s"] == 5
```
Guard test: reuse the pattern from `tests/test_coverage_extra2.py::test_guard_kills_real_overbudget_process` but driven through `LocalProcessLauncher` with a tiny budget; expect the step `StepResult.status == ABORTED_GUARDRAIL`.
- [ ] Implement worker entrypoint (`python -m clusterbench_core.engine.worker <spec.json>`), set `PYTHONPATH` to repo root, capture stdout/err + metrics JSON; implement both launchers.
- [ ] Commit: `feat(engine): InProcess/LocalProcess launchers + OOM-guarded subprocess`

### Task 1.5: `engine/scheduler.py` — DAG + bounded parallelism + serialized measurement

**Files:** Create `clusterbench_core/engine/scheduler.py`; Test `tests/engine/test_scheduler.py`
**Interfaces:** Produces `Scheduler(launcher, cache, max_parallel=…)` with `run(steps) -> dict[str, StepResult]`: topo-sort on `edges`, run independent cacheable steps concurrently (consult cache first), but **measurement steps (`cacheable=False`) run serialized** (never concurrently with any other step). Propagates a failed dependency as a skipped/FAILED downstream.

- [ ] **Tests:** topo order respected (prep before measure); two independent cacheable preps run concurrently (timing or a shared counter); a non-cacheable measure never overlaps another step (instrument a lock-contention flag); a failing prep marks its dependent FAILED not run.
- [ ] Implement with a thread dispatcher around launchers + a measurement mutex.
- [ ] Commit: `feat(engine): scheduler with parallel prep + serialized measurement`

---

## Phase 2 — Lifecycle/tuner on the engine; domain persistence

### Task 2.1: `run_lifecycle` as a prep→measure step graph

**Files:** Modify `clusterbench_core/lifecycle.py`; Test extend `tests/test_lifecycle.py`
**Interfaces:** Consumes Phase-1 engine. Produces unchanged `run_lifecycle(cfg, domain, ctx=None, workdir=…, baseline=None, apply=True, launcher=None) -> LifecycleResult`; internally builds `prep` (cacheable, key = domain build-key) + `measure` (non-cacheable) steps and runs them via `Scheduler`. Budget/manifest/preflight stay as pre-step gates.

- [ ] **Test:** existing `test_full_lifecycle_completes_and_persists`, `test_forced_oom_aborts_guardrail_and_persists`, `test_preflight_verify_mismatch_aborts_and_does_not_measure` must still pass; add `test_lifecycle_runs_on_local_process_launcher`.
- [ ] Implement; keep `LifecycleResult`/`RunResult` shape.
- [ ] Commit: `refactor(lifecycle): run prep→measure on the native engine`

### Task 2.2: Domain prep-artifact persistence (save/load)

**Files:** Modify `clusterbench_core/domain.py` (protocol), `clusterbench_domains/{demo,seismic,opensearch}/domain.py`; Test `tests/test_domain_persistence.py`
**Interfaces:** Produces `Domain.save_prep(artifact, path)` and `load_prep(path) -> PrepArtifact`. SEISMIC → `SeismicIndex.save/load`; OpenSearch → write `{endpoint, index_name, descriptor}`; demo → JSON. `prep` stores via `SignatureCache.store`; `measure` loads via `.load`.

- [ ] **Test (cross-session reuse):** build with a SEISMIC domain into a `SignatureCache` rooted at `tmp_path`; create a *fresh* domain instance (new process-like state) and assert `prep` is a cache hit (no rebuild — assert via a build-count sentinel / mtime) and `measure` loads the saved index and returns the same recall.
- [ ] Implement save/load per domain.
- [ ] Commit: `feat(domains): persistable prep artifacts for cross-session cache`

---

## Phase 3 — Gate 1: parameter identity

### Task 3.1: Freeze `BenchmarkConfig`

**Files:** Modify `clusterbench_core/model.py`; Test extend `tests/test_model.py`
**Interfaces:** `BenchmarkConfig` becomes effectively immutable after `freeze()`: `freeze()` returns a frozen view (tuples/`MappingProxyType` for `params`), stores `self._frozen_signature`; `assert_unchanged()` re-checks. Mutating a frozen config raises `FrozenConfigError`.

- [ ] **Test:**
```python
def test_frozen_config_rejects_mutation():
    cfg = make_cfg(); fz = cfg.freeze()
    import pytest
    with pytest.raises(Exception):
        fz.set_param("seismic.n_postings", 1)
    fz.assert_unchanged()  # no raise
```
- [ ] Implement freeze + guard in `set_param`/`__setattr__` when frozen.
- [ ] Commit: `feat(model): frozen config + signature re-assertion`

### Task 3.2: Effective-param capture AT POINT OF USE (keystone)

**Files:** Create `clusterbench_core/engine/effective.py` (the `EffectiveRecorder`); Modify `clusterbench_domains/{seismic,opensearch}/domain.py` to route search params through it; Test `tests/test_effective_capture.py`
**Interfaces:** Produces `EffectiveRecorder` with `effective(name, value) -> value` (records then returns the value) and `.params -> dict`. `ctx` passed to `measure` carries a recorder. Domains MUST call `qc = ctx.effective("seismic.query_cut", int(cfg.get("seismic.query_cut")))` **at the search call site**, then pass `qc` to `idx.search`.

- [ ] **Test (clamp injection — Review Focus #1):**
```python
def test_point_of_use_capture_records_clamped_value(tmp_path):
    # a domain subclass whose measure clamps query_cut to 2 right before search
    dom = ClampingSeismicDomain(clamp_query_cut=2)
    lr = run_lifecycle(make_seismic_cfg(query_cut=10), dom, workdir=tmp_path, baseline=make_seismic_cfg(query_cut=10))
    assert lr.result.effective_params["seismic.query_cut"] == 2   # NOT the declared 10
```
- [ ] Implement recorder; wire domains to record at the call site; populate `RunResult.effective_params`.
- [ ] Commit: `feat(fairness): point-of-use effective-param capture`

### Task 3.3: Effective-vs-declared gate in `classify`

**Files:** Modify `clusterbench_core/discipline/reliability.py` (classify consumes effective), `clusterbench_core/lifecycle.py` (compute effective_signature, set on RunResult), `clusterbench_core/model.py` (RunResult gains `effective_signature`, `signature_diff`); Test extend `tests/test_discipline.py`
**Interfaces:** Produces `RunResult.effective_signature`, `RunResult.signature_diff: dict`. `classify` input gains `effective_matches_declared: bool`; when False → UNRELIABLE with rationale naming the diffed fields.

- [ ] **Test:**
```python
def test_effective_mismatch_forces_unreliable():
    tag, why = classify(ClassifyInput(reproduced=True, functional_validation_passed=True,
                                      effective_matches_declared=False))
    assert tag is ReliabilityTag.UNRELIABLE and "effective" in why.lower()
```
Plus a lifecycle test: the clamp run from 3.2 → `reliability_tag == UNRELIABLE` and `signature_diff["seismic.query_cut"] == (10, 2)` and the report mentions it.
- [ ] Implement signature compute + diff + classify branch; report includes the diff.
- [ ] Commit: `feat(fairness): effective-vs-declared gate + structured diff`

### Task 3.4: Fail-loud invariant + provenance

**Files:** Modify `clusterbench_core/lifecycle.py` (provenance capture), `clusterbench_core/discipline/reliability.py` (forbidden assertion); Test `tests/test_provenance.py`
**Interfaces:** Produces `RunResult.provenance` = `{declared_signature, effective_signature, code_version (git SHA of domains+ops), seeds, start, end, host, launcher, resource_limits}`; a `fairness_assert(result)` that raises if effective≠declared on a controlled var yet tag ∈ {RELIABLE, QUALIFIED}.

- [ ] **Test:** provenance fields present + non-empty on a normal run; `fairness_assert` raises on a hand-built RELIABLE+mismatch result.
- [ ] Implement (git SHA via `subprocess`, host via `socket`, seeds from cfg).
- [ ] Commit: `feat(fairness): provenance capture + fail-loud assertion`

---

## Phase 4 — §14 current-code fixes

### Task 4.1: Data-integrity-derived `passed`

**Files:** Modify `clusterbench_domains/{seismic,opensearch}/domain.py`; Test `tests/test_data_integrity.py`
**Interfaces:** `functional_validation.passed = (recall >= floor) and (doc_count == expected) and (all hits == k) and (no bulk partial failure) and (no client retry)`. OpenSearch: `helpers.bulk(..., raise_on_error=True, stats_only=False)` + assert `_count == n_docs`.

- [ ] **Test (Review Focus #3):** a domain variant that drops 10% of docs on ingest → `passed == False` → lifecycle tags UNRELIABLE.
- [ ] Implement; replace hardcoded `True`.
- [ ] Commit: `fix(domains): compute functional_validation.passed from data integrity`

### Task 4.2: Fixed-k recall assertion

**Files:** Modify both domains + `clusterbench_core/lifecycle.py`; Test extend `tests/test_data_integrity.py`
**Interfaces:** assert `cfg.get(".k") == 10` for a `recall@10` comparison (or metric is renamed `recall@{k}` and k added to the comparability key). Default: enforce k==10.
- [ ] **Test:** k=5 config → classify/lifecycle raises or tags EXPLORATORY with reason "recall@10 requires k==10".
- [ ] Implement assertion.
- [ ] Commit: `fix(domains): pin k==10 for recall@10 comparisons`

### Task 4.3: Subprocess RSS; in-process RSS non-comparable

**Files:** Modify `clusterbench_domains/*/domain.py` (RSS via a window delta + a `measurement_comparable_memory` flag), `clusterbench_core/model.py` (RunResult.measurement_flags); Test `tests/test_rss.py`
**Interfaces:** When run under `InProcessLauncher`, `peak_rss_kb` is marked `memory_comparable=False`; under `LocalProcessLauncher`, RSS is the child's and `memory_comparable=True`. Tuner must not select on memory when `memory_comparable=False`.
- [ ] **Test (Review Focus #2):** two in-process trials → both `memory_comparable=False`; a subprocess trial → `memory_comparable=True` and RSS not monotonically inheriting the prior.
- [ ] Implement.
- [ ] Commit: `fix(domains): attributable RSS via subprocess; flag in-process RSS non-comparable`

### Task 4.4: Reproduction tolerances (p99 out, p50→10%, recall→0.5pp)

**Files:** Modify `clusterbench_core/discipline/reliability.py` `DEFAULT_TOLERANCES`; Test extend `tests/test_discipline.py`
**Interfaces:** Remove `p99_ms` from the gate (keep as diagnostic); `p50_ms` 20%→10%; `recall@10` 0.01→0.005.
- [ ] **Test:** a run differing only in p99 reproduces (not capped); a 15%-p50 drift fails (tol now 10%).
- [ ] Implement.
- [ ] Commit: `fix(reliability): drop p99 from gate; tighten p50/recall tolerances`

---

## Phase 5 — Gate 2: measurement comparability

### Task 5.1: Replication harness + effect>noise + CV ceiling

**Files:** Create `clusterbench_core/measurement.py`; Modify `clusterbench_core/tuning.py` to compare via it; Test `tests/test_measurement.py`
**Interfaces:** Produces `measure_repeated(run_once: Callable[[int], float], R=7) -> MeasureStats(median, ci_lo, ci_hi, cv)`; `is_real_improvement(baseline: MeasureStats, cand: MeasureStats, mde=0.03) -> bool` (CI of the median shift excludes 0 AND rel ≥ mde); `comparable_cv(stats, ceiling=0.15) -> bool`.
- [ ] **Test (Review Focus #4):** a 1% difference with 5% noise → `is_real_improvement` False; a 10% difference with 2% noise → True; CV 0.2 → not comparable.
- [ ] Implement bootstrap CI (≥2000 resamples) over run-medians.
- [ ] Commit: `feat(measurement): replication, effect>noise (MDE), CV ceiling`

### Task 5.2: Warmth/order control

**Files:** Modify `clusterbench_core/tuning.py` (interleave baseline A/B/A; warmth fingerprint), register `query.warmup`/`seismic.warmup` as controlled params in the domains’ manifests + build/measure; Test `tests/test_warmth.py`
**Interfaces:** `Tuner` re-measures the baseline interleaved; if baseline median drifts beyond its own CI across the search → mark the window non-comparable. `warmup` becomes a controlled identity param (trips Gate 1 if clamped).
- [ ] **Test:** a domain whose baseline latency drifts upward across trials → interleaved-baseline check flags non-comparable; clamping `query.warmup` → effective≠declared.
- [ ] Implement.
- [ ] Commit: `feat(fairness): interleaved-baseline warmth control + warmup as controlled param`

### Task 5.3: Environment + code fingerprint

**Files:** Create `clusterbench_core/fingerprint.py`; Modify `clusterbench_core/lifecycle.py` (stamp) + baseline reuse path; Test `tests/test_fingerprint.py`
**Interfaces:** Produces `env_fingerprint() -> dict` (host, CPU model, container image digest if any, key lib versions, git SHA of domains+ops) and `assert_comparable_fingerprint(baseline_fp, current_fp)` → raises `BaselineFingerprintMismatch`.
- [ ] **Test:** reuse with a mutated fingerprint dict raises; identical passes.
- [ ] Implement.
- [ ] Commit: `feat(fairness): environment+code fingerprint, refuse cross-fingerprint baseline`

### Task 5.4: Wider Phase C for OpenSearch

**Files:** Modify `clusterbench_domains/opensearch/domain.py` `verify_config` + `required_params.yaml`; Test `tests/test_phase_c_coverage.py` (`-m happy`)
**Interfaces:** `verify_config` additionally reads JVM heap (`_nodes/jvm`), container memory limit (docker inspect), merge policy, thread pools, and compares to declared.
- [ ] **Test (`happy`):** declare heap X, start container with heap Y → Phase C mismatch blocks.
- [ ] Implement.
- [ ] Commit: `feat(opensearch): extend Phase C to JVM heap/cgroup/merge/threadpools`

---

## Phase 6 — Loop guard

### Task 6.1: Comparability verdict on `Trial`

**Files:** Modify `clusterbench_core/tuning.py` (`Trial` gains `comparable`, `reliability_tag`, `effective_matches_declared`, `signature_diff`, populated in `_eval` from `RunResult`); Test `tests/test_tuning.py`
**Interfaces:** `_comparable(trial) -> bool` = `COMPLETED ∧ tag∈{RELIABLE,QUALIFIED} ∧ effective==declared ∧ measurement_comparable`.
- [ ] **Test:** a trial built from an UNRELIABLE RunResult → `comparable False`; a clean one → True.
- [ ] Implement.
- [ ] Commit: `feat(tuning): per-trial comparability verdict`

### Task 6.2: LoopBudget + guard state + halts + `_better` gate

**Files:** Modify `clusterbench_core/tuning.py`; Create nothing; Test `tests/test_loop_guard.py`
**Interfaces:** Produces `HaltReason` enum, `LoopBudget` dataclass (defaults from Global Constraints), guard state + `_check_halt() -> HaltReason|None` evaluated in the spec §12.3 order; `_better(a,b)` returns False unless `a in comparable`.
- [ ] **Tests (Review Focus #5 + halts):**
```python
def test_better_never_selects_noncomparable(...): ...   # safety
def test_streak_halts_and_asks(...): ...                 # K=3 → NONCOMPARABLE_STREAK, needs_human
def test_baseline_ungrounded_halts_before_treatment(...): ...
def test_unresolvable_effect_halts(...): ...             # baseline CI half-width > MDE
def test_budget_and_no_progress_auto_halt(...): ...
def test_loop_always_terminates(...): ...                # liveness
```
- [ ] Implement guard; insert post-trial `_check_halt` + pre-loop baseline check into grid/refine/coordinate.
- [ ] Commit: `feat(tuning): loop guard — comparability-gated selection + halt reasons`

### Task 6.3: HaltReport + `TuningResult.recommendation`

**Files:** Modify `clusterbench_core/tuning.py`; Test extend `tests/test_loop_guard.py`
**Interfaces:** Produces `HaltReport(reason, message, needs_human, offending_trials, comparable_count, total_trials, best_comparable, recommendation_safe, detail)`; `TuningResult.halt`, `.comparable`, and `.recommendation -> Trial|None` (== best iff `recommendation_safe`).
- [ ] **Test:** no-comparable search → `recommendation is None`, `recommendation_safe False`, HaltReport carries the signature_diff of offenders.
- [ ] Implement; experiments print `recommendation`/halt.
- [ ] Commit: `feat(tuning): HaltReport + safe recommendation property`

---

## Phase 7 — Acceptance & contribution

### Task 7.1: Full acceptance

**Files:** Modify experiments to use `recommendation`; Test run all suites.
- [ ] Run `pytest -m "not happy"` → all green; `pytest -m happy` → both tuning happy paths pass and now report replicated (R≥7) results with a recommendation + halt reason; coverage ≥ prior.
- [ ] Commit: `test: full acceptance of native engine + two-gate fairness`

### Task 7.2: Contribute to the benchmark plugin

**Files:** per the destination decision (see Handoff).
- [ ] Clone `model-collapse/benchmark-agent-plugin`; create branch `feat/clusterbench-native-engine`; land ClusterBench per the agreed structure; push via SSH.
- [ ] (PAT cannot open PRs — provide the compare URL for the user to open the PR, as with the experimaestro contribution.)
- [ ] Commit message + PR body summarizing the two-gate fairness contribution.

---

## Self-review notes
- **Spec coverage:** Phase 0 = §8 relicense; Phase 1 = §3/§4/§5 engine; Phase 2 = §6/§7 lifecycle+domain persistence; Phase 3 = §12.1 Gate 1; Phase 4 = §14 fixes; Phase 5 = §12.2 Gate 2; Phase 6 = §12.3 loop guard; §12.4 policy caveats are enforced as the completeness-lint test in Task 3.2 + the RCP backstop deferred (noted, not v1-blocking). v2 (Slurm/SSH/tokens) intentionally out.
- **Review Focus:** all five pinned to tasks 3.2 / 4.3 / 4.1 / 5.1 / 6.2 respectively.
- **Type consistency:** `comparable`, `effective_signature`, `signature_diff`, `reliability_tag`, `recommendation`, `HaltReason`, `LoopBudget` used identically across tasks 3.3/6.1/6.2/6.3.
