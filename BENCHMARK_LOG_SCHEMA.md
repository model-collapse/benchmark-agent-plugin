# Benchmark Log Schema

Standard directory structure and file schema for benchmark experiment management. Designed so an LLM agent can reliably reconstruct the full context of any prior run — including every parameter that was set, every parameter that was left at default, and every dependency on prior runs.

## Design Problem

LLMs lose context across sessions. Prose-format run records allow critical parameters to go unmentioned (because the human "knew" them). When the agent starts a new run, it reads prior records but cannot distinguish "parameter X was deliberately set to Y" from "parameter X was never considered." This leads to silent misconfiguration.

**Solution:** A structured schema where every relevant parameter is explicitly declared (set or default), dependencies are machine-parseable, and lessons are coupled to the runs that produced them.

### The "invisible default" problem (v1.1 addition)

The original schema caught most divergences via baseline-config.yaml diffing. But it had a coverage gap: **if a parameter was never listed in any prior config.yaml (because all prior runs left it at its system default), the alignment check could not detect when a new run silently changed it.**

This bit us in the 2026-06-11 eviction-merge-slowdown incident. `index.merge.scheduler.max_thread_count` was never listed in any prior config.yaml — every prior run had inherited the cluster default of 4. A subsequent run set it to 16 (along with `max_merge_count=32` and `auto_throttle=false`), interacted catastrophically with the persistent-eviction patch, and produced a 14× stored-fields merge slowdown. The agent's parameter alignment check did not catch the change because the parameter wasn't in any baseline.

**Fix:** Domain Required-Parameters Manifests (`domains/<domain>/required_params.yaml`). The manifest is a per-domain checklist of parameters that MUST be declared in every config.yaml — independent of whether prior runs declared them. Entries are added when forensic investigation finds a parameter that "ever surprised us." The manifest grows monotonically.

---

## Directory Structure

```
benchmark_data/
├── INDEX.md                         # Global run index (summary table)
├── lessons.md                       # Global lessons (accumulated across all runs)
├── risks.md                         # Known fragilities and scaling limits
├── settings/                        # Cluster/environment documentation
│   └── seismic_cluster.md
│
├── domains/                         # Per-domain required-parameters manifests
│   └── <domain>/
│       └── required_params.yaml     # Hard-gate checklist for runs in this domain
│
└── runs/
    └── <run_id>/                    # One folder per run (YYYY-MM-DD-<slug>)
        ├── README.md                # High-level: motivation, hypothesis, key decisions
        ├── config.yaml              # Machine-readable: ALL parameters (set + defaults)
        ├── results.yaml             # Machine-readable: outcomes, metrics, verdict
        ├── lessons.yaml             # Per-run lessons: applied, discovered, remaining
        ├── scripts/                 # Execution scripts + change log
        │   ├── CHANGELOG.md         # What changed from the template/previous run
        │   ├── execute.sh           # Main execution script
        │   ├── guardrail.sh         # Hard ceiling protection
        │   ├── monitor.sh           # Resource monitoring
        │   ├── check.sh             # Loop status reporter
        │   └── reproduce_deps.sh    # Script to recreate prerequisite data if missing
        └── artifacts/               # Side artifacts: config files, data files, logs
            ├── cluster_settings.json    # Snapshot of cluster settings at run time
            ├── index_settings.json      # Snapshot of index settings at run time
            ├── jvm_options.txt          # JVM config snapshot
            ├── monitor.csv              # Time-series RSS/metrics data
            ├── events.log               # Event log (phase transitions, alerts)
            └── <other run-specific files>
```

---

## File Schemas

### 1. `config.yaml` — The Single Source of Truth for Parameters

This file is the **most critical**. Every parameter that affects the run outcome MUST appear here, explicitly marked as either `set` (deliberately configured) or `default` (left at system default). A missing parameter is a bug in the schema, not a "it was obvious."

