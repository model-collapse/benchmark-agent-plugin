# Unified Benchmark Harness — Design Spec

**Date:** 2026-10-19
**Status:** Approved decisions, pending spec review
**Supersedes:** the two parallel skill families (`benchmark_agent`/`benchmark_run` markdown agent + `clusterbench_plan`/`clusterbench_run`/`clusterbench_domain` engine silo) in `model-collapse/benchmark-agent-plugin`.

## 1. Problem

The plugin currently ships **two complete, overlapping harnesses**:

- `benchmark_agent` / `benchmark_run` — ~1,500 lines of markdown prose, LLM-driven, executes by generating ad-hoc `nohup` bash.
- `clusterbench_*` — the same discipline (fair comparison, required-params manifest hard-gate, reliability tags, skeptical analysis + "What Went Wrong", resource budget/OOM, plan/run/analyze) **re-implemented in Python** and exposed as three more skills.

The discipline is defined **twice, in two languages**, and the two were never fused: the markdown agent can't enforce what its prose claims, the engine's rigor is locked inside a `clusterbench` silo, and cluster-deploy / resource-management are presented as "clusterbench features" rather than general harness capabilities. Users face five skills and two incompatible execution paths. This is the misalignment this spec removes.

## 2. Goals / non-goals

**Goals**
- **One** general-purpose skill, `/benchmark`, that plans, runs, tunes, analyzes, compares, and manages history for *any* experiment.
- Discipline defined **once**, in the engine; the skill is a thin reasoning layer that drives it and never re-encodes a rule it cannot enforce.
- A generic Domain that benchmarks **anything** — retrieval, embedding training/eval, LLM training/eval — through declared shell-command stages, on the full engine backbone.
- Resource management (host RAM, GPU/VRAM, cluster lifecycle, GPU-hours/$) as **engine-wide capabilities** available to every Domain.

**Non-goals**
- A research/experiment-tracking product (MLflow/W&B). This is an *experiment harness*; metrics stay domain-supplied and the core stays metric-agnostic.
- A GPU cluster scheduler/queue. We provide guardrails + accounting, not device scheduling (see §8).
- Backward-compatible skill names: this refactors an **unmerged branch**; a clean restructuring is acceptable.

## 3. Locked decisions

1. **Fusion shape:** one skill, the engine is the only execution backbone. Ad-hoc bash generation is retired; new systems become Domains (the skill can scaffold them).
2. **Generic Domain:** a first-class `CommandDomain`, generalized to an **N-stage DAG** command pipeline (§7).
3. **Resource management:** GPU **guardrails + accounting** — declare GPUs + VRAM per stage, pin via `CUDA_VISIBLE_DEVICES`, detect VRAM-OOM and fail loud, record GPU-hours and $cost as metrics and loop-guard budgets. No device scheduler/queue.
4. **Entry point:** rename the skill to `/benchmark`; detached session-resilient execution is preserved as a run **mode**.
5. **Packaging:** rename Python packages `benchmark_engine → benchmark_engine`, `benchmark_ops → benchmark_ops`, `benchmark_domains → benchmark_domains`; `docs/clusterbench/ → docs/benchmark/`.

## 4. Architecture

```
/benchmark   (ONE skill: plan · run[--detach] · tune · analyze · compare · history · status · reclassify · domain)
     │  drives — never re-implements
     ▼
benchmark_engine   — typed BenchmarkConfig · manifest hard-gate · preflight A/B/C ·
                     two fairness gates · Tuner + loop guard · signature cache ·
                     resource manager (RSS + VRAM + cluster + GPU-hours/$) ·
                     DAG scheduler · reliability tags · reproduction · one results index
     │  via the Domain protocol
     ▼
Domains   — CommandDomain (generic N-stage DAG) · OpenSearch · SEISMIC · hand-written
     │  recipes pre-fill CommandDomain + a scenario manifest
     ▼
Recipes   — retrieval-index · embedding-train-eval · llm-finetune-eval · llm-eval-only
```

**Dependency rule (strict one-way):** `skill → benchmark_domains → benchmark_ops → benchmark_engine`.

## 5. The one skill `/benchmark`

Verb-dispatched. Each verb delegates enforcement to the engine; prose covers only LLM judgment.

| Verb | LLM judgment (prose) | Engine enforces (code) |
|---|---|---|
| `plan` | hypothesis, treatment var, controls, **challenge protocol**, pick/scaffold a Domain or recipe | manifest hard-gate, typed `BenchmarkConfig`, resource budget, preflight A/B/C |
| `run [--detach]` | — | execution, per-stage caching, RSS/VRAM OOM, cluster lifecycle, fairness capture |
| `tune` | choose search space + quality floor | Tuner (grid/refine/coordinate) + **loop guard** (incl. GPU-hour/$ budget) |
| `analyze` | skeptical interpretation, "What Went Wrong" narrative | computed reliability tag, fairness verdict, reproduction check |
| `compare` | frame the finding | **comparability gates** (refuse unfair comparisons) |
| `history` / `status` / `reclassify` | — | one results index + persisted `RunResult`s |
| `domain` | design the wrapper | scaffold a Python Domain or a CommandDomain/recipe config |

