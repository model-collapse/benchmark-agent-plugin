# Benchmark Lessons Learned

Accumulated from running force-merge / RSS / search-latency benchmarks on the neural-sparse SEISMIC engine across 138M docs, 3-node clusters (r6i.4xlarge, 128 GB), multiple index types (float32, SQ uint8), and iterative fix cycles from May–June 2026.

---

## 1. Uncontrolled Variables Silently Invalidate Results

**What happened:** We compared an "ephemeral eviction" run (43–58 starting segments) against a baseline (32 segments). The peak RSS looked catastrophically worse (79–98 GB vs 69–71 GB). We nearly discarded the eviction approach.

**Root cause:** Segment count was the confound. More segments = more intermediate merge rounds = more time for page cache to accumulate. The eviction mechanism was correct but couldn't keep up with 2–3x more segments.

**Lesson:** Never compare runs that differ in more than the treatment variable. If you can't hold a variable constant, you must explicitly acknowledge the confound and quantify its expected impact before drawing conclusions.

---

## 2. Premature Root-Cause Attribution Wastes Days

**What happened:** When the ephemeral eviction run peaked at 79 GB, we hypothesized that `/proc/self/maps` scanning overhead was the cause (scanning thousands of memory regions every 30s). We spent time optimizing the scanner before discovering the real issue.

**Root cause:** The actual problems were: (a) 18-minute gaps between intermediate merge rounds with no eviction running, and (b) unmanaged `.cfs` compound segment files accumulating ~20 GB of resident page cache.

**Lesson:** Never attribute a root cause until you can prove it accounts for the observed magnitude. "Could this possibly add 20 GB?" — if you can't demonstrate the mechanism, keep looking.

---

## 3. Success Hides Bugs

**What happened:** The persistent eviction run completed perfectly — 59–61 GB peak, flat Phase 1 RSS, search latency unchanged. A subsequent code review found 6 bugs including a critical double-free and a buffer overflow.

**Root cause:** The happy path exercised none of the error paths. The double-free only triggers if `buildAndSaveIndex` throws after deleting the native index. The buffer overflow only triggers if a `/proc/self/maps` line exceeds 1024 bytes (rare but possible with deeply nested mount paths).

**Lesson:** A successful benchmark proves performance, not correctness. Always follow a good benchmark with adversarial code review. Ask: "What paths weren't exercised? What assumptions does the code make about inputs?"

---

## 4. Settings Amnesia Between Runs

**What happened:** Across sessions, we repeatedly lost track of:
- Cluster settings (`index_thread_qty`, merge policy)
- Node topology (IPs, SSH aliases, data paths)
- OS configuration (`vm.max_map_count`, transparent hugepages)
- Port forwarding (localhost:19200, not :9200)
- Index state (doc count, segment count, merge progress)

Each new session spent 30–60 minutes rediscovering the environment before productive work could begin.

**Lesson:** Record the full environment snapshot at every run boundary. Treat settings as part of the result — they determine reproducibility.

---

## 5. Hardware Limits Are Silent Until They Kill

**What happened:** Early float32 runs peaked at 116–118 GB on 128 GB nodes. This left only 10 GB for the OS, page cache for other files, and any background activity. One concurrent compaction or log rotation could have triggered OOM-kill with no warning.

**Root cause:** No safety margin was computed before the run. We estimated "it should fit" without doing the math.

**Lesson:** Before every run, compute: `estimated_peak + 10% safety margin < available_RAM`. If the margin is under 10%, deploy active monitoring with auto-pause capabilities. Never discover OOM by experiencing OOM.

---

## 6. "Account For Every GB" Catches Hidden Costs

**What happened:** When persistent eviction achieved 59 GB peak, we could precisely explain every GB: 17 (JVM) + 40 (CSR at 46M docs) + 4 (page cache sawtooth between eviction cycles) = 61 GB. This accounting revealed that the result was at theoretical minimum — no further optimization possible without reducing doc count or CSR size.

