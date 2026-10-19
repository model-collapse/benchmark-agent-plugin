# Task: Functional Happy-Path Test of the ClusterBench Skill

You are testing **ClusterBench**, a cluster-ops benchmarking framework + Claude Code
plugin. This brief is self-contained — do **not** rely on any prior conversation.
Your job is to verify the skill works end-to-end on the happy path and report a
clear PASS/FAIL with evidence.

> Be skeptical and honest (that's the whole point of this tool): run the commands,
> read the real output, and report what actually happened — including anything
> that didn't. Do not claim success without the evidence below.

---

## 0. What ClusterBench is (1 paragraph)

An engine (`benchmark_engine`) — a native, self-contained Apache-2.0 engine — that runs benchmarks
through a disciplined lifecycle (resource budget → required-params manifest gate →
3-phase preflight → cacheable prep → guarded measurement → functional validation →
reliability tagging → persisted report), plus a **hyperparameter Tuner**
(grid/refine/coordinate). Two reference domains run **SPLADE sparse-retrieval**
speed benchmarks: **OpenSearch** (Dockerized, `rank_features` field, force-merge)
and **SEISMIC** (`pyseismic-lsr`). The Claude Code plugin lives in `plugin/`
(skills: `clusterbench_plan`, `clusterbench_run`, `clusterbench_domain`).

Repo: `/home/ubuntu/auto-exp/clusterbench`

---

## 1. Environment preconditions

Run everything inside the project's conda env:

```bash
source /home/ubuntu/miniconda3/etc/profile.d/conda.sh
conda activate clusterbench
cd /home/ubuntu/auto-exp/clusterbench
```

Verify the toolchain is present (all four must succeed):

```bash
python -c "import opensearchpy, seismic, yaml; print('deps OK')"
python -c "import seismic; print('seismic U30 =', seismic.get_seismic_string())"   # expect 'U30'
docker info >/dev/null 2>&1 && echo "docker OK"                                     # needed for OpenSearch
pip install -e . -q && echo "editable install OK"
```

If a dependency is missing, see **Troubleshooting** at the bottom before continuing.

---

## 2. Part A — Automated test suite (ground truth)

```bash
# fast suite (native engine, discipline, tuning, fairness, hook) — must be all green
# includes the engine-integration tests in tests/engine/ that spawn a worker subprocess
python -m pytest tests/ -q -m "not happy"
# happy paths (real OpenSearch via Docker + real SEISMIC) — must be all green
python -m pytest tests/ -q -m happy
```

**Expected:** fast suite 134 passed; happy = 3 passed. Zero failures. (First
OpenSearch happy test boots a container; allow ~1–2 min.)

---

## 3. Part B — Happy path (a): SPLADE-v3 on OpenSearch, tune force-merge

```bash
python -m experiments.opensearch_splade /tmp/cb_test/opensearch
```

This boots a disposable OpenSearch container, ingests a SPLADE `rank_features`
index across refresh cycles, then **tunes `forcemerge.max_num_segments`** over a
grid, picking the fastest point within a 1 percentage-point recall floor.

**Expected output shape** (numbers are hardware-dependent; the *trends* must hold):
- A `Tuning [grid] optimize p50_ms` trajectory with 4 trials (segments 16, 8, 4, 1).
- `recall@10` ~equal across all trials (force-merge doesn't change results).
- p50 **decreases** as segments decrease; recommended `max_num_segments=1`.
- A line like `RECOMMENDED: max_num_segments=1 ... improvement=~1.5–3.9x vs baseline`.
- The container is gone afterwards (teardown in `finally`).

---

## 4. Part C — Happy path (b): SPLADE-v2 on SEISMIC, tune heap_factor

```bash
python -m experiments.seismic_splade /tmp/cb_test/seismic
```

Builds a SEISMIC index **once** (reused across the search), then **iteratively
refines `seismic.heap_factor`** (coarse grid → zoom) to maximize speed within the
recall floor.

**Expected:**
- A `Tuning [refine]` trajectory with **more trials than the coarse grid**
  (refinement rounds), each showing `p50_ms` and `recall@10`.
- Higher `heap_factor` is faster; recommended config near the fast end with
  `recall@10` ≥ floor.
- A line like `RECOMMENDED: heap_factor=... improvement=~1.3–2.2x vs baseline`.

---

## 5. Part D — Verify the discipline + persisted artifacts

```bash
# per-run artifacts exist for both domains
find /tmp/cb_test -name results.yaml | head
# a recommended run has a report with the MANDATORY section
grep -l "## What Went Wrong" /tmp/cb_test/*/*/report.md | head
# the results index was written and groups by reliability tag
sed -n '1,20p' /tmp/cb_test/opensearch/results_index.md
# the config is canonical and records the SPLADE model
grep -R "splade.model\|naver/splade" /tmp/cb_test/*/*/config.yaml | head
# no stray benchmark containers were left behind
docker ps --filter name=clusterbench-os -q | wc -l   # expect 0
```

---

## 6. Part E (optional) — Exercise the plugin skill directly

If the ClusterBench plugin is installed in this session, the slash commands
`/clusterbench_plan`, `/clusterbench_run`, `/clusterbench_domain` are available.
Otherwise read `plugin/skills/clusterbench_plan/SKILL.md` and follow it.

Drive a **small new tuning** through the skill workflow to confirm the skill (not
just the scripts) produces a disciplined result — e.g.:

> Plan and run a SEISMIC SPLADE benchmark that tunes `seismic.query_cut` for search
> speed within a 1pp recall floor, at `n_docs=3000, n_queries=80`. Use the Tuner,
> report the trajectory + recommended config, and confirm a RunResult + report were
> persisted.

PASS if the skill: loads context, builds a manifest-gated `BenchmarkConfig`, runs a
**tuning search** (not a single run), respects the recall floor, and persists a
report containing a "What Went Wrong" section.

---

## 7. Acceptance criteria (checklist)

- [ ] All deps import; `docker info` works; editable install succeeds.
- [ ] Part A: fast + happy suites **all pass, zero failures**.
- [ ] Part B: OpenSearch run completes; p50 decreases with fewer segments;
      recommended `max_num_segments=1`; recall within 1pp; improvement > ~1.2x.
- [ ] Part C: SEISMIC run completes; refine trajectory has > (coarse grid) trials;
      recommended config near fast end; recall ≥ floor; improvement > ~1.1x.
- [ ] Part D: `results.yaml`, `report.md` (with "What Went Wrong"), and
      `results_index.md` exist; configs record the SPLADE model; **0 stray containers**.
- [ ] (Optional) Part E: the skill produces a disciplined tuning search, not a
      single run.

Report any criterion that fails, with the actual command output.

---

## 8. Cleanup

```bash
rm -rf /tmp/cb_test
docker rm -f $(docker ps -aq --filter name=clusterbench-os) 2>/dev/null || true
```

---

## 9. Troubleshooting (known gotchas — see `plugin/lessons.md`)

- **env missing:** recreate with
  `conda create -y -n clusterbench python=3.11 && conda activate clusterbench && pip install -e ".[opensearch,seismic,dev]"`.
- **`seismic` import is the wrong package:** the real one is `pyseismic-lsr`
  (imports as `seismic`); the bare PyPI `seismic` is an unrelated seismology tool.
  `pyseismic-lsr` needs Rust ≥ 1.99 (`rustup update`).
- **OpenSearch container won't start:** ensure the Docker daemon is up and the
  image `opensearchproject/opensearch:2.17.0` is pullable; the cluster picks a free
  port automatically.
- **A speedup looks inverted / noisy:** that is the cold-cache confound (L1) — the
  domains run a warm-up pass before timing; if you add timing code, warm up first.
- **Stray container after a crash:** always tear down in a `finally` (L4);
  `docker rm -f <name>` to clean up.

## 10. Report format

Produce a short PASS/FAIL summary: the three suite results, the two recommended
configs + improvements + recall, confirmation of persisted artifacts and zero
stray containers, and a bullet list of anything that failed or surprised you.
```
