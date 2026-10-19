# ClusterBench Native Engine — Design Spec

**Date:** 2026-10-17
**Status:** draft for review
**Supersedes dependency:** removes experimaestro; relicenses the project to **Apache-2.0**

## 1. Purpose

Replace experimaestro (GPL-3.0) with a small, **clean-room, Apache-2.0 execution
engine** owned by this project and merged into `benchmark_engine`. The engine is
informed by *what* an experiment runner must do — not by experimaestro's code. Once
experimaestro is gone from the base install, the whole project is relicensed
Apache-2.0 to match the plugin ecosystem.

Non-negotiable property preserved from the current system: a benchmark's
deterministic prep (index build) is reused across runs/trials, while the
measurement is always re-run — the cache-vs-reproduction split.

## 2. Locked decisions (from brainstorming)

- **Approach C**: reuse our dataclass configs + `signature()`; add a
  `Step` / `Launcher` / `Cache` / `Scheduler` execution layer. **No typed-`Param`
  metaclass** (we accept hand-declared dependencies and hand-declared cache keys;
  our configs are flat, so this is trivial and transparent).
- **Drop experimaestro entirely** — remove `benchmark_engine/xpm.py` and the
  dependency.
- **Relicense to Apache-2.0.**
- **Full** capability target, delivered in **phases** (see §10): v1 local
  (in-process + subprocess) with on-disk cache; v2 remote launchers + resource tokens.

## 3. Architecture (Approach C)

New module tree under the engine (all Apache-2.0, no external GPL):

```
benchmark_engine/
  model.py          # (existing) BenchmarkConfig, RunResult, signature()
  engine/
    step.py         # Step, StepRef, StepResult
    signature.py    # content-hash helpers (generalized from model.signature)
    cache.py        # on-disk content-addressed cache (SignatureCache)
    launcher.py     # Launcher protocol; InProcessLauncher, LocalProcessLauncher
    worker.py       # subprocess entrypoint (we own its sys.path — no L5 gap)
    scheduler.py    # DAG topo-sort + parallel dispatch honoring the cache
  lifecycle.py      # (existing) now expressed as Steps on the engine
  guard.py          # (existing) OOMGuard wired into LocalProcessLauncher
```

Dependency direction unchanged: `plugin → domains → ops → core(+engine)`. The
engine depends on nothing GPL.

## 4. Core abstractions

- **`Step`** — a unit of work:
  `Step(name, fn, inputs: dict, cache_key: tuple|None, cacheable: bool, depends_on: list[Step])`.
  `fn` is referenced as `"module:function"` so it can run in a subprocess.
  `inputs` values are literals, config dicts, or `StepRef`s to upstream outputs.
- **`StepRef`** — a handle to a step's (future) output. Passing a `StepRef` as an
  input *is* a dependency edge (data-flow form); `depends_on` is the explicit form.
  Both are plain Python — no metaclass.
- **`StepResult`** — `{status, outputs (paths/values), metrics, phases}`; persisted.
- **`SignatureCache`** — on-disk, content-addressed:
  `path_for(step_name, sig)`, `has(sig)`, `store(sig, producer)`. Layout
  `cache_root/<step_name>/<sig>/`. A `cacheable` step with a hit is **reused**; a
  non-cacheable step (measurement) always runs into a per-run dir.
- **`Launcher`** (protocol) — `run(step, inputs, workdir) -> StepResult`. The launcher
  is selected per experiment (default configurable; happy paths may use `InProcess`
  for speed and `LocalProcess` when isolation/guard enforcement is wanted):
  - `InProcessLauncher`: call `fn` in-process. Simplest; matches today's behavior.
  - `LocalProcessLauncher`: run `fn` in a subprocess via `worker.py`
    (serialized inputs + `module:function`), with the **OOM guard** monitoring the
    child; captures stdout/err to the step dir.
  - `SlurmLauncher` / `SSHLauncher` (v2): same interface, submit remotely.
