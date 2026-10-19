---
name: clusterbench_run
description: Execute an approved ClusterBench plan — run the tuning search via the native ClusterBench engine (locally or on a cluster), manage the OpenSearch Docker cluster lifecycle, persist results, and hand back to analysis. Never makes analytical decisions.
allowed-tools: Bash, Read, Write, Edit
user-invocable: true
argument-hint: <experiment_module> [workdir] — e.g. "experiments.opensearch_splade ./clusterbench_data/os"
---

# ClusterBench Runner

The execution/watchdog layer. Answers only: is it running, done, or in trouble.
All judgment belongs to `clusterbench_plan`.

## Preconditions
- An approved experiment script exists under `experiments/`.
- The env is active: `conda activate clusterbench` (opensearch-py,
  pyseismic-lsr installed; the engine itself has no third-party runtime deps).

## Execute

### Library / SEISMIC domains (no cluster)
```bash
python -m experiments.seismic_splade ./clusterbench_data/seismic
```
Each lifecycle runs through the engine; the deterministic index build is cached
by signature and reused across the sweep, the measurement is always re-run.

### OpenSearch domain (Docker cluster)
The experiment's `__main__` starts an `OpenSearchCluster` (disposable container,
security disabled, free port), runs the sweep, and tears the cluster down in a
`finally`:
```bash
python -m experiments.opensearch_splade ./clusterbench_data/opensearch
```
The container is OOM-guarded by the engine's `ResourceBudget` (SIGTERM at 85%,
SIGKILL at 92% of declared RAM). Confirm teardown with `docker ps`.

### Caching and subprocess isolation (native engine)
Signature-caching is automatic: `run_lifecycle(cfg, domain, workdir=...)` content-
hashes the deterministic prep (index build) and reuses it across trials with an
identical build-key — measurement is always re-run. For attributable per-trial
memory, pass `measure_in_subprocess=True`, which runs the measurement under the
OOM-guarded `LocalProcessLauncher` so RSS is isolated from the parent. Multi-step
DAGs use `benchmark_engine.engine.scheduler` (parallel prep, serialized
measurement) over the on-disk `SignatureCache`.

## Preflight is enforced by the engine
Before any measurement the lifecycle runs: budget check → manifest gate →
Phase A baseline diff → Phase B apply_config → Phase C live verify. A failure
persists an `ABORTED_PREFLIGHT`/`ABORTED_GUARDRAIL` RunResult and stops.

## On completion
Each run writes `clusterbench_data/runs/<run_id>/{config.yaml,results.yaml,report.md}`.
Report one line per tuning trial (treatment=value: p50, recall, status, tag) and
the recommended config + improvement. Then hand to analysis / reclassification.

## Safety rules
```
NEVER launch without an approved plan or without a ResourceBudget.
NEVER modify the config/scripts after launch.
NEVER make analytical conclusions — that is clusterbench_plan's job.
ALWAYS ensure the Docker cluster is torn down (finally:), even on failure.
ALWAYS write a RunResult even when a run aborts.
```
