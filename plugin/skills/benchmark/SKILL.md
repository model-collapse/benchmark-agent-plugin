---
name: benchmark
description: One general-purpose experiment harness. Plans, runs, tunes, analyzes, compares, and tracks benchmarks of any system (database, index, retriever, embedding/LLM pipeline) on the native benchmark_engine with fair comparison, a required-params manifest gate, resource/OOM guardrails, two experiment-fairness gates, a loop-guarded tuner, cross-session caching, and honest persisted reports.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
user-invocable: true
argument-hint: <verb> [args] — verbs: plan | run [--detach] | tune | analyze | compare | history | status | reclassify | domain
---

# Benchmark

The single entry point for benchmarking. This skill is the *judgment* layer — it
reasons about hypotheses, treatments, and results. It does **not** re-implement
any rule: every gate, cache, budget, and fairness check is enforced by the
`benchmark_engine` code the verbs call. Prose here that claims a guarantee it
cannot enforce is a bug; put the guarantee in the engine.

The engine is metric-agnostic. The science (datasets, models, metrics) is yours,
supplied through a `Domain`: either the generic **CommandDomain** (declare shell
`stages` — a DAG of prep/measure commands — in YAML; no Python) or a hand-written
Python `Domain`. Recipes pre-fill a CommandDomain + its fairness manifest for a
scenario (`retrieval-index`, and — later — embedding/LLM training+eval).

## Core principles (enforced by the engine, not by this prose)

```
P1 FAIR COMPARISON    — only the treatment variable changes; the manifest HARD-GATES the rest.
P2 MEMORY CONTINUITY  — every run inherits prior context (results index + lessons).
P3 SAFETY FIRST       — resource budget + OOM guard validated before and during execution.
P4 SKEPTICAL ANALYSIS — good results get MORE scrutiny; reproduction required for RELIABLE.
P5 HONEST REPORTING   — every report carries a mandatory "What Went Wrong" section.
P6 ROOT CAUSE DEPTH   — trace causation; two fairness gates refuse non-comparable wins.
```

## Verbs

Each verb loads prior context first (`benchmark_engine.report_index.load_runs` +
`$BENCHMARK_HOME/lessons.md`), then calls the engine.

### `plan <domain|recipe> <hypothesis>`
Reason about the hypothesis, the treatment variable, and controlled variables, and
**challenge** the request if it is misaligned with prior runs (judgment). Pick a
Domain or scaffold one (`domain` verb). Produce a validated typed `BenchmarkConfig`.
The engine runs the **manifest hard-gate**, resource budget, and preflight A/B/C —
a missing required param or an unexpected baseline diff blocks here. Does NOT execute.

### `run [--detach] <experiment>`
Execute via `benchmark_engine.lifecycle.run_lifecycle` (or a `Tuner` for a search).
Synchronous for short runs. `--detach` launches the engine under `nohup` so a long
or cluster run survives session death, drops `.running`/`.complete`/`.failed` signal
files, monitors via `/loop`, and triggers `analyze` on completion. Cluster/GPU
lifecycle and the OOM guard are engine services — never hand-roll them here.

### `tune <experiment>`
Run a hyperparameter search (`benchmark_engine.tuning.Tuner`: grid / refine /
coordinate) with the **loop guard**: it never selects a non-comparable trial and
halts (asking a human) on an ungrounded baseline or a non-comparable streak. Choose
the search space and quality floor (judgment); the engine runs the search.

### `analyze <run_id>`
Interpret a completed run's persisted `RunResult` skeptically and write the
"What Went Wrong" narrative (judgment). The reliability tag, fairness verdict, and
reproduction check are already computed by the engine — read them, don't recompute.

### `compare <run_id_1> <run_id_2>`
Frame the finding (judgment). The engine's comparability gates decide whether the
two runs are even fair to compare; if they are not, say so and stop.

### `history [domain]` / `status` / `reclassify <run_id> <tag> <reason>`
Thin reads/writes over the single results index (`report_index`) and the persisted
`RunResult`s. One index is the source of truth.

### `domain <name|--recipe <recipe>>`
Scaffold a new benchmark target: a CommandDomain stages config (+ its required-params
manifest) from a recipe, or a hand-written Python `Domain`. See the Domain API docs.

## Safety rules

```
NEVER execute without a validated plan and a ResourceBudget.
NEVER mutate a config after freeze — the engine raises; a changed config is a new run.
NEVER claim "no regression" / "as expected" without the evidence the engine recorded.
ALWAYS tear down clusters in finally; ALWAYS persist a RunResult, even on abort.
```