**Lesson:** If you cannot explain where every unit of your measured metric comes from, the analysis is incomplete. Unexplained residuals are either measurement error or hidden costs that will surprise you later.

---

## 7. Good Results Need More Scrutiny, Not Less

**What happened:** After seeing 59 GB peak, we nearly declared victory without asking:
- Is this the floor? (Yes — CSR alone is 40 GB, unavoidable)
- Does it scale? (Linear with docs: 92M docs → ~80 GB CSR → exceeds 128 GB)
- What breaks it? (If eviction thread doesn't get scheduled for 60s+ under CPU pressure, page cache re-accumulates)
- Is it robust to segment count? (Yes — 47 segments peaked lower than 32 segments from baseline)

**Lesson:** When a result exceeds expectations, the correct response is heightened suspicion, not celebration. Understand the mechanism, project to edge cases, identify fragility.

---

## 8. Per-Node Variance Reveals Asymmetric Behavior

**What happened:** Node 3 consistently showed 44 segments while Nodes 1 and 2 had 47. This was caused by background merges that ran on Node 3 before the experiment started. While the peak RSS was similar (59.9 vs 61.2 GB), the timing and eviction patterns differed.

**Lesson:** Always report per-node numbers, not averages. Variance between nodes is diagnostic information — it tells you whether the system is deterministic or if you're measuring noise.

---

## 9. Validation Benchmarks Are Mandatory, Not Optional

**What happened:** After fixing the eviction mechanism and all 6 bugs, we ran a search latency benchmark. It confirmed no regression (3ms p50 at hf=1.08, identical to prior baseline). Without this, we would have shipped a change that "probably" doesn't affect search — a claim with zero evidence.

**Lesson:** Any change to the write path / merge path must be followed by a read-path validation benchmark. "It shouldn't affect search" is a hypothesis, not a fact, until measured.

---

## 10. The Environment Is Part of the Experiment

**What happened:** We discovered that the cluster was accessible on port 19200 (not 9200), SSH required specific aliases (SEISMIC1/2/3), logs were at a non-standard path, the query format required `query_tokens` with integer keys (not `query_vector` with string keys), and `method_parameters` was the correct field name (not `search_options`).

**Lesson:** Document the environment as rigorously as the results. Future experimenters (including future agent sessions) will otherwise repeat every discovery from scratch.

---

## 11. Phase-Level Monitoring Reveals the True Bottleneck

**What happened:** Overall build time was ~5.5 hours. Without phase-level breakdown, we might have optimized the wrong phase. Actual breakdown: Stored fields merge (80 min, I/O bound) → CSR load (10 min) → buildIndex (4h, CPU bound) → saveIndex (2 min). The stored fields eviction only helps the I/O phase — it cannot reduce the 4h CPU phase.

**Lesson:** Always instrument at phase granularity. A metric that spans multiple phases hides which phase dominates and misleads optimization effort.

---

## 12. Compound File Formats Hide Their Contents

**What happened:** Lucene's `.cfs` (compound file system) format bundles multiple logical files into one physical file. We were evicting `.fdt` and `.fdx` but not `.cfs`, even though intermediate merge segments use `.cfs` as their container. The stored fields inside `.cfs` were consuming ~20 GB of page cache — invisible until we enumerated what files were actually resident.

**Lesson:** When working with systems that have bundled/compound file formats, understand the actual on-disk layout. Eviction/caching strategies that target logical file types may miss physical file types that contain the same data.

---

## Summary: The Benchmark Mindset

1. **Control everything.** One variable changes per run. Everything else is held constant or explicitly flagged as a confound.
2. **Remember everything.** Settings, topology, lessons, wins, losses — all persisted and loaded before the next run.
3. **Question everything.** Good results get more scrutiny. Bad results get systematic elimination, not guesses.
4. **Measure everything.** If you claim "X causes Y," show the measurement that proves it. Inference without evidence is fiction.
5. **Report everything.** The negative findings are more valuable than the positive ones — they prevent future wasted effort.