```yaml
schema_version: "1.0"
run_id: "2026-06-10-single-node-138m"
created: "2026-06-10T14:30:00Z"
agent_version: "benchmark-agent@1.2.0"

# --- Hypothesis & Treatment ---
hypothesis: "Single-node 138M eliminates cross-node overhead, improving build time"
treatment_variable:
  name: "shard_count"
  value: 1
  baseline_value: 3
  baseline_run: "2026-06-08-persistent-eviction-cfs"

# --- Hardware ---
hardware:
  nodes: ["SEISMIC1"]
  instance_type: "r6i.4xlarge"
  ram_gb: 128
  vcpus: 16
  storage_type: "gp3"
  storage_iops: 3000
  storage_throughput_mbps: 125

# --- Cluster Settings ---
# EVERY cluster setting that matters. Mark source: "set" | "default" | "inherited"
cluster_settings:
  index_thread_qty:
    value: 32
    source: "set"
    command: 'PUT /_cluster/settings {"persistent":{"plugins.neural_search.sparse.algo_param.index_thread_qty":32}}'
    note: "Critical: default is 1, which takes 50+ hours"
  search_thread_qty:
    value: 8
    source: "default"
    note: "Not explicitly set — using system default"
  circuit_breaker_limit:
    value: "95%"
    source: "set"
    command: 'PUT /_cluster/settings {"transient":{"plugins.neural_search.circuit_breaker.limit":"95%"}}'

# --- Index Settings ---
index_settings:
  index_name: "bench-single-138m"
  shards:
    value: 1
    source: "set"
  replicas:
    value: 0
    source: "set"
  refresh_interval:
    value: "-1"
    source: "set"
    note: "Disabled during ingestion for throughput"
  translog_flush_threshold:
    value: "10gb"
    source: "set"
  translog_durability:
    value: "async"
    source: "set"
  codec:
    value: "SparseNativeCodec"
    source: "set"
  quantization:
    value: "sq_uint8"
    source: "set"

# --- Algorithm Parameters ---
algorithm:
  name: "seismic"
  engine: "cpp-native"
  parameters:
    approximate_threshold:
      value: 9000000
      source: "set"
    cluster_ratio:
      value: 0.1
      source: "set"
    summary_prune_ratio:
      value: 0.4
      source: "set"
    heap_factor:
      value: 1.08
      source: "set"
      note: "Search-time parameter"
    top_n:
      value: 3
      source: "set"
      note: "Search-time parameter"
    quantization_ceiling_search:
      value: 4.0
      source: "set"
      note: "IMPORTANT: Must be 4.0 for recall parity with java-legacy. Default is 3.0 which costs 2-3% recall."

# --- JVM Settings ---
jvm:
  heap_min: "16g"
  heap_max: "16g"
  max_direct_memory: "4g"
  gc: "G1GC"

# --- OS Settings ---
os:
  vm_max_map_count: 262144
  vm_swappiness: 1
  transparent_hugepages: "madvise"

# --- Dataset ---
dataset:
  name: "MSMarco V2 SPLADE"
  total_docs: 138000000
  format: "CSR (int64 indptr, int32 indices, float32 data)"
  path_on_node: "/home/ubuntu/dataset/merged_passages.csr"
  avg_nnz_per_doc: 127
  vocabulary_size: 65536

# --- Ingestion Settings ---
ingestion:
  batch_size: 10000
  send_threads: 32
  serialization_workers: 8
  source_field: "sparse_embedding"
  id_scheme: "sequential_0_based"

# --- Resource Budget (computed at plan time) ---
resource_budget:
  estimated_peak_rss_gb: 120
  available_capacity_gb: 112  # 128 - 16 (heap)
  headroom_gb: -8             # NEGATIVE = unsafe
  verdict: "ABORT"
  hard_ceiling_gb: 109        # 85% of 128
  warn_ceiling_gb: 96         # 75% of 128
  formula: "CSR(138M × 127 avg_nnz × 8 bytes) + JVM(16G) + page_cache(4G) + overhead"

# --- Controlled Variables (must match baseline) ---
controlled_variables:
  - name: "quantization"
    expected: "sq_uint8"
    tolerance: "exact"
    verify: "GET /_cat/indices?v (check codec)"
  - name: "heap_factor"
    expected: 1.08
    tolerance: "exact"
    verify: "query parameter"
  - name: "top_n"
    expected: 3
    tolerance: "exact"
    verify: "query parameter"
  - name: "index_thread_qty"
    expected: 32
    tolerance: "exact"
    verify: "GET /_cluster/settings"
  - name: "quantization_ceiling_search"
    expected: 4.0
    tolerance: "exact"
    verify: "GET /_cluster/settings"
```

