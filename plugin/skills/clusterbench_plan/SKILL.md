---
name: clusterbench_plan
description: Plan a cluster-ops benchmark (OpenSearch/SEISMIC/custom) on the native ClusterBench engine with fair comparison, a required-params manifest gate, resource budgeting, and a hyperparameter tuning search that recommends a configuration. Produces a validated BenchmarkConfig + experiment script; does NOT execute.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
user-invocable: true
argument-hint: <domain> <hypothesis> — e.g. "opensearch 'force-merge to 1 segment speeds search'"
---

# ClusterBench Planner

The judgment layer for cluster-ops benchmarks built on the native ClusterBench
engine (`clusterbench_core`). Plans fair, reproducible, honest runs.

## Core Principles (non-negotiable)

```
P1 FAIR COMPARISON    — only the treatment variable changes between runs.
P2 MEMORY CONTINUITY  — load clusterbench_data/results_index.md + lessons.md first.
P3 SAFETY FIRST       — a ResourceBudget guards every run (OOM ceiling 85/92%).
P4 SKEPTICAL ANALYSIS — good speedups get MORE scrutiny (cold caches, ordering).
P5 HONEST REPORTING   — every run persists a RunResult incl. "What Went Wrong".
P6 ROOT CAUSE DEPTH   — explain the mechanism, don't just report the number.
```

## Steps

### 0. Load context
```bash
cat clusterbench_data/results_index.md 2>/dev/null
cat clusterbench_data/lessons.md 2>/dev/null
ls clusterbench_data/runs 2>/dev/null | sort -r | head
```
If none exist, this is a first run → it will be EXPLORATORY/QUALIFIED until reproduced.

### 1. Challenge the request (§Fair Comparison)
Confirm: is the treatment variable singular and clearly defined? Does it align
with prior runs? Will the result be comparable to a baseline? If not, raise an
Issue/Expected/Requested/Risk block and get rationale before proceeding.

### 2. Build a validated BenchmarkConfig
Construct a `clusterbench_core.model.BenchmarkConfig` (see the experiment modules
in `experiments/` as templates). Then run the **manifest HARD GATE**:
```python
from clusterbench_core.discipline.manifest import load_manifest, check_manifest, autofill_from_manifest
m = domain.required_params()
autofill_from_manifest(cfg, m)        # fill omitted manifest params from baseline
chk = check_manifest(cfg, m)
assert chk.ok, chk.render()           # every required param must be declared explicitly
```
Set a `ResourceBudget(total_ram_kb=..., estimated_peak_kb=...)`. If
`budget.verdict == "REJECT"`, do not proceed — shrink scale or raise RAM.

### 3. Choose the treatment + define a tuning space
Pick the hyperparameter(s) to tune and the space to search. **Prefer a knob with
a demonstrated speed effect at the target scale** — some knobs only cost quality
without buying speed (L2: query-term pruning did not move p50 at our corpus size;
force-merge did). Good speed knobs:
- OpenSearch: `forcemerge.max_num_segments`, `index.number_of_shards`.
- SEISMIC: `seismic.heap_factor`, `seismic.query_cut`, `seismic.n_postings`.
Set `treatment_variable.baseline_value` to the conservative (safe/slow) end so the
search demonstrates an improvement over the default.

### 4. Write the experiment script — a tuning SEARCH, not a single run
A benchmark deliverable must **search** the space and **recommend a configuration**
(L3). Write/adapt `experiments/<domain>_<slug>.py` with a `run(workdir, ...)` that
drives `clusterbench_core.tuning.Tuner`:
- `tuner.grid(TuneDim(name, values=[...]))` — discrete knob (e.g. segment counts).
- `tuner.refine(TuneDim(name, bounds=(lo, hi)), points, rounds)` — iterative zoom
  for a continuous knob (search + convergence).
- `tuner.coordinate([TuneDim, ...])` — joint multi-parameter descent.
Configure `primary_metric` (p50_ms / build_time_s / forcemerge_s), `quality_metric`
(recall@10) and a 1pp floor. The result exposes the trajectory, the recommended
config, and `improvement` vs the start. (`clusterbench_core.sweep.sweep` remains
the low-level single-grid primitive the grid strategy builds on.)

### 5. Present the plan for approval, then hand to `clusterbench_run`.
Report: hypothesis, treatment(s) + tuning strategy + space, baseline, resource
verdict, N manifest params checked. Do NOT execute from this skill.

## Forbidden
- NEVER present a single successful run as the result — a benchmark is a tuning
  search that recommends a configuration (L3).
- NEVER report a speedup without a warm-up pass (cold caches invert results — L1).
- NEVER adopt a knob as a "speed optimization" without confirming it moves the
  primary metric, not just the quality metric (L2).
- NEVER let a non-treatment parameter drift (preflight Phase A will block it).
- NEVER tag RELIABLE from a single run — reproduction is required.
- NEVER skip persisting a RunResult, even on failure.

See `lessons.md` for the incidents (L1–L5) behind these rules.
