# Benchmark Agent Plugin for Claude Code

One general-purpose **experiment harness** for Claude Code. A single `/benchmark`
skill plans, runs, tunes, analyzes, compares, and tracks performance experiments on
*any* system — a database, index, retriever, or an embedding/LLM training+eval
pipeline — backed by a native, self-contained engine (Apache-2.0, no external
workflow engine). Reproducible results with honest, evidence-backed conclusions,
fair-by-construction comparisons, and hard safety guardrails.

## Install

```bash
# Add the marketplace, then install
/plugin marketplace add model-collapse/benchmark-agent-plugin
/plugin install benchmark-agent@benchmark-tools
```

## One skill, verb-dispatched

`/benchmark <verb>` — the skill is a thin judgment layer; every gate, cache, budget,
and fairness check is enforced by the engine it calls, never re-implemented in prose.

| Verb | What it does |
|------|--------------|
| `plan <domain\|recipe> <hypothesis>` | Frame hypothesis / treatment / controls, challenge misaligned requests, produce a validated `BenchmarkConfig` (manifest hard-gate + preflight run here). No execution. |
| `run [--detach]` | Execute via the engine; `--detach` nohups a long/cluster run that survives session death and monitors via `/loop`. |
| `tune` | Hyperparameter search (grid / refine / coordinate) with a **loop guard** that never selects a non-comparable trial and halts (asking a human) on a broken experiment. |
| `analyze <run_id>` | Skeptical interpretation + mandatory "What Went Wrong"; reads the engine-computed reliability tag and fairness verdict. |
| `compare <a> <b>` | Frame the finding; the engine's comparability gates refuse unfair comparisons. |
| `history` / `status` / `reclassify` | One results index as the single source of truth. |
| `domain [--recipe <r>]` | Scaffold a new benchmark target: a CommandDomain stages config or a Python `Domain`. |

## Benchmark anything — the generic CommandDomain

No Python needed: declare a DAG of shell **stages** in YAML and the engine supplies
fair comparison, signature caching, preflight, resource guardrails, and the tuner.

```yaml
domain: command
recipe: retrieval-index           # optional pre-filled template + fairness manifest
stages:
  - name: build                   # kind: prep → signature-cached, reused across trials
    kind: prep
    cmd: "./build_index.sh --docs {corpus.n_docs} --out {index}"
    produces: [index]
  - name: search                  # kind: measure → always re-run; metrics from stdout/file
    kind: measure
    needs: [build]
    cmd: "./search_bench.sh --index {index} --queries {n_queries}"
    metrics_from: {stdout: true, fields: [p50_ms, "recall@10"]}
treatment_variable: forcemerge.max_num_segments
```

The same abstraction covers **retrieval** (`build→search`), **embedding**
(`train→eval`), and **LLM** (`data_prep→train→eval`) pipelines. GPU stages add
`resources: {gpus, vram_mb, est_gpu_hours}`. Shipped recipes pre-fill stages + a
provenance manifest: `retrieval-index`, `embedding-train-eval`, `llm-finetune-eval`,
`llm-eval-only`. For richer logic, hand-write a Python `Domain` (OpenSearch and
SEISMIC ship as typed reference domains). See
**[`docs/benchmark/README.md`](docs/benchmark/README.md)** and
**[`docs/benchmark/DOMAIN_API.md`](docs/benchmark/DOMAIN_API.md)**.

## Core principles (enforced by the engine)

| Principle | Meaning |
|-----------|---------|
| **Fair Comparison** | Only the treatment variable changes; the required-params manifest hard-gates the rest |
| **Memory Continuity** | Every run inherits prior context (results index + lessons) |
| **Safety First** | Resource budget + OOM guard validated before and during execution |
| **Skeptical Analysis** | Good results get more scrutiny; reproduction required for RELIABLE |
| **Honest Reporting** | Every report carries a mandatory "What Went Wrong" section |
| **Root Cause Depth** | Two fairness gates refuse non-comparable or noise-level "wins" |

## Key features

- **Two-gate experiment fairness** — *parameter identity* (frozen config, point-of-use
  effective-param capture, effective-vs-declared gate) + *measurement comparability*
  (replication, effect>noise selection, env/code/accelerator fingerprint, per-metric
  reproduction tolerances).
- **Loop-guarded tuner** — grid / refine / coordinate search that can never select a
  non-comparable trial; halts (and asks) on an ungrounded baseline or a
  non-comparable streak; auto-halts on trial / wall-clock / **GPU-hour / $cost** budgets.
- **GPU guardrails + accounting** — per-stage VRAM budget, `CUDA_VISIBLE_DEVICES`
  pinning, fail-loud VRAM-OOM, GPU-hours and $cost recorded and usable as loop budgets.
- **OOM crash-prevention (verified against the real kernel)** — the guard kills a
  runaway process at the budget ceiling *before* the kernel OOM-killer fires, and in a
  shared cgroup protects an innocent co-tenant the kernel would otherwise sacrifice.
- **ML-aware fairness** — provenance hard-gate (base_model / dataset / tokenizer /
  precision / seed / eval_suite), seed-distribution replication (a lucky seed can't
  win), accelerator fingerprint, eval-suite comparability refusal.
- **Cross-session signature cache** — deterministic prep reused; measurement always re-run.
- **Session resilience** — `run --detach` survives session death via nohup + `/loop`.
- **Reliability tags** — RELIABLE / QUALIFIED / UNRELIABLE / EXPLORATORY; citations gated.
- **Metric-agnostic core** — you name your own metrics; nothing is hard-coded.

## Validation

- **Fast suite: 192 tests**, deterministic, no external deps (`pytest -m "not happy"`).
- **Real-infra smoke: 3 tests** — a real OpenSearch cluster (Docker) + SEISMIC (`pytest -m happy`).
- **OOM fidelity: 2 opt-in tests** — real cgroup (Docker `--memory`, no swap) proving the
  guard preempts the kernel OOM-killer and protects a co-tenant (`pytest -m oom_fidelity`).
- **Full-scale tuning paths run live:** SEISMIC heap_factor **1.42×** faster within a
  recall floor (50k docs); OpenSearch force-merge 16→1 segments **1.49×** faster at
  identical recall (20k docs, real 8 GB cluster).

## Data directory

The plugin uses `$BENCHMARK_HOME` (defaults to `./benchmark_data/`):

```
benchmark_data/
  results_index.md          — single source of truth, grouped by reliability tag
  lessons.md                — accumulated lessons (append-only, read at plan time)
  risks.md                  — known fragilities and scaling limits
  runs/<run_id>/            — per-run config.yaml, results.yaml, report.md
```

Set `BENCHMARK_HOME` to customize; otherwise it defaults relative to your project root.

## Origin

Built from lessons learned running force-merge / RSS / latency benchmarks on a
138M-doc SEISMIC sparse-vector index across 3-node clusters. Every feature exists
because its absence caused a real problem — a segment-count confound that nearly
discarded a correct fix, a misaligned run that wasted hours, an invalidated run cited
as a baseline, celebrated results that hid bugs, an OOM that took down a node. See
`BENCHMARK_LESSONS_LEARNED.md`.

## License

Apache-2.0