**Rule:** If a parameter appeared in ANY prior run's config.yaml, it MUST appear in this run's config.yaml too — even if unchanged. The agent diffs config.yaml files between runs to detect silent changes.

### 2. `README.md` — Human-Readable Context

```markdown
# Run: 2026-06-10-single-node-138m

## Motivation
Test whether concentrating all 138M docs on a single node (eliminating cross-node
communication and shard-level overhead) improves total build time and search latency.

## Key Decisions
- Single shard on SEISMIC1 only (vs 3 shards across 3 nodes in baseline)
- Same quantization (SQ uint8) and algorithm params as baseline
- 16GB heap (same as baseline per-node)

## Dependency on Prior Runs
| Dependency | Run ID | What's needed | Status check |
|-----------|--------|---------------|--------------|
| Baseline comparison | 2026-06-08-persistent-eviction-cfs | Completed results for comparison | Check `benchmark_data/runs/2026-06-08-persistent-eviction-cfs/results.yaml` exists |
| Dataset | N/A (raw CSR file) | 138M docs in CSR format on SEISMIC1 | `ssh SEISMIC1 'ls -l /home/ubuntu/dataset/merged_passages.csr'` |

### Data Status Verification
Before running, verify:
```bash
# Dataset present and correct size (~72 GB)
ssh SEISMIC1 "stat --printf='%s' /home/ubuntu/dataset/merged_passages.csr"
# Expected: approximately 77309411352 bytes

# No leftover index from prior runs
curl -s http://localhost:19200/bench-single-138m 2>/dev/null | grep -c error
# Expected: 1 (index doesn't exist yet)

# Node is clean (no running OpenSearch)
ssh SEISMIC1 "pgrep -f opensearch" 
# Expected: no output (nothing running)
```

### Reproduce Dependencies
If the dataset is missing from SEISMIC1, run:
```bash
bash scripts/reproduce_deps.sh
```
This copies the CSR file from the dev box to the node.

## Lessons Applied from Prior Runs
- [L2] Set index_thread_qty=32 explicitly (default=1 takes 50+ hours)
- [L5] Peak RSS = CSR + .nsparse overlap — accounted for in resource budget
- [L6] Will run validation benchmark (search latency) after build
- [L12] Monitor .cfs file behavior — ensure native files inside compound segments

## Lessons/Issues Still Open
- [ ] int32 overflow risk at 138M docs: 138M × 127 = 17.5B NNZ (safe for int64 offset_t, but verify)
- [ ] glibc arena retention: will release_build_memory() work correctly with 3× the data?
- [ ] Single-node has no failover — if node dies, all work is lost

## Outcome
<!-- Filled after run completes -->
```

### 3. `results.yaml` — Machine-Readable Outcomes

```yaml
schema_version: "1.0"
run_id: "2026-06-10-single-node-138m"
completed: "2026-06-10T22:15:00Z"  # or null if not completed
status: "ABORTED_PREFLIGHT"  # COMPLETED | FAILED | ABORTED_PREFLIGHT | ABORTED_GUARDRAIL | IN_PROGRESS

reliability_tag: "N/A"  # RELIABLE | QUALIFIED | UNRELIABLE | EXPLORATORY | N/A (if never ran)
reliability_reason: "Rejected at preflight — estimated peak exceeds hard ceiling"

# --- Abort/Failure Info (if applicable) ---
abort:
  phase: "preflight"
  reason: "estimated_peak_rss (120 GB) > hard_ceiling (109 GB)"
  recommendation: "Use 3 shards across 3 nodes, or upgrade to r6i.8xlarge (256 GB)"

# --- Metrics (if run completed) ---
metrics:
  force_merge:
    total_duration_s: null
    phases:
      lucene_merge_s: null
      batch_add_s: null
      build_index_s: null
      save_index_s: null
    peak_rss_gb: null
    settled_rss_gb: null
  search:
    p50_ms: null
    p95_ms: null
    p99_ms: null
    recall_at_10: null
    queries_run: null
  index:
    final_size_gb: null
    segment_count: null
    doc_count: null

# --- Comparison to Baseline ---
comparison:
  baseline_run: "2026-06-08-persistent-eviction-cfs"
  fair: false
  reason: "Run did not complete — no metrics to compare"
  deviations:
    - parameter: "shard_count"
      baseline: 3
      this_run: 1
      impact: "Treatment variable (expected difference)"
    - parameter: "total_docs_per_shard"
      baseline: 46000000
      this_run: 138000000
      impact: "Confound — 3× data per shard changes memory, build time, and potentially recall"
```

