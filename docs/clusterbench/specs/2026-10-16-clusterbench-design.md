# ClusterBench — Design Spec

**Date:** 2026-10-16
**Status:** approved (autonomous build per `/goal`)
**License:** GPL-3.0 (direct import of experimaestro)

## Purpose

A cluster-ops **benchmarking framework built on experimaestro-core**. It brings
the deterministic execution engine of experimaestro (typed `Config`/`Task`,
signature-hash caching, scheduler, launchers) together with the *discipline*
layer of the `model-collapse/benchmark-agent-plugin` (fair comparison,
required-params manifest, three-phase preflight, reliability tags, skeptical
reporting). The result is a systems analog of what `xpmir` is for IR: a general
abstraction for benchmarking cluster operations (OOM-prone force-merge,
ingestion, index build, retrieval latency/recall), with OpenSearch and SEISMIC
as the two reference domains.

Success = two happy paths run end-to-end and produce honest, reproducible speed
numbers from a hyperparameter sweep:
- **(a)** SPLADE / SPLADE-v3 on a **local OpenSearch** cluster.
- **(b)** SPLADE / SPLADE-v2 on **SEISMIC**.
…plus full automated test coverage.

## Architecture (Approach C: lifecycle backbone + op-library + domain manifests)

Strict one-way dependency: `plugin → benchmark_domains → benchmark_ops → benchmark_engine → experimaestro`.

```
benchmark_engine/      engine: lifecycle backbone, discipline, guard, model/schema
benchmark_ops/       reusable op-tasks (encode, ingest, forcemerge, build, probe, eval)
benchmark_domains/   domain plugins + required_params manifests (opensearch, seismic)
plugin/                 Claude Code harness: skills (plan/run/domain) + awareness hook
experiments/            the two happy-path experiment scripts
tests/                  unit + integration (fakes) + happy-path smoke
```

### Layer 2a — `benchmark_engine`

- **model/** — `BenchmarkConfig` (typed experimaestro `Config`: hypothesis,
  treatment variable, controlled variables, resource budget, domain, phases),
  `RunResult`/`PhaseMetrics` schema, `ReliabilityTag` enum, run-folder ↔ job-hash
  mapping.
- **lifecycle/** — the invariant spine as composable callables/tasks:
  `budget → apply → prep → measure → verify → validate → persist`.
  Prep tasks are **cacheable** (deterministic build). The **Measurement** step is
  **always-run** (uncacheable) so reproduction runs produce fresh numbers.
- **discipline/** — ported from the plugin, re-pointed at `BenchmarkConfig`:
  - `manifest.py` — load/validate a domain `required_params.yaml` (HARD GATE).
  - `preflight.py` — Phase A baseline diff (flatten+classify), Phase B apply,
    Phase C post-deploy verify. Mirrors `preflight_compare.py`.
  - `reliability.py` — tag rules incl. the reproduction requirement
    (RELIABLE ⇒ reproduced within tolerance), downgrade triggers, forbidden
    behaviors as assertions.
  - `analysis.py` — skeptical analysis + report generation (mandatory
    "What Went Wrong" section).
- **guard/** — `OOMGuard`: resource budget → warn/hard/emergency thresholds;
  a `GuardedLauncher` wrapper (Slurm `--mem` on cluster; polling sidecar that
  SIGTERM/SIGKILLs at 85/92% on local/SSH).

### Layer 2b — `benchmark_ops`

Reusable, domain-agnostic op-tasks with typed params. Each declares inputs,
outputs, and (optionally) whether it is a cacheable prep op or a measurement op:
`SpladeEncode` (real transformers OR synthetic), `CorpusSource`, `Ingest`,
`ForceMerge`, `BuildIndex`, `LatencyProbe`, `RecallEval`, `SmokeSearch`.

### Layer — `benchmark_domains`

A `Domain` protocol: `apply_config`, `verify_config`, `required_params()`,
`make_prep_tasks`, `make_measure_tasks`. Reference impls:
- **opensearch/** — Docker-managed single/multi-node cluster, `rank_features`
  SPLADE field, index/merge/shard settings, force-merge, `rank_feature` queries;
  `required_params.yaml` ported from the plugin.
- **seismic/** — `pyseismic-lsr` build/search; `required_params.yaml` for
  `n_postings`, `centroid_fraction`, `summary_energy`, `query_cut`, `heap_factor`.

### Layer 1 — `plugin` (Claude Code harness)

Skills (adapted from the plugin): `clusterbench_plan` (brain: load history,
challenge, build a validated `BenchmarkConfig` + experimaestro experiment
script), `clusterbench_run` (muscle: launch via the experimaestro server, which
is itself the session-death-surviving daemon; monitor; trigger analysis),
`clusterbench_domain` (author a new domain + manifest). Plus the
`experiment_awareness.py` hook (ported) that detects benchmark work.

## Reproducibility ⟂ cache resolution

A run's signature includes `treatment_variable` + a `repro_nonce`. Deterministic
prep (corpus, encoded vectors, built index for a fixed config) is cached and
reused across runs with the same signature. The Measurement op is marked
always-run; a RELIABLE tag requires ≥1 reproduction run whose metrics agree
within domain tolerance (peak RSS 10%, p50/p95 20%, recall@10 1pp, build 30%).

## Hyperparameter sweep + speed optimization

A `Sweep` helper fans a base `BenchmarkConfig` over a treatment-variable grid,
submits one lifecycle per point (prep reused where identical), collects
`RunResult`s, and reports the Pareto frontier / best point on the primary speed
metric (p50 latency or build/merge time) subject to a quality floor
(recall@10 ≥ baseline − 1pp). This is the "tune a hyperparameter, optimize
speed" deliverable for both happy paths.

## Testing

- **Unit** (no cluster): manifest gate, preflight A/B/C classification, guard
  thresholds, reliability tagging + reproduction rule, schema round-trip,
  analysis report structure, sweep/Pareto selection. Deterministic via a
  `FakeDomain` + synthetic SPLADE vectors.
- **Integration** (fakes): a full lifecycle over `FakeDomain` end-to-end,
  including a forced OOM to prove the guard aborts and the run persists as
  ABORTED_GUARDRAIL.
- **Happy-path smoke** (`-m happy`, opt-in): tiny real runs — OpenSearch via
  Docker (a few thousand synthetic SPLADE docs), SEISMIC build+search — asserting
  the sweep picks a faster point without breaking the recall floor.

## Non-goals

Multi-node Slurm execution (interface present, not exercised here); GPU SPLADE
training; a web UI beyond experimaestro's own.