**Deleted:** all five current skills. The duplicated-discipline markdown collapses to a short judgment-only skill. **Invariant:** no rule-enforcing logic lives in prose; prose that asserts a gate it cannot enforce is forbidden (that drift is what created the two silos).

## 6. The engine (`benchmark_engine`)

Unchanged in spirit from the native engine, renamed, with the resource manager and DAG scheduler generalized. Components: `engine/` (signature, on-disk `SignatureCache`, `step`/DAG, `scheduler`, `launcher` InProcess+LocalProcess subprocess, `worker`, `measure_entry`, `effective`), `model` (frozen `BenchmarkConfig` + `RunResult`), `lifecycle`, `discipline/` (manifest, preflight, reliability, analysis), `tuning` (Tuner + loop guard), `measurement`, `resources` (new, §8), `fingerprint`, `report_index`.

## 7. CommandDomain — N-stage DAG command pipeline

CommandDomain implements the `Domain` protocol by running declared shell-command **stages** that form a DAG. One abstraction covers retrieval, embedding, and LLM work.

```yaml
domain: command
recipe: llm-finetune-eval              # optional; pre-fills stages + manifest, fully overridable
stages:
  - name: data_prep
    cmd: "python prep.py --raw {raw} --out {train_data}"
    produces: [train_data]
    kind: prep                          # prep|measure  (measure = recorded, comparability-gated)
  - name: train
    cmd: "torchrun sft.py --base {base_model} --data {train_data} --lr {lr} --seed {seed} --out {ckpt}"
    needs: [data_prep]
    produces: [ckpt]
    kind: prep
    resources: {gpus: 4, vram_gb: 72, est_gpu_hours: 6}
    effective_from: {file: "{ckpt}/resolved_config.json"}   # point-of-use param echo
  - name: eval_mmlu
    cmd: "lm_eval --model {ckpt} --tasks mmlu --output {mmlu_json}"
    needs: [train]
    kind: measure
    metrics_from: {file: "{mmlu_json}", fields: [mmlu_acc]}
    resources: {gpus: 1, vram_gb: 40}
  - name: eval_gsm8k                     # fan-out: parallel sibling of eval_mmlu
    cmd: "lm_eval --model {ckpt} --tasks gsm8k --output {gsm_json}"
    needs: [train]
    kind: measure
    metrics_from: {file: "{gsm_json}", fields: [gsm8k_acc]}
    resources: {gpus: 1, vram_gb: 40}
treatment_variable: train.lr
```

**Semantics**
- **DAG:** `needs:` declares edges; independent stages may run in parallel (subject to §8/§10).
- **Artifacts** flow by name; `{name}` placeholders are resolved to concrete paths the engine allocates. Params inject into `{param}` placeholders.
- **Caching:** each `prep` stage is signature-cached on `(cmd, resolved params, upstream artifact descriptors)`; a cache hit skips re-run. `measure` stages always re-run.
- **Metrics:** `metrics_from` reads a `file:` (JSON/CSV) or `stdout:` and extracts `fields` → the metrics dict. Metric-agnostic: field names are whatever the command emits.
- **Effective params:** `effective_from` points at a resolved-config file the command writes, giving true point-of-use capture (catches an agent that silently changed e.g. precision). Falls back to declared.

**Recipes** = pre-filled `stages` + a scenario-tuned `required_params.yaml` manifest. Shipped: `retrieval-index` (build→search), `embedding-train-eval` (train→eval on MTEB/BEIR recall), `llm-finetune-eval` (data_prep→train→eval), `llm-eval-only` (eval a fixed model).

## 8. Resource management (`benchmark_engine.resources`) — engine-wide

Generalizes the host-RSS OOM guard into one resource manager used by every Domain:

- **Host RAM:** existing `ResourceBudget` + guard (SIGTERM at 85%, SIGKILL at 92% of declared).
- **GPU/VRAM:** per-stage `resources: {gpus, vram_gb}`. The launcher pins `CUDA_VISIBLE_DEVICES` to the allotted devices, polls VRAM (via `nvidia-smi`/NVML), and **fails loud on VRAM-OOM** with an attributable error rather than an opaque crash. No queue: a stage assumes its declared devices are free; parallel GPU stages must declare disjoint devices (§10).
- **Accounting:** wall-clock, GPU-hours (`Σ gpus × stage_seconds`), and `$cost` (from an optional `$/gpu-hour` rate) are recorded as first-class metrics on every `RunResult`.
- **Budgets as loop-guard limits:** the Tuner's `LoopBudget` gains `max_gpu_hours` and `max_cost`; a sweep auto-halts (reason `BUDGET_GPU_HOURS` / `BUDGET_COST`) exactly like the existing wall-clock/trial budgets.
- **Cluster lifecycle** (OpenSearch Docker, remote hosts) stays a Domain-provided capability but is surfaced through the same manager so teardown is guaranteed on failure.

## 9. Two-gate fairness, ML-aware

The existing two gates carry over; ML makes them matter more.