### 4. `lessons.yaml` — Per-Run Lesson Tracking

```yaml
schema_version: "1.0"
run_id: "2026-06-10-single-node-138m"

# Lessons from prior runs that were APPLIED in this run
applied:
  - id: "L2"
    title: "OMP thread count defaults to 1"
    action_taken: "Set index_thread_qty=32 in cluster settings"
    verified: true
    verify_command: "GET /_cluster/settings"
  - id: "L5"
    title: "Peak RSS from CSR + .nsparse overlap"
    action_taken: "Computed resource budget accounting for overlap"
    verified: true
    verify_command: "resource_budget.estimated_peak_rss_gb in config.yaml"
  - id: "L12"
    title: "Compound file format contains native files"
    action_taken: "Will verify .nsparse accessible after merge"
    verified: false
    note: "Cannot verify until merge completes"

# Lessons DISCOVERED during this run
discovered:
  - id: "L13"  # Will be added to global lessons.md
    title: "138M docs on single 128GB node exceeds capacity"
    finding: "CSR alone requires ~120GB at 138M docs. Cannot fit on r6i.4xlarge."
    rule: "Maximum docs per shard on 128GB = ~58M (SQ uint8). For 138M, need 3+ shards."
    source: "preflight resource budget calculation"

# Lessons/Issues that REMAIN OPEN after this run
remaining:
  - id: "L3"
    title: "int32 overflow at scale"
    status: "untested"
    note: "138M × 127 = 17.5B — within int64 but never tested at this scale"
  - id: "L7"
    title: "glibc arena retention"
    status: "untested"
    note: "Unknown behavior with 3× data volume"
```

### 5. `scripts/CHANGELOG.md` — What Changed from Template/Prior Run

```markdown
# Script Changes: 2026-06-10-single-node-138m

## Base
Scripts derived from: `2026-06-08-persistent-eviction-cfs`

## Changes

### execute.sh
- Changed: `number_of_shards` from 3 to 1
- Changed: target nodes from [SEISMIC1, SEISMIC2, SEISMIC3] to [SEISMIC1]
- Changed: index name from `bench-ingest-local` to `bench-single-138m`
- Changed: discovery mode to `single-node`
- Removed: cross-node ingestion dispatch (all data to one node)

### guardrail.sh
- Changed: threshold calc uses single-node total (128 GB) not per-node
- Same: 85% hard ceiling, 75% warn, 92% emergency

### monitor.sh
- Changed: only monitors SEISMIC1 (removed SEISMIC2, SEISMIC3)
- Same: 5s poll interval, CSV format

### reproduce_deps.sh
- NEW: copies dataset CSR to SEISMIC1 if missing
```

### 6. `scripts/reproduce_deps.sh` — Recreate Prerequisites

```bash
#!/bin/bash
# Reproduce prerequisite data for run 2026-06-10-single-node-138m
set -euo pipefail

echo "=== Checking and reproducing dependencies ==="

# Dependency 1: Dataset on SEISMIC1
echo "[1/1] Checking dataset on SEISMIC1..."
if ssh SEISMIC1 "test -f /home/ubuntu/dataset/merged_passages.csr"; then
  SIZE=$(ssh SEISMIC1 "stat --printf='%s' /home/ubuntu/dataset/merged_passages.csr")
  if [ "$SIZE" -gt 70000000000 ]; then
    echo "  OK: Dataset present ($((SIZE/1073741824)) GB)"
  else
    echo "  ERROR: Dataset too small ($SIZE bytes). Re-copying..."
    scp /home/ubuntu/bitq-code/cpp-sparse-ann/Datasets/msmarco_v2_splade/merged_passages.csr SEISMIC1:/home/ubuntu/dataset/merged_passages.csr
  fi
else
  echo "  Missing. Copying dataset (~72 GB, will take ~10 minutes)..."
  ssh SEISMIC1 "mkdir -p /home/ubuntu/dataset"
  scp /home/ubuntu/bitq-code/cpp-sparse-ann/Datasets/msmarco_v2_splade/merged_passages.csr SEISMIC1:/home/ubuntu/dataset/merged_passages.csr
fi

echo "=== All dependencies satisfied ==="
```