- **`Scheduler`** — takes the step set, topologically sorts by edges, runs
  independent steps concurrently (bounded worker pool), consulting the cache before
  dispatching, and collecting `StepResult`s.

## 5. Identity & caching model

- **Hand-declared keys.** Each step's `cache_key` is an explicit tuple of the
  identity-bearing inputs. Build steps exclude search-time params; measure steps
  include them (exactly our existing `SeismicDomain._build_key`, promoted to the
  engine contract). A `repro_nonce` participates in a measurement's identity to
  force a fresh reproduction run.
- **Signature** = `sha256(json(cache_key))[:16]` (generalized from
  `BenchmarkConfig.signature`).
- **Correctness responsibility (accepted risk, §12):** the author must put every
  build-affecting param in the build step's key; omitting one risks a false cache
  hit (stale artifact). We mitigate with a lint helper that diffs a step's declared
  key against the config params it reads (best-effort) and with domain tests.

## 6. Execution & isolation; the Domain contract change

Subprocess isolation + an on-disk cache both require **prep artifacts to be
persistable** (today the SEISMIC index is reused in-memory). The `Domain` protocol
gains serialization:

- `prep(cfg, ctx) -> PrepArtifact` must produce an artifact that can be
  **saved** to and **loaded** from a cache path:
  - SEISMIC: `SeismicIndex.save(path)` / `load(path)`.
  - OpenSearch: the index lives in the container; the artifact is
    `{endpoint, index_name}` (the container is a run-scoped resource owned by the
    launcher/harness, not a per-step subprocess).
- `measure(cfg, artifact, ctx)` loads the artifact (or reuses the live handle under
  `InProcessLauncher`).

This makes the build cache **cross-session** (a strict improvement over the current
in-memory cache) and is what unlocks subprocess isolation and (later) remote launchers.

## 7. Integration with existing layers

- **lifecycle.py**: `budget → manifest → preflight → prep → measure → validate →
  classify → persist` becomes a tiny fixed step graph: `prep` (cacheable) → `measure`
  (non-cacheable, guarded). Preflight/budget/manifest remain pre-step gates
  (unchanged discipline). `run_lifecycle` builds these two Steps and runs them via a
  `Launcher` + `Scheduler`.
- **tuner.py**: unchanged API; each trial submits a lifecycle. Because the build
  step is cacheable and keyed without the search param, the index builds once and
  all trials reuse it — same behavior we ship today, now cross-session.
