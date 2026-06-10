# Design Document: Benchmark Experiment Log Schema

**Status:** Accepted  
**Author:** neural-sparse  
**Date:** 2026-06-10  
**Implements:** `BENCHMARK_LOG_SCHEMA.md` (schema specification)

---

## 1. Problem Statement

### 1.1 Observed Failure

During a 138M single-node benchmark, the LLM agent failed to set `quantization_ceiling_search=4.0`, a parameter that was explicitly set in the prior baseline run. The agent read the baseline's prose-format run record, but the parameter was mentioned in passing within a paragraph — not flagged as a controlled variable. The result: 2-3% recall regression that invalidated the comparison.

### 1.2 Root Cause

LLM agents process prior run records by reading natural language. When parameters are embedded in prose:

1. **Silent omission** — The LLM cannot distinguish "parameter was deliberately set to X" from "parameter was not mentioned because it seemed obvious." Prose doesn't have a concept of "exhaustive enumeration."

2. **Context window loss** — Across sessions, the agent starts fresh. Prior run context is only as good as what the file system contains. If a parameter was set via an interactive command but not documented, it's permanently lost.

3. **Inheritance ambiguity** — When the user says "do the same thing but change X," the agent must reconstruct "the same thing" from prior records. If records are incomplete, "the same thing" silently diverges.

4. **Lesson disconnection** — Global lessons exist, but there's no record of which lessons were actually applied in a given run. An agent may re-discover a lesson that was already applied (wasting time) or miss one that should have been applied.

### 1.3 Scope

This design covers:
- Per-run file structure and naming
- Machine-readable parameter schema (`config.yaml`)
- Outcome recording (`results.yaml`)
- Lesson coupling (`lessons.yaml`)
- Dependency management and reproducibility
- Agent behavioral contract when reading/writing these files

Out of scope:
- Real-time monitoring data format (covered by guardrail/monitor scripts)
- Plugin hook system (covered by experiment awareness design)
- Agent decision logic (covered by benchmark agent spec)

---

## 2. Design Constraints

| Constraint | Rationale |
|-----------|-----------|
| Must be readable by LLMs without custom tooling | The agent uses `Read` and `Bash` — no custom parsers |
| Must be diffable | `config.yaml` between runs should produce meaningful git-style diffs |
| Must be exhaustive for parameters | The "forgot a parameter" class of bugs must be structurally impossible |
| Must support forward references | A run may depend on a future run (e.g., "will validate after fix") |
| Must support partial completion | A run aborted at preflight still produces a valid record |
| Must not require human maintenance | The agent generates all files; humans only review |
| Must coexist with legacy format | Existing `run_*.md` files remain readable during migration |
| Must be VCS-friendly | YAML/Markdown, no binary, no huge files in the schema itself |

---

## 3. Architecture

### 3.1 Two-Layer Design

```
┌─────────────────────────────────────────────────────────┐
│ Global Layer (benchmark_data/)                           │
│  INDEX.md — summary table of all runs                   │
│  lessons.md — accumulated lessons across runs           │
│  risks.md — known fragilities and limits                │
│  settings/ — environment documentation                  │
└─────────────────────────────────────────────────────────┘
        │ references ↕ referenced-by
┌─────────────────────────────────────────────────────────┐
│ Per-Run Layer (benchmark_data/runs/<run_id>/)            │
│  README.md — human context, motivation, dependencies    │
│  config.yaml — ALL parameters (machine-readable)        │
│  results.yaml — outcomes, metrics, comparison           │
│  lessons.yaml — applied/discovered/remaining            │
│  scripts/ — execution artifacts + changelog             │
│  artifacts/ — runtime snapshots, logs, data             │
└─────────────────────────────────────────────────────────┘
```

**Why two layers?**

- The **global layer** answers "what do I know across all experiments?" — used at session start and prompt detection
- The **per-run layer** answers "what exactly happened in this specific experiment?" — used during planning (config diff) and analysis (results comparison)

The agent reads global first (cheap, fits in context), then drills into specific runs when needed.

### 3.2 File Roles

