# Benchmark Harness

A **reproducible experiment harness** for benchmarking systems fairly. You wrap
*your* system (a retriever, reranker, vector DB, index, or an embedding/LLM
pipeline — anything benchmarkable) in a `Domain`; the harness gives you fair
comparison, a required-params gate, preflight, an OOM guard, two experiment-fairness
gates, replication, reproduction, provenance, a hyperparameter tuner, cross-session
caching, a loop guard, and honest persisted reports.

The engine is native and self-contained (Apache-2.0, no external workflow engine, no
GPL). It ships the generic **CommandDomain** (benchmark anything with a DAG of shell
commands — no Python) plus two typed reference domains — **OpenSearch**
(`rank_features` SPLADE + force-merge) and **SEISMIC** (`pyseismic-lsr`) — and a
`demo` template. The science (models, datasets, metrics) is *yours*; the harness is
metric-agnostic.

> License: **Apache-2.0** — a self-contained native engine, no external workflow
> engine, no GPL. The plugin's top-level `README.md` covers the plugin as a whole.

## Architecture (strict one-way dependency)

```
plugin (the /benchmark skill) → benchmark_domains → benchmark_ops → benchmark_engine
```

- **benchmark_engine** — the engine + discipline:
  - `engine/` — the native execution engine: content-hash `signature`, on-disk
    content-addressed `cache` (atomic store + descriptor-verify), `step`/DAG,
    `scheduler` (parallel prep, serialized measurement, opt-in parallel accuracy-only
    measures), `launcher` (InProcess + OOM-guarded subprocess) + `worker`/`measure_entry`,
    `effective` (point-of-use param recorder).
  - `model` — frozen typed `BenchmarkConfig` (single source of truth) + `RunResult`.
  - `lifecycle` — `budget → manifest → preflight(A/B/C) → prep(cached) →
    measure(guarded) → validate → classify → persist`.
  - `discipline/` — `manifest` (hard gate), `preflight` (incl. domain self-validation),
    `reliability` (tags + reproduction + fail-loud), `analysis` (mandatory "What Went Wrong").
  - `tuning` — the **Tuner** (grid / refine / coordinate) with replication,
    effect>noise selection, and the **loop guard**.
  - `measurement` (replication / MDE / CV), `guard` (OOM), `fingerprint` (env+code),
    `report_index` (metric-agnostic results index + `load_runs`).
- **benchmark_ops** — the `command` stage runner (shell stages + stdout/file/CSV metric
  extraction) and SPLADE encoding / recall ground truth.
- **benchmark_domains** — `command` (generic N-stage DAG), `recipes/` (pre-filled
  specs + manifests), `demo`, `seismic`, `opensearch`.
- **plugin** — the one `/benchmark` skill (plan / run / tune / analyze / compare /
  history / reclassify / domain) + the awareness hook.

## The generic CommandDomain

Declare stages in YAML; each is a shell command that produces/consumes named
artifacts. `kind: prep` stages are signature-cached and reused across trials;
`kind: measure` stages always re-run and their metrics (`metrics_from` → stdout JSON
or a JSON/CSV file) become the run's metrics. `needs:` forms the DAG; `effective_from`
captures the resolved config a command actually used (point-of-use, for Gate 1). A
**recipe** pre-fills stages plus a scenario-tuned required-params manifest.

## Experiment-fairness (the differentiator)

Two gates, both feeding one `comparable` verdict the loop guard keys off:
- **Gate 1 — parameter identity:** frozen config (mutate ⇒ new run), effective
  params captured **at point of use** (an adaptive clamp can't hide), effective-vs-
  declared gate + field diff, fail-loud, provenance.
- **Gate 2 — measurement comparability:** R-replication + effect>noise (MDE + 3·SE),
  per-trial attributable memory (subprocess) + non-comparable flagging, env/code
  fingerprint refusal, data-integrity `passed`, configurable per-metric reproduction
  tolerances (relative or absolute).
- **Loop guard:** `_better` can never select a non-comparable trial; the search
  halts (and ASKs) on an ungrounded baseline or a non-comparable streak, auto-halts
  on budgets / no-progress, and is provably terminating.

## Setup

```bash
conda create -y -n clusterbench python=3.11 && conda activate clusterbench
pip install -e ".[opensearch,seismic,dev]"
# SEISMIC (pyseismic-lsr) needs recent Rust: rustup update   (vectorium uses float_algebraic)
# the OpenSearch happy path needs a running Docker daemon
```

## Bring your own experiment

Two routes, both on the full backbone:
- **CommandDomain** — declare `stages` in YAML (optionally from a recipe) and run.
  No Python. See **`docs/benchmark/DOMAIN_API.md`**.
- **Python Domain** — implement the `benchmark_engine.domain.Domain` protocol
  (5 methods minimum) for richer logic; `benchmark_domains/demo.py` is a template.

Drive either with the `Tuner`; pull results into analysis with
`benchmark_engine.report_index.load_runs(workdir)`.

## Reference happy paths (SPLADE)

```bash
python -m experiments.opensearch_splade ./benchmark_data/opensearch   # tune force-merge
python -m experiments.seismic_splade   ./benchmark_data/seismic       # tune heap_factor
```
Each tunes a hyperparameter for search speed within a recall floor and writes
`benchmark_data/<domain>/<run_id>/{config.yaml,results.yaml,report.md}` +
`results_index.md`. Observed (small scale): OpenSearch 16→1 segments ≈ 1.8–3.9×
faster p50 at equal recall; SEISMIC heap_factor ≈ 1.4–2.2× faster within a 1pp floor.

## Tests

```bash
pytest -m "not happy"    # fast, deterministic tests, no external deps
pytest -m happy          # end-to-end smoke: real OpenSearch (Docker) + SEISMIC
```
The fast suite exercises the engine, discipline, both fairness gates, the loop guard,
the CommandDomain pipeline (DAG, caching, metric extraction, validation), and recipes
— including native-engine integration tests in `tests/engine/` that spawn a real
worker subprocess; the `happy` tests add real-cluster coverage of the reference domains.