- **discipline/**: unchanged.
- **domains/**: gain `save`/`load` for prep artifacts (SEISMIC, OpenSearch, demo).
- **`xpm.py`**: deleted. `run_on_experimaestro` is replaced by the native
  `Scheduler.run(...)`; the experimaestro test (`test_xpm.py`) is replaced by native
  engine tests.

## 8. Migration & relicense

1. Build `benchmark_engine/engine/*`; wire `lifecycle`/`tuner` onto it behind the
   existing APIs (no change for callers/experiments).
2. Add `save`/`load` to the three domains.
3. Delete `xpm.py`, `tests/test_xpm.py`; drop `experimaestro` from `pyproject.toml`
   dependencies.
4. Relicense: replace `LICENSE` (GPL-3.0 → Apache-2.0), update `pyproject.toml`
   (`license`, classifiers), add SPDX headers, update `README`/`plugin.json`.
5. Keep the merged upstream `python_path` work only as a historical note in
   `docs/upstream/` (no longer a dependency).

## 9. Dependency specification (recap)

Edges are plain Python: either `depends_on=[prep_step]` or passing
`prep_step.ref` as a `measure` input. The scheduler topo-sorts on these. No
inference, no metaclass. For ClusterBench the graph is `prep → measure` (plus any
domain-specific sub-steps a domain chooses to declare).

## 10. Non-goals / phased roadmap

**v1 (this spec) — full scope, both fairness gates included (user decision
2026-10-17):** local execution (`InProcess` + `LocalProcess` subprocess, with
`LocalProcess` the default whenever memory is a reported/selected metric), on-disk
content-addressed cache (cross-session reuse) + artifact-descriptor verify on load,
OOM guard integration, the fixed lifecycle graph + tuner on the engine, three
domains with save/load, Apache-2.0 relicense. **Plus the full §12 fairness stack:**
Gate 1 (frozen config, point-of-use effective-param capture, effective-vs-declared
gate + field-diff, fail-loud, provenance), Gate 2 (replication R≥7 + effect>noise,
subprocess RSS, warmth/order control, fixed-k recall, data-integrity `passed`,
env+code fingerprint, steady-state + CV ceiling, wider Phase C), and the §12.3 loop
guard. **Plus all §14 current-code fixes.** Team-recommended thresholds (R=7, MDE
3%, K=3, M=5, CV≤15%, 30 trials / 2 h / 5 aborts) are the defaults, tunable via
`LoopBudget`. Long-run survival relies on the existing `clusterbench_run` skill's
`nohup` + `.running/.complete/.failed` + resume pattern (harness-level).

Scope note: this is a larger v1 than the engine alone — the fairness stack roughly
doubles it. The writing-plans output will sequence it (engine core → Gate 1 →
§14 fixes → Gate 2 → loop guard) so each layer is independently testable.

**v2 (roadmap, not now):** `SlurmLauncher` / `SSHLauncher` (real multi-node);
resource **tokens** (graph-level admission so jobs don't oversubscribe RAM/GPU);
engine-level resume/re-attach for jobs that outlive the driver.

**Never (out of scope — experimaestro's territory we don't need):** typed-`Param`
metaclass with automatic deep-graph cache invalidation; arbitrary nested-object
serialization; live TUI/web monitor; the datamaestro/xpm-torch/xpmir ecosystem.

Acknowledged lags vs experimaestro at v1: cluster launchers (roadmap), engine-level
resume (harness-mitigated), resource-aware concurrency (roadmap), and global
cache maturity (ours is per-project). None block ClusterBench's workload.

## 11. Testing strategy

- **Unit:** signature determinism/sensitivity; cache hit/miss + stale-key detection;
  scheduler topo-order + parallelism + failure propagation; `InProcessLauncher` and
  `LocalProcessLauncher` parity on a toy step; OOM guard kills an over-budget
  subprocess step (reuse existing guard test).
- **Integration (fakes):** full lifecycle over `DemoDomain` on both launchers;
  forced-OOM → `ABORTED_GUARDRAIL`; a tuning run proves the build step is cached and
  reused across trials (cross-session: second process reuses the on-disk artifact).
- **Happy paths (unchanged):** the OpenSearch + SEISMIC tuning experiments must pass
  identically after the swap — this is the migration's acceptance test.
- **License:** a test/CI check that `experimaestro` is not importable in the base
  install and the LICENSE is Apache-2.0.
- **Fairness (§12):** a clamp-injection test — a measure step clamps a param at
  point-of-use and the effective-vs-declared gate MUST tag the run UNRELIABLE
  (red-team rank-1 regression guard); replication/variance picks reject a
  sub-noise "speedup"; RSS measured in-subprocess differs from the contaminated
  in-process value; a partial-ingest run computes `passed=False`; a
  mismatched-fingerprint baseline refuses reuse; the loop guard halts+ASKs on a
  forced non-comparable streak and on an unresolvable (noise > MDE) baseline.

## 12. Fairness & effective-parameter integrity

**Synthesized from a 4-agent review (red-team, measurement-validity, loop-control,
prior-art).** The central result: fairness is **two axes**, needing **two gates**.

- **Axis 1 — parameter identity:** did the run *use* the parameters it declared?
- **Axis 2 — measurement comparability:** even when effective == declared, is the
  *measurement* itself a fair comparison (noise, warmth, isolation, data integrity,
  environment)?

The four invariants below cover Axis 1. They are **parameter-identity checks and
structurally cannot see Axis-2 failures** — where effective == declared yet the
comparison is still unfair. Both gates feed one `comparable` verdict that the loop
guard (§12.3) keys off. (Prior art: only MLPerf does real effective-param
verification — via log-at-point-of-use + anomaly detection + audit; DVC/Metaflow
verify effective *outputs* by content hash; Sacred/MLflow/W&B/Hydra/experimaestro
record only *declared* values. §12 is ahead of the ML-tooling mainstream — provided
capture is honest, see §12.4.)

### 12.1 Gate 1 — parameter identity (4 invariants)

1. **Frozen config + "mutate ⇒ new run".** `BenchmarkConfig` is `@dataclass(frozen=True)`
   (Sacred's read-only-config pattern, native); nested containers become immutable at
   freeze (tuples / `MappingProxyType`). Signature computed once at freeze and
   **re-asserted on each step entry**. The agent/engine may NOT mutate an in-flight
   run; any safety change becomes a new config → new signature → a new,
   honestly-labeled run.
2. **Effective-parameter manifest — captured AT POINT OF USE (keystone).** The
   manifest MUST record the value *actually passed into the operation*
   (`idx.search(...)`, the query body), via a single recorder accessor
   `ctx.effective(name, value)` **at the consumption site** — NOT by re-reading
   `cfg.get(name)`. Re-reading echoes the declared value and proves nothing; it
   defeats the entire defense (red-team rank-1). This is MLPerf's "mllog the value
   you actually ran with."
3. **Effective-vs-declared gate (in `classify`).** Fast path: `sha256(canonical JSON
   of sorted identity-bearing effective params)` vs the declared signature. Also
   retain the **structured per-field diff** (not just the hash) so the report can
   name *which* param drifted (the spec requires explaining the deviation). On any
   identity-bearing mismatch → auto-tag UNRELIABLE (silent) / EXPLORATORY; report
   must explain. `classify` sets `reliability_tag`, `effective_signature`, and
   `signature_diff` onto `RunResult` (contract the loop guard consumes).
4. **Fail-loud.** A safety mechanism may **abort** (like the OOM guard) or **record a
   deviation** — never silently continue with an altered comparison variable. Engine
   assertion (effective≠declared on a controlled var ⇒ cannot be RELIABLE/QUALIFIED)
   + plugin forbidden rule.

**Provenance recorded with every result** (MLflow/Sacred/MLPerf standard set):
`declared_signature`, `effective_signature`, code/package version + git SHA of
`domains/`+`ops/`, RNG seed(s), start/end time, hostname, launcher type, applied
resource limits; and per deviation: `{field, declared, effective, mechanism, reason}`.

### 12.2 Gate 2 — measurement comparability (new axis)

effective == declared is necessary but **not sufficient**. A trial is
measurement-comparable only if:

- **Replication + variance (biggest driver of wrong picks).** A trial is R
  independent measurement runs (default R=7, min 5) via `repro_nonce`, compared as a
  **distribution of run-medians**. A speedup is "real" only if the median shift's 95%
  bootstrap CI excludes 0 **and** the relative improvement ≥ **MDE = 3%** (don't act
  on significant-but-trivial deltas). "better" and "no-progress" tests use
  effect-vs-noise, never point estimates.
- **Memory metric isolation.** `peak_rss_kb` via `ru_maxrss` is a process-lifetime
  high-water mark → under `InProcess` it accumulates across trials (baseline always
  looks leanest). RSS is only comparable when measured in a **fresh subprocess**
  (`LocalProcessLauncher`) or as a window delta; otherwise it is tagged
  non-comparable and never selected on. **→ measurement steps default to
  `LocalProcessLauncher` when memory is reported/selected.**
- **Order / warmth control.** Shared process/container warms over a run (page cache,
  JIT, GC, allocator) favoring later trials. Counterbalance / interleave the baseline
  (A/B/A) and reject if the baseline drifts beyond variance; record a warmth
  fingerprint. Register `query.warmup` (and SEISMIC's warmup) as **controlled
  identity params** so clamping them trips Gate 1.
- **Metric-definition integrity.** `recall@10` must be scored with a **fixed k=10**;
  assert `cfg.k == 10` for any recall@10 comparison (or name the metric `recall@{k}`
  and forbid mixing k's), and add `k` to the comparability key.
- **Data-integrity-derived `passed`.** `functional_validation.passed` must be
  *computed*, not hardcoded `True`: recall ≥ floor **and** indexed doc-count == expected
  **and** hits == k **and** no bulk partial-failure (`raise_on_error`) **and** no
  silent client retry. Any shortfall ⇒ UNRELIABLE (so the loop guard's exclusion +
  streak-breaker actually fire — today's hardcoded `True` bypasses them entirely).
- **Environment + code fingerprint.** Stamp host/CPU, container image digest, lib
  versions, git SHA of `domains/`+`ops/`. **Refuse to reuse/compare a baseline whose
  fingerprint differs** (cross-session on a loaded box / rebuilt container / dependency
  bump looks comparable at identical signature otherwise).
- **Artifact-descriptor verify on load (DVC-style).** On cache reuse, verify the live
  artifact matches a persisted descriptor (SEISMIC: content hash; OpenSearch: index
  UUID + segment count + doc count). Mismatch ⇒ cache miss / baseline re-establishment,
  never a silent hit. (Closes the §13 false-cache-hit risk for OpenSearch too, whose
  cross-session cache is currently in-memory only — `save/load` is still TODO.)
- **Steady-state + variance ceiling.** Discard warmup (≥50 queries or 25% of N),
  verify first-half vs second-half medians within 10%, and tag a trial whose CV
  (stdev of run-medians / median) > 15% **non-comparable** (it feeds the same streak
  breaker). Baseline CV > 15% ⇒ halt immediately (environment ungrounded).
- **Phase C coverage.** Extend `verify_config` beyond the 4 settings to JVM heap,
  cgroup memory limit, merge policy, and thread pools (undeclared treatment surface
  that silently moves latency/GC tails).

### 12.3 Loop guard — no effortless/unfair experiment loops

One predicate drives everything (spans **both** gates):
```
comparable := status == COMPLETED
          AND reliability_tag in {RELIABLE, QUALIFIED}
          AND effective_signature == declared_signature          # Gate 1
          AND measurement_comparable                              # Gate 2: CV≤15%,
              # fingerprint-match, data-integrity pass, RSS-isolated-if-selected
```
`_better()` is gated on `trial in comparable`, so a non-comparable trial can
**never** become the recommendation; `TuningResult.recommendation` is a comparable,
grounded, floor-passing trial or `None`.

Guard **state** (reset per search): `comparable[]`, `streak_noncomparable`,
`trials_run` (cache hits don't count), `aborts_total`, `wall_start`, `best_history`,
`baseline_ok`, latched `halt_reason`.

**Halt reasons** (evaluated in order; first trip wins; defaults in parens):
- `BASELINE_UNGROUNDED` — baseline trial non-comparable **or** baseline CV>15%;
  checked *before* any treatment trial → **ASK** (re-establish, don't continue).
- `NONCOMPARABLE_STREAK` — `streak ≥ K` (K=3) → **ASK** (stop, don't iterate on garbage).
- `UNRESOLVABLE_EFFECT` — baseline p50 CI half-width > MDE (3%): the target effect is
  below measurement resolution → **ASK** (can't optimize noise; fix environment / raise N).
- `BUDGET_TRIALS` / `BUDGET_WALLCLOCK` / `BUDGET_ABORTS` — (30 trials / 2 h / 5
  aborts) → auto-halt.
- `NO_PROGRESS` — no comparable trial beats baseline by ≥MDE (CI-excludes-0) over the
  last M=5 comparable trials → auto-halt.
- `SEARCH_EXHAUSTED` — strategy space done → clean success.

**ASK vs auto:** `BASELINE_UNGROUNDED`, `NONCOMPARABLE_STREAK`, `UNRESOLVABLE_EFFECT`
mean *the experiment is broken* — the Tuner stops and surfaces a `HaltReport` (reason,
offending run_ids, `signature_diff`, comparable-vs-total counts, `recommendation_safe`)
to the harness/human and does **not** auto-retry. Budgets / no-progress / exhausted
return normally with the (possibly empty) comparable set.

**Liveness & safety:** each strategy is independently finite (grid/refine/coordinate
bounds); the guard only adds earlier monotonic exits and never retries → the loop
always terminates. The recommendation is always a comparable trial or `None`.

API shape: `HaltReason` enum, `LoopBudget` dataclass (the defaults above), `Trial`
gains `comparable/reliability_tag/effective_matches_declared/signature_diff`,
`HaltReport`, `TuningResult.{halt, comparable, recommendation}`.

### 12.4 Guarantees that are policy/convention, not pure-engine

- **Completeness of capture.** The engine only records params that cross
  `ctx.effective`; it cannot prove a third-party/library call didn't use something
  differently internally. "Every controlled param is captured" is a **best-effort lint**
  (diff declared `cache_key` fields vs recorder calls), not a proof.
- **Honesty of self-reported effective values.** A forged effective value can't be
  caught structurally. In-engine backstop = a cheap **RCP-style outlier check** across
  comparable trials; beyond that it is audit/reputation policy (MLPerf's model).
- **Non-determinism** (timing, GC, BLAS). Mitigated by seed-logging + tolerances, not
  eliminated.
- **Threshold validity depends on capture.** The §12.3 K/M/MDE/CV knobs are only as
  meaningful as capture is honest+complete — stated explicitly so it isn't assumed away.

## 13. Risks & mitigations

- **False cache hit from a wrong hand-declared key** (stale artifact, silent). →
  key-vs-params lint helper + artifact-descriptor verify on load (§12.2) + domain tests.
- **Prep-artifact serialization effort** (SEISMIC save/load, OpenSearch index
  lifetime). → SEISMIC has native save/load; OpenSearch artifact = container-scoped
  descriptor (UUID+segments+docs); demo trivially serializes.
- **Subprocess import/env** (the L5 trap). → we own `worker.py`'s launch, so we set
  its `sys.path`/`PYTHONPATH` explicitly; no external-API gap.
- **Effective-capture is only as good as its weakest site** (red-team rank-1). →
  single recorder accessor + a unit test that injects a clamp and asserts the gate
  fires; the completeness lint; label it best-effort (§12.4).
- **New-engine edge cases vs years-hardened experimaestro.** → keep v1 small; the two
  real happy paths + the fake integration suite are the regression guard.

## 14. Current-code fixes required (honest audit from the review)

These are defects in the **already-shipped** domains, independent of the engine swap;
the migration must fix them:

1. **`peak_rss_kb` is not a per-trial metric** (`ru_maxrss` high-water mark). Measure
   in a subprocess or report a window delta; never select on in-process RSS. *(Shipped
   recommendations did NOT select on RSS — selection was p50 within the recall floor —
   so this did not change the shipped picks, but the reported RSS numbers are
   contaminated.)*
2. **Single-pass measurement, no replication.** The shipped speedups (OpenSearch
   1.76×, SEISMIC 1.39×) are **single-shot point estimates** — large enough to be
   likely-real, but **unvalidated** to the R≥7 + MDE standard; re-run under replication
   before citing as RELIABLE.
3. **`functional_validation.passed` hardcoded `True`.** Compute it (§12.2).
4. **p99 from N≈200 gates reproduction.** Drop p99 from the gate (diagnostic only) or
   raise N ≥ 1000–5000.
5. **`recall@10` with floating k.** Shipped experiments fixed k=10 so this didn't bite,
   but assert it so it can't regress.
6. **Residual cross-trial warmth bias.** We added a warm-up pass (fixing cold-start
   inversion), but shared-process/container warmth still favors later trials; adopt
   order counterbalancing / interleaved baseline.
7. **Concurrent measurement (future §4 scheduler).** Serialize measurement steps
   (exclusive resource) — timing/RSS under contention is incomparable. Our sequential
   tuner is fine today; this guards the parallel scheduler.