---

## Global Index File: `INDEX.md`

```markdown
# Benchmark Run Index

## Active Baselines (RELIABLE)

| Run ID | Date | Type | Shard/Node | Key Result | Config Hash |
|--------|------|------|-----------|------------|-------------|
| 2026-06-08-persistent-eviction-cfs | 2026-06-08 | force-merge-rss | 3s/3n | 59-61 GB peak | a3f2c1 |
| 2026-06-08-search-latency | 2026-06-08 | search-latency | 3s/3n | 3ms p50 | a3f2c1 |

## Qualified

| Run ID | Date | Type | Qualification | Config Hash |
|--------|------|------|--------------|-------------|
| 2026-05-30-sq-uint8-baseline | 2026-05-30 | force-merge-rss | Pre-eviction-fix | b7d4e2 |

## Invalidated

| Run ID | Date | Reason |
|--------|------|--------|
| 2026-05-28-first-attempt | 2026-05-28 | Uncontrolled: thread_qty=1 (not set) |

## Aborted

| Run ID | Date | Phase | Reason |
|--------|------|-------|--------|
| 2026-06-10-single-node-138m | 2026-06-10 | preflight | RSS exceeds capacity |
```

The `Config Hash` column is a short hash of the `config.yaml` contents (excluding run_id and timestamps). Two runs with the same config hash have identical parameters — useful for detecting accidental duplication or confirming reproducibility.

---

## Agent Behavior with This Schema

### When Planning a New Run

1. List all `runs/*/config.yaml` files
2. Load the most recent RELIABLE run's `config.yaml`
3. For EVERY parameter in that file:
   - If unchanged: copy verbatim to new config.yaml (source: "inherited")
   - If changed: mark as treatment variable or justify the change
   - If missing from new plan: **ERROR** — parameter regression detected
4. Diff the two config.yaml files → produces `scripts/CHANGELOG.md` automatically

### When a Parameter Is Missing

If the baseline `config.yaml` has a parameter that the user's request doesn't mention:

```
PARAMETER ALIGNMENT CHECK:

The baseline run (2026-06-08-persistent-eviction-cfs) set:
  quantization_ceiling_search: 4.0

Your request does not mention this parameter.
  - If I leave it at default (3.0), recall will drop 2-3% vs baseline.
  - If I set it to 4.0, results are comparable.

Setting to 4.0 to maintain comparability with baseline.
If you intend to test the effect of this parameter, make it the treatment variable.
```

### When Checking Dependencies

Before execution, the agent reads `README.md` dependencies table and runs each status check command. If any fails:

```
DEPENDENCY CHECK FAILED:

  Dependency: Dataset on SEISMIC1
  Check: ssh SEISMIC1 'ls -l /home/ubuntu/dataset/merged_passages.csr'
  Result: No such file

  Reproduction available: scripts/reproduce_deps.sh
  Estimated time: ~10 minutes (72 GB copy)

  Shall I run the reproduction script?
```

---

## Migration from Current Format

Current `benchmark_data/runs/run_*.md` files remain valid but are "legacy format." The agent can read both. New runs MUST use the structured format. Over time, the agent can backfill `config.yaml` for important legacy runs by extracting parameters from prose.

---

## Anti-Patterns This Schema Prevents

| Problem | How Schema Prevents It |
|---------|----------------------|
| "Forgot to set index_thread_qty" | config.yaml requires ALL params from baseline; missing = error |
| "Didn't realize quantization_ceiling changed" | Explicit `source: "default"` forces acknowledgment |
| "Can't reproduce — data was deleted" | reproduce_deps.sh + README.md status checks |
| "Which lessons were actually applied?" | lessons.yaml `applied` section with verify_command |
| "Was this run comparable to baseline?" | results.yaml `comparison.fair` + deviations list |
| "What changed between runs?" | scripts/CHANGELOG.md + config.yaml diff |
| "Prior run's context lost across sessions" | All context in structured files, not conversation memory |