| File | Primary Consumer | Write Time | Update Frequency |
|------|-----------------|-----------|------------------|
| `config.yaml` | Agent (planning) | Plan approval | Never (immutable after creation) |
| `README.md` | Human + Agent | Plan approval | Once (outcome filled post-run) |
| `results.yaml` | Agent (analysis, comparison) | Post-run | Rarely (reliability reclassification) |
| `lessons.yaml` | Agent (planning) | Plan + post-run | Once per phase |
| `scripts/` | Agent (execution) | Plan approval | Never |
| `artifacts/` | Agent (analysis) | During/after run | Append-only |
| `INDEX.md` | Agent (discovery) | Post-run | On every new run |
| `lessons.md` | Agent (planning) | Post-run | On lesson discovery |

### 3.3 Immutability Contract

- `config.yaml` is **write-once**. It captures the plan at approval time. If parameters change mid-run (shouldn't happen), that's recorded in `artifacts/events.log`, not by editing config.yaml.
- `results.yaml` is **write-once + reclassify**. The metrics are fixed after analysis. Only `reliability_tag` and `reliability_reason` can be updated later.
- `scripts/` is **write-once**. Scripts are generated, reviewed, and never modified post-approval.
- `artifacts/` is **append-only**. New files added during/after run, never deleted.

---

## 4. Key Design Decisions

### 4.1 Why YAML over JSON for config/results?

| Factor | YAML | JSON |
|--------|------|------|
| Comments | Yes (critical for `note:` fields) | No |
| Multi-line strings | Native | Escaped |
| Readability | Human-scannable | Needs formatting |
| LLM generation | Reliable | Reliable |
| Diffability | Good | Good |
| Parsing | Standard | Standard |

YAML's comment support is essential — the `note:` field explains WHY a parameter has a particular value. JSON would require a separate `_note` key pattern that's less natural.

### 4.2 Why Explicit `source` Field on Every Parameter?

Alternatives considered:

1. **Only list non-default parameters** — Fails because the agent cannot determine if an absent parameter was "deliberately left at default" or "forgotten." This is exactly the bug we're fixing.

2. **List all parameters without source annotation** — Better, but doesn't distinguish "I set this to 32" from "I checked and the default of 32 is correct." The source field makes the agent's reasoning auditable.

3. **Only list changed parameters + a "baseline" reference** — Requires the agent to load the baseline's config.yaml to compute the full set. Adds a dependency chain that breaks if baseline is deleted. Each config.yaml should be self-contained.

**Decision:** Every parameter appears with `value` + `source` (`"set"` | `"default"` | `"inherited"`). Verbose, but eliminates ambiguity. The agent's parameter alignment check relies on this exhaustiveness.

### 4.3 Why Per-Run `lessons.yaml` in Addition to Global `lessons.md`?

The global `lessons.md` answers "what do we know?" The per-run `lessons.yaml` answers three questions the global file cannot:

1. **"Was lesson L2 applied in this run?"** — The `applied` section with `verified: true/false` creates accountability
2. **"What was discovered HERE vs what was already known?"** — The `discovered` section with `source: "this run"` traces provenance
3. **"What's still unresolved?"** — The `remaining` section carries forward across runs without being lost

Without per-run lesson tracking, the agent may:
- Apply a lesson that was already applied (redundant work)
- Skip a lesson because it "feels familiar" but was never actually applied
- Lose a discovered lesson because it wasn't immediately added to global

### 4.4 Why `reproduce_deps.sh` Instead of Just Documenting Dependencies?

Documentation says "the dataset should be at `/home/ubuntu/dataset/merged_passages.csr`." But when the agent reads this 2 weeks later, the file may have been deleted, the node rebooted, or the path changed.

The reproduction script is executable verification:
- **Check:** Is the dependency present and valid?
- **Reproduce:** If not, can it be recreated?
- **Fail clearly:** If reproduction is impossible, say so

This converts "dependency exists" from a statement of faith into a testable assertion.

### 4.5 Why `scripts/CHANGELOG.md` Instead of Just Diffing Scripts?

The agent generates scripts from templates, customized per-run. A raw `diff` between two runs' scripts shows WHAT changed but not WHY. The changelog annotates each change:

```
- Changed: `number_of_shards` from 3 to 1
  Reason: treatment variable (testing single-node performance)
```

This is especially important when a change is NOT the treatment variable — it might be a bug or an unintended deviation. The changelog forces explicit acknowledgment of every difference.

### 4.6 Why Config Hash in INDEX.md?

Two runs may have nearly identical configurations with one small difference (the treatment variable). The config hash lets the agent quickly identify:
- **Same hash:** Reproduction attempt (should produce same results)
- **Different hash:** Something changed — look at the diff

Without the hash, the agent must load and compare full config.yaml files to determine if two runs are comparable. The hash is a cheap first-pass filter.

---

## 5. Parameter Alignment Protocol

The most important behavioral change this schema enables:

```
FOR EACH parameter P in baseline.config.yaml:
  IF P is mentioned in user's request:
    → Use requested value, mark source: "set"
  ELSE IF P is the treatment variable:
    → Use new value, mark source: "set"  
  ELSE:
    → Inherit baseline value, mark source: "inherited"
    → If baseline value ≠ system default, LOG this inheritance

IF baseline has parameters NOT in schema template:
  → These are domain-specific additions. Copy them.

IF user's request mentions parameters NOT in baseline:
  → New parameters. Add them with source: "set"
  → Flag as potential comparability concern
```

**The critical invariant:** `len(new_config.parameters) >= len(baseline_config.parameters)`. The parameter set can only grow, never shrink. A shrinking parameter set means something was forgotten.

---

## 6. Lifecycle of a Run Folder

```
[Plan Phase]
  Agent creates: runs/<id>/
    config.yaml     ← full parameter set, locked
    README.md       ← motivation, deps, lessons to apply
    lessons.yaml    ← applied + remaining sections
    scripts/        ← all execution scripts
      CHANGELOG.md
      execute.sh
      guardrail.sh
      monitor.sh
      check.sh
      reproduce_deps.sh

[Preflight Phase]
  Agent runs dependency checks from README.md
  Agent snapshots actual settings to artifacts/
    artifacts/cluster_settings.json
    artifacts/index_settings.json
    artifacts/jvm_options.txt
  If abort: writes results.yaml with status: ABORTED_PREFLIGHT

[Execution Phase]  
  Scripts write to artifacts/:
    artifacts/monitor.csv     (time-series, append-only)
    artifacts/events.log      (phase transitions, alerts)
  Guardrail may write:
    artifacts/events.log += GUARDRAIL_KILL entry
    results.yaml with status: ABORTED_GUARDRAIL

[Analysis Phase]
  Agent writes:
    results.yaml              ← metrics, verdict, comparison
    lessons.yaml += discovered section
    README.md += Outcome section

[Persist Phase]
  Agent updates global:
    INDEX.md += new row
    lessons.md += discovered lessons
    risks.md += new fragilities (if any)
```

---

## 7. Schema Evolution

### 7.1 Versioning

Every YAML file starts with `schema_version: "1.0"`. If the schema changes:

- **Minor** (new optional fields): Increment to 1.1. Old files remain valid.
- **Major** (required fields added/renamed): Increment to 2.0. Agent must handle both.

The agent reads `schema_version` before parsing. Unknown versions trigger a warning, not a crash.

### 7.2 Extension Points

Domain-specific parameters (e.g., SEISMIC-specific `heap_factor`, `top_n`) live under `algorithm.parameters`. New domains add their own keys without modifying the schema structure.

Custom artifact types (e.g., flame graphs, heap dumps) go in `artifacts/` with a descriptive filename. No registration required.

### 7.3 Migration from Legacy

Existing `benchmark_data/runs/run_*.md` files are legacy. The agent can:
1. Read them (prose parsing, best-effort)
2. Use them as baselines (extract parameters into an in-memory config)
3. Optionally backfill a `config.yaml` for important runs

Migration is not forced — the new schema applies to new runs only.

---

## 8. Failure Modes and Mitigations

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| Agent generates invalid YAML | config.yaml is unparseable for next run | Validate with `python3 -c "import yaml; yaml.safe_load(open(f))"` post-generation |
| User modifies config.yaml after approval | Immutability contract broken | Agent re-reads and diffs at preflight; warns if changed |
| Baseline run folder deleted | Parameter alignment check fails (no baseline) | Fall back to second-most-recent RELIABLE run; warn user |
| Config hash collision | Two different configs appear identical | SHA-256 truncated to 6 chars — collision probability negligible for <1000 runs |
| Legacy run used as baseline | No config.yaml to diff against | Agent extracts parameters from prose with explicit "(EXTRACTED — may be incomplete)" warning |
| Agent hallucinates a parameter value | config.yaml contains wrong value | `verify` command in controlled_variables lets preflight catch discrepancies |
| reproduce_deps.sh fails | Dependency cannot be recreated | Script exits with clear error; agent reports and stops |

---

## 9. Design Principles

1. **Explicit over implicit** — Every parameter present, every decision annotated.

2. **Machine-first, human-readable** — YAML for parsing, comments/notes for understanding.

3. **Self-contained runs** — Each run folder has everything needed to understand it without loading other runs (though cross-references exist for comparison).

4. **Append-only history** — Runs are never deleted. Bad runs are reclassified, not erased. The full history of the experiment is preserved.

5. **Fail loudly** — A missing parameter is an error, not a default. A missing dependency is a blocker, not a warning. Silent degradation is the enemy.

6. **Lessons travel with runs** — Not just globally accumulated, but individually tracked per-run so the agent knows WHICH lessons were active WHEN.

7. **Reproducibility by design** — Between `config.yaml` (what to set), `scripts/` (how to run), and `reproduce_deps.sh` (how to recreate prerequisites), any run should be reproducible from its folder alone.

---

## 10. Interaction with Other Components

### 10.1 Experiment Awareness Hooks

The `UserPromptSubmit` hook reads `INDEX.md` to inject baseline context. With the new schema, it can also read the most recent run's `config.yaml` to surface critical parameters:

```
[Experiment Awareness]
Most recent RELIABLE baseline: 2026-06-08-persistent-eviction-cfs
  Critical non-default params: index_thread_qty=32, quantization_ceiling_search=4.0
```

### 10.2 Benchmark Agent Skill

The skill's Step 2 (planning) now generates the full run folder. The parameter alignment check is the enforcement mechanism — it mechanically prevents the "forgot a parameter" failure by requiring exhaustive enumeration.

### 10.3 Benchmark Run Skill

The runner reads scripts from `runs/<id>/scripts/` (not the old flat `benchmark_data/scripts/`). Monitor output goes to `runs/<id>/artifacts/monitor.csv`.

### 10.4 CLAUDE.md

The benchmark results policy in CLAUDE.md adds:
- "When planning a run, always diff config.yaml against the baseline"
- "Never execute without a complete run folder (config.yaml + scripts/ + README.md)"

---

## 11. Example: How This Prevents the Original Bug

**Scenario:** User asks "run the same benchmark but on a single node."

**Without schema:**
1. Agent reads prose baseline: "We ran SEISMIC with SQ uint8, 32 threads, got 3ms p50..."
2. Agent doesn't notice `quantization_ceiling_search=4.0` buried in a paragraph
3. Agent configures everything EXCEPT that parameter
4. Run produces 2-3% worse recall
5. Investigation wastes 2 hours discovering the missing parameter

**With schema:**
1. Agent loads `runs/2026-06-08-persistent-eviction-cfs/config.yaml`
2. Iterates ALL parameters. Finds `quantization_ceiling_search: {value: 4.0, source: "set"}`
3. User's request doesn't mention this parameter
4. Agent outputs:
   ```
   PARAMETER ALIGNMENT CHECK:
   baseline set quantization_ceiling_search=4.0 (default is 3.0)
   Inheriting 4.0 for comparability.
   ```
5. Parameter appears in new config.yaml with `source: "inherited"`
6. Run produces correct results

Time saved: 2 hours of debugging + 1 invalidated run + 1 re-run.

---

## 12. Open Questions

1. **Should artifacts/ have a manifest?** Currently free-form. A manifest.yaml listing each file + its role would help the agent know what to look for. Deferred — let usage patterns emerge first.

2. **Should config.yaml support templates?** A "SEISMIC benchmark template" that pre-fills known parameters. Risk: templates drift from reality. Decision: no templates — always diff from most recent RELIABLE run.

3. **Maximum run folder size?** `monitor.csv` at 5s interval for 15 hours = ~10,000 rows ≈ 500 KB. Event logs are small. Total run folder: ~1-2 MB typical. Not a concern.

4. **Should the schema enforce field ordering?** YAML is order-independent, but consistent ordering aids diffing. Decision: generate in canonical order (as shown in schema spec) but don't reject non-canonical files.