**Gate 1 — parameter identity.** Frozen config; effective params captured at point of use (`effective_from`); effective-vs-declared gate + field diff; fail-loud; provenance. Per-recipe **manifest hard-gates ML provenance** that silently ruins comparisons: `base_model` (hash), `dataset` (version/hash), `tokenizer`, `precision`, `seed`, `eval_suite` + harness version. A silent precision drop or eval-set shrink to "fit"/"pass" trips the gate.

**Gate 2 — measurement comparability.** R-replication; `is_real_improvement` (MDE + 3·SE). For stochastic training, **replication is across seeds** and improvement compares seed distributions, not single runs. Comparability **refuses** to compare checkpoints evaluated on different eval-suite versions/sizes. The env/code fingerprint extends to CUDA/driver/accelerator-lib versions and model/data/harness identity. Data-integrity `passed` still required.

**Loop guard** unchanged in structure; now also halts on GPU-hour/$ budgets and still can never select a non-comparable trial.

## 10. DAG scheduler policy

Reconciles DAG parallelism with Gate 2's attributability requirement:

- **`prep`/`train` stages** run in parallel when their `needs` are satisfied and their declared devices are disjoint.
- **`measure` stages serialize by default** — timing/throughput/RSS/VRAM must be attributable to be comparable. Opt-in `parallel: true` is allowed only for a `measure` stage that records **no** performance metric (accuracy-only).
- With no GPU queue, two ready GPU stages with overlapping device requests **serialize** rather than contend; disjoint requests parallelize.

## 11. Persistence — one layout, one index

Collapse the two schemas into one. `$BENCHMARK_HOME` (default `./benchmark_data`); the engine's `report_index` (`update_index` + `load_runs`) is the single source of truth; each run is a typed `RunResult` persisted as `runs/<run_id>/{config.yaml,results.yaml,report.md}`. `lessons.md` + `risks.md` remain the append-only agent memory the skill reads at `plan` time (the "memory continuity" principle) — read by the skill, not a parallel result store.

## 12. Packaging / migration / deletions

- Rename packages (§3.5); update all imports, `experiments/`, tests, `pyproject.toml`, docs.
- `plugin/skills/` ends with exactly one skill: `benchmark/`. Delete `benchmark_agent`, `benchmark_run`, `clusterbench_plan`, `clusterbench_run`, `clusterbench_domain`. Update `.claude-plugin/marketplace.json` (name/description), `clusterbench_awareness` hook → `benchmark_awareness`.
- Move `docs/clusterbench/* → docs/benchmark/*`; refresh READMEs (root + `docs/benchmark/README.md`) to describe one skill + the pipeline/recipes/GPU story.
- No external-user migration: unmerged branch.

## 13. Testing strategy (TDD, full coverage of new paths)

Keep the existing 137. Add:
- **Pipeline:** DAG construction + topo order; artifact-name resolution + flow; per-stage signature caching (hit skips re-run; measure always re-runs); `metrics_from` stdout **and** file (JSON/CSV); `effective_from` point-of-use capture + effective-vs-declared diff.
- **Resources:** VRAM accounting + VRAM-OOM fail-loud (mock NVML/`nvidia-smi`); device pinning sets `CUDA_VISIBLE_DEVICES`; GPU-hours/$ recorded; `LoopBudget` halts on `max_gpu_hours`/`max_cost`.
- **ML fairness:** seed-replication path; comparability refusal across eval-suite version/size; caught silent precision/eval-size change via `effective_from`; fingerprint includes accelerator libs.
- **Scheduler:** parallel prep with disjoint devices; serialized measurement; opt-in parallel accuracy-only measure.
- **Recipes:** each recipe's manifest hard-gate blocks a config missing its provenance params.
- **Skill/detached:** `run --detach` writes signal files and resumes monitoring; one-skill verb dispatch.

## 14. Phasing (for the implementation plan)

- **Phase 1 — unification, no new scenarios:** rename packages; collapse to one `/benchmark` skill; one persistence layout; CommandDomain as N-stage DAG (CPU/host-RSS only); stdout+file metrics; scheduler policy; migrate OpenSearch/SEISMIC onto it; delete old skills. Ships a coherent one-skill harness.
- **Phase 2 — ML scenarios:** `benchmark_engine.resources` GPU guardrails + accounting; ML-aware fairness (seed replication, provenance manifest, accelerator fingerprint); recipes (`embedding-train-eval`, `llm-finetune-eval`, `llm-eval-only`); GPU-hour/$ loop budgets.

Each phase is independently testable and leaves the harness working.

## 15. Risks / open questions

- **VRAM polling portability:** NVML preferred, `nvidia-smi` fallback; non-NVIDIA accelerators out of scope this version (document the limitation).
- **Training nondeterminism vs reproduction tolerances:** seed-distribution comparison must set defensible default tolerances per metric; recipes ship sensible defaults, overridable.
- **DAG config surface:** more expressive = more misconfiguration; the manifest gate + preflight must validate the DAG (no cycles, all `needs`/artifacts resolvable) before any stage runs.
- **Rename churn:** large mechanical diff; done as the first plan task so the rest builds on stable names.
