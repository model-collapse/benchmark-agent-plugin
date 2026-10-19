# ClusterBench

A **reproducible experiment harness** for benchmarking systems fairly. You wrap
*your* system (a retriever, reranker, vector DB, index — anything benchmarkable)
in a `Domain`; the harness gives you fair comparison, a required-params gate,
preflight, an OOM guard, two experiment-fairness gates, replication, reproduction,
provenance, a hyperparameter tuner, cross-session caching, a loop guard, and
honest persisted reports.

It ships with a native, Apache-2.0 execution engine (no GPL dependencies) and two
reference domains — **OpenSearch** (`rank_features` SPLADE + force-merge) and
**SEISMIC** (`pyseismic-lsr`) — plus a `demo` template. The science (models,
datasets, metrics) is *yours*, supplied through a `Domain`; the harness is
metric-agnostic.

> License: **Apache-2.0** — a self-contained native engine, no experimaestro / no GPL.
> This is the ClusterBench framework shipped inside the benchmark-agent-plugin; the
> plugin's top-level `README.md` covers the plugin as a whole.

## Architecture (strict one-way dependency)

```
plugin (Claude Code skills) → clusterbench_domains → clusterbench_ops → clusterbench_core
```

- **clusterbench_core** — the engine + discipline:
  - `engine/` — the native execution engine: content-hash `signature`, on-disk
    content-addressed `cache` (atomic store + descriptor-verify), `step`/DAG,
    `scheduler` (parallel prep, serialized measurement), `launcher`
    (InProcess + OOM-guarded subprocess) + `worker`/`measure_entry`,
    `effective` (point-of-use param recorder).
  - `model` — frozen typed `BenchmarkConfig` (single source of truth) + `RunResult`.
  - `lifecycle` — `budget → manifest → preflight(A/B/C) → prep(cached) →
    measure(guarded) → validate → classify → persist`.
  - `discipline/` — `manifest` (hard gate), `preflight`, `reliability` (tags +
    reproduction + fail-loud), `analysis` (report with mandatory "What Went Wrong").
  - `tuning` — the **Tuner** (grid / refine / coordinate) with replication,
    effect>noise selection, and the **loop guard**; `sweep` is the single-grid primitive.
  - `measurement` (replication / MDE / CV), `guard` (OOM), `fingerprint` (env+code),
    `report_index` (results index + `load_runs` for analysis).
- **clusterbench_ops** — SPLADE encoding (synthetic + real-model interface), recall ground truth.
- **clusterbench_domains** — `demo` (template), `seismic`, `opensearch` + `required_params.yaml` manifests.
- **plugin** — `clusterbench_plan` / `clusterbench_run` / `clusterbench_domain` skills + awareness hook.

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

Implement the `clusterbench_core.domain.Domain` protocol (5 methods minimum) and
drive it with the `Tuner`. See **`docs/clusterbench/DOMAIN_API.md`** for the full
guide (required vs optional methods, the point-of-use capture rule, worked examples),
and `clusterbench_domains/demo.py` as a template. Pull results into analysis with
`clusterbench_core.report_index.load_runs(workdir)`.

## Reference happy paths (SPLADE)

```bash
python -m experiments.opensearch_splade ./clusterbench_data/opensearch   # tune force-merge
python -m experiments.seismic_splade   ./clusterbench_data/seismic       # tune heap_factor
```
Each tunes a hyperparameter for search speed within a recall floor and writes
`clusterbench_data/<domain>/<run_id>/{config.yaml,results.yaml,report.md}` +
`results_index.md`. Observed (small scale): OpenSearch 16→1 segments ≈ 1.8–3.9×
faster p50 at equal recall; SEISMIC heap_factor ≈ 1.4–2.2× faster within a 1pp floor.

## Tests

```bash
pytest -m "not happy"    # 134 fast, deterministic tests, no external deps
pytest -m engine         #   (subset) native engine integration (spawns worker subprocess)
pytest -m happy          # 3 end-to-end smoke tests: real OpenSearch (Docker) + SEISMIC
```
137 tests total. The fast suite (`-m "not happy"`) exercises the engine, discipline,
both fairness gates and the loop guard with no external dependencies; the 3 `happy`
tests add real-cluster coverage of the reference domains.
