# Deep Claude Code Integration: Benchmark-Aware Intelligence

## Proposal Summary

Make Claude Code inherently smarter about experimentation and benchmarking — not through explicit skill invocation, but through behavioral enrichment that activates transparently when the work context involves performance measurement, comparison, or optimization.

This is NOT a plugin. It's a proposal for core Claude Code capabilities that benefit all users doing any kind of empirical work (benchmarking, A/B testing, load testing, profiling, experiment tracking) without adding commands or changing workflows.

---

## Motivation

### The Problem Today

Claude Code is excellent at coding tasks but naive about empirical tasks. When a user says "run the benchmark," Claude treats it like any other command — execute and report. It doesn't ask:

- "What are you comparing against?"
- "Is this a fair comparison?"
- "Is the environment the same as last time?"
- "These numbers look too good — did you check the measurement?"

This naivety leads to:
1. **Wasted computation** — Running 5-hour experiments that produce uninterpretable results because a variable wasn't controlled
2. **False conclusions** — Celebrating improvements that are actually measurement artifacts
3. **Memory loss** — Every session rediscovers the same environment, settings, and lessons
4. **Silent failures** — Results look fine but hide bugs, confounds, or invalid measurements

### The Opportunity

Claude Code already has the building blocks:
- **Memory system** — Can persist lessons across sessions
- **Task tracking** — Can manage multi-step workflows
- **Plan mode** — Can propose and get approval before acting
- **Hooks** — Can trigger behavior on events
- **Skills** — Can activate specialized behavior contextually

What's missing is the **intelligence layer** that connects these building blocks into experiment-aware reasoning. This proposal adds that layer without modifying existing workflows.

---

## Design Principles

```
1. TRANSPARENT    — Activates when relevant, invisible otherwise
2. NON-INTRUSIVE — Zero impact on non-benchmark workflows
3. PROGRESSIVE   — Light touch for simple benchmarks, full protocol for critical ones
4. OPEN          — Works with any system being benchmarked, not just specific tools
5. COMPOSABLE    — Builds on existing Claude Code primitives (memory, tasks, plans, hooks)
```

---

## Architecture

### Layer Model

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 4: EXPERIMENT LIFECYCLE                                    │
│   Long-running operation management, phase tracking,            │
│   completion detection, session-resilient monitoring             │
├─────────────────────────────────────────────────────────────────┤
│ Layer 3: ANALYTICAL REASONING                                   │
│   Skeptical analysis, mechanism explanation, fragility           │
│   identification, scaling projection, root cause protocol       │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2: COMPARISON INTEGRITY                                   │
│   Variable control, fair comparison enforcement,                │
│   result reliability classification, citation rules             │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: EXPERIMENT AWARENESS                                   │
│   Context detection, history loading, environment tracking,     │
│   measurement validity, automatic instrumentation               │
├─────────────────────────────────────────────────────────────────┤
│ Layer 0: EXISTING CLAUDE CODE                                   │
│   Memory, Tasks, Plans, Hooks, Skills, Tools                    │
└─────────────────────────────────────────────────────────────────┘
```

Each layer activates independently. A user doing a quick `time ./my_program` gets Layer 1 (awareness) only. A user running a 6-hour distributed benchmark gets all four layers.

---

## Layer 1: Experiment Awareness

### What It Does

Claude Code recognizes when the user is doing empirical work and automatically enriches its context with relevant prior state.

### Detection Signals

Claude Code should recognize benchmark/experiment context when it observes:

```
STRONG signals (any one activates Layer 1):
- User mentions "benchmark", "performance", "latency", "throughput", "RSS", "peak memory"
- User asks to compare metrics across runs ("faster than before?", "how does this compare?")
- User runs commands that produce numeric measurements (time, perf, ab, wrk, jmh)
- Project contains benchmark_data/, .benchmarks/, or similar directories
- Prior memory contains benchmark-related entries

WEAK signals (two or more needed):
- User mentions "before and after"
- Commands involve profiling tools (perf, valgrind, instruments)
- User tracks resource consumption (ps, top, htop, /proc/meminfo)
- Repeated execution of the same command with timing
```

### Automatic Context Loading

When Layer 1 activates, Claude Code automatically:

1. **Checks for experiment history** in the project
   ```
   Look for: benchmark_data/, .benchmarks/, results/, perf_data/
   If found: load results_index.md or equivalent
   ```

2. **Loads relevant environment state**
   ```
   If prior benchmark settings exist: load them
   If the user is about to run on a known cluster: load access/config docs
   ```

3. **Surfaces relevant lessons**
   ```
   If memory contains benchmark lessons: make them available for reasoning
   But: do NOT dump them unprompted into the conversation
   ```

### Implementation Approach

This could be implemented as a **context enrichment hook** — similar to how CLAUDE.md is loaded, but conditional:

```jsonc
// In Claude Code's context assembly logic (pseudocode)
if (experiment_signals_detected(user_message, project_state)) {
  context.add(load_experiment_history(project));
  context.add(load_benchmark_settings(project));
  reasoning_mode.activate("empirical");  // Adjusts reasoning patterns
}
```

**Non-intrusive because:** If no signals detected, zero additional context loaded, zero behavioral change.

---

## Layer 2: Comparison Integrity

### What It Does

When Claude Code is about to help the user compare measurements, it automatically checks for fair comparison conditions — without requiring explicit invocation of a comparison protocol.

### Behavioral Changes (When Active)

**Before any comparison statement**, Claude Code internally checks:

```
1. SAME ENVIRONMENT?
   - Are the two measurements from the same hardware?
   - Same software versions?
   - Same configuration?
   
2. SAME WORKLOAD?
   - Same input data?
   - Same data volume?
   - Same concurrency level?

3. SAME MEASUREMENT?
   - Same metric (RSS vs VSZ vs page cache)?
   - Same measurement tool?
   - Same sampling interval?
   
4. SINGLE VARIABLE?
   - What exactly changed between the two?
   - Is there only one intentional difference?
   - Are there unintentional differences?
```

If any check fails, Claude Code **does not silently proceed** — it raises the concern:

```
"Before I compare these results: the prior run used 32 segments but this 
run has 47. That's a significant confound — more segments means more merge 
rounds. Want me to normalize this first, or note it as a caveat?"
```

### Result Reliability Awareness

When Claude Code references a prior measurement (from memory, from files, from conversation history), it considers:

- **Recency** — Is this measurement still valid? Has the system changed?
- **Provenance** — Where did this number come from? Was it well-measured?
- **Conditions** — Under what conditions was this true? Do those conditions still hold?

If citing a number that might be stale or invalidated:
```
"The prior measurement of 69 GB was from May 30 with 32 segments and no 
eviction. Since then we've changed the eviction strategy, so direct 
comparison requires careful interpretation."
```

### Implementation Approach

This is a **reasoning pattern modification** — not new tools, but adjustments to how Claude Code reasons about numeric claims:

```python
# Pseudocode for comparison reasoning
class EmpiricalReasoning:
    def before_making_comparison(self, value_a, value_b, context):
        confounds = self.identify_confounds(context)
        if confounds:
            self.surface_confounds(confounds)  # Tell the user
            self.mark_comparison_as("qualified")
        
    def before_citing_measurement(self, measurement, source):
        if source.age > threshold or source.conditions_changed():
            self.add_caveat(measurement, source)
```

**Non-intrusive because:** Only activates when Claude Code is about to make a comparative claim. Normal coding work never triggers this.

---

## Layer 3: Analytical Reasoning

### What It Does

When Claude Code interprets benchmark results, it applies structured skepticism rather than naive reporting.

### The Core Behavioral Shift

**Without this layer (current behavior):**
```
User: "Peak RSS dropped from 79 GB to 61 GB!"
Claude: "Great improvement! The fix reduced peak memory by 23%."
```

**With this layer:**
```
User: "Peak RSS dropped from 79 GB to 61 GB!"
Claude: "61 GB observed. Before celebrating — can we account for where 
each GB comes from? 17 (JVM) + 40 (CSR) + 4 (page cache) = 61. That 
accounts for the full peak. 

But the 79→61 comparison has a confound: the prior run had more starting 
segments. The meaningful comparison is against the 69-71 GB baseline with 
32 segments — that's a 13-17% improvement from the same starting point.

Also: 61 GB is the theoretical floor for this doc count. Further 
improvement requires reducing CSR size or doc count, not eviction tuning."
```

### Analytical Patterns

**Pattern: Account For Every Unit**
```
When a metric is reported, don't just accept it — decompose it.
"61 GB = what exactly?" Force enumeration of components.
If components don't sum to observed: flag the gap.
```

**Pattern: Good Results Get More Questions**
```
When result is better than expected:
- What assumption makes this hold?
- What would break it?
- Is this the floor? How close to theoretical minimum?
- What paths weren't exercised?
```

**Pattern: Bad Results Get Structured Investigation**
```
When result is worse than expected:
- List all possible causes (don't guess one)
- What exactly changed? (use diff, not inference)
- Can the hypothesis explain the full magnitude?
- Is it node-specific, phase-specific, or intermittent?
```

**Pattern: Mechanism Over Correlation**
```
Never say: "X improved because we did Y" 
Without: a causal chain explaining HOW Y reduces X, 
AND: the magnitude matching prediction.
```

### Implementation Approach

This is the hardest layer — it's a **reasoning style** rather than a feature. Implementation options:

**Option A: System prompt enrichment (lightest touch)**
```
When empirical_mode is active, append to system context:
"You are analyzing empirical results. Apply skeptical reasoning:
 - Account for every unit of the measured metric
 - Good results require MORE scrutiny (what breaks it?)
 - Bad results require structured elimination (don't guess)
 - Never claim causation without mechanism + magnitude match"
```

**Option B: Structured analysis tool**
A built-in tool that forces structured output:
```
AnalyzeResult(
  metric="peak_rss",
  observed=61,
  expected=70,
  prior=79,
  unit="GB"
)
→ Triggers structured analysis workflow internally
→ Returns decomposition, fragility, confidence level
```

**Option C: Post-generation verification (most powerful)**
After Claude Code generates a response about results, an internal verifier checks:
- Did it account for the full metric?
- Did it consider confounds?
- Did it identify fragility?
- Did it hide inconvenient findings?

If verification fails, the response is revised before presenting to user.

**Recommendation:** Option A for initial implementation (cheap, non-intrusive), with Option C as a future enhancement for high-stakes experiments.

**Non-intrusive because:** Only activates when discussing numeric results in experiment context. Writing code, fixing bugs, reviewing PRs — unaffected.

---

## Layer 4: Experiment Lifecycle

### What It Does

Provides native support for operations that take hours, span multiple sessions, and require autonomous monitoring — without inventing new abstractions.

### The Problem

Claude Code sessions are ephemeral but experiments are long-lived. Current workarounds:
- `nohup` scripts (survive session death but have no intelligence)
- `/loop` (periodic check-in but dies with session)
- Manual resume (user must remember to ask about in-flight work)

### Proposed: First-Class "Experiment" Concept

An **experiment** is a managed long-running operation with:
- A defined start, phases, and completion condition
- Autonomous monitoring that survives session death
- Automatic context restoration on session resume
- Structured completion handling (analysis trigger)

```
┌─────────────────────────────────────────────────────────────────┐
│ Experiment Lifecycle (managed by Claude Code runtime)            │
│                                                                 │
│  PLAN → PREFLIGHT → RUNNING → [MONITORING] → COMPLETE → ANALYZE│
│    │         │          │          │              │          │   │
│    │         │          │     (survives          │          │   │
│    │         │          │      session           │          │   │
│    ▼         ▼          ▼      death)            ▼          ▼   │
│  human    human      nohup    daemon/cron     signal     human  │
│  approval  check     process   check-in        file      review │
└─────────────────────────────────────────────────────────────────┘
```

### API (How Users Would Interact)

No new commands needed. Claude Code infers the lifecycle from natural conversation:

```
User: "Start the force merge and monitor it"
Claude: [recognizes: long-running, needs monitoring, user wants to walk away]
  → Creates experiment record
  → Generates+launches execution script
  → Deploys monitor daemon
  → Registers completion handler
  → "Force merge started. I'll track it autonomously. 
     Expected duration: ~5.5h. You can close this session."

[Next session, or wake-on-completion]
Claude: "Force merge completed 20 minutes ago. Peak RSS: 61 GB 
  across all nodes. Shall I run the full analysis?"
```

### Implementation: Experiment Registry

A lightweight registry in `.claude/experiments/`:

```yaml
# .claude/experiments/active/exp_2026-06-10_force-merge.yaml
id: "2026-06-10-force-merge"
status: running  # plan | preflight | running | complete | failed | analyzed
started: "2026-06-10T14:30:00Z"
expected_duration: "5.5h"

execution:
  script: "/path/to/execute.sh"
  pid_file: "/path/to/execute.pid"
  
monitoring:
  script: "/path/to/monitor.sh"
  pid_file: "/path/to/monitor.pid"
  log: "/path/to/monitor.log"
  
signals:
  complete: "/path/to/.complete"
  failed: "/path/to/.failed"
  
on_complete: "Run /benchmark_agent analyze 2026-06-10-force-merge"
on_failure: "Report failure, collect crash artifacts"

context:
  plan: "/path/to/plan.md"
  prior_run: "2026-06-08-persistent-eviction-cfs"
  lessons_loaded: ["L1", "L3", "L5"]
```

### Session Resume Behavior

When Claude Code starts a new session and finds active experiments:

```python
# Pseudocode for session start
experiments = load_active_experiments()
for exp in experiments:
    if exp.signal_complete_exists():
        notify_user(f"Experiment {exp.id} completed. Analysis ready.")
    elif exp.signal_failed_exists():
        notify_user(f"Experiment {exp.id} failed. Investigation needed.")
    elif exp.is_running():
        notify_user(f"Experiment {exp.id} in progress ({exp.elapsed()}).")
    elif exp.monitor_dead():
        notify_user(f"Experiment {exp.id} monitor died. Reconnect?")
```

This could integrate with the existing **SessionStart hook** to be completely transparent.

### Implementation Approach

**Phase 1 (plugin-level, today):** The `/benchmark_run` skill already does this with nohup + /loop + signal files. This works but requires explicit skill invocation.

**Phase 2 (core enhancement):** Add an `Experiment` primitive to Claude Code alongside Task and Plan:
- `ExperimentCreate` — Register a long-running operation
- `ExperimentStatus` — Check experiment state
- `ExperimentComplete` — Mark as done, trigger handler
- Session start hook automatically checks for active experiments

**Phase 3 (full integration):** Claude Code's runtime manages the daemon process (not relying on nohup + /loop hacks):
- Native daemon process that persists across sessions
- Built-in wake-on-completion (no polling needed)
- Integrated with Claude Code's notification system (desktop notifications, telegram, etc.)

**Non-intrusive because:** The Experiment concept is opt-in. It only activates when Claude Code detects a long-running operation that the user wants to leave running. Normal `bash` commands, `git` operations, file edits — completely unaffected.

---

## Integration Points with Claude Code Source

Based on Claude Code being open source, here are the specific integration points:

### 1. Context Assembly (Layer 1)

**Where:** The context assembly pipeline that builds the system prompt + conversation context.

**Change:** Add a conditional context enrichment step that loads experiment history when empirical signals are detected.

```typescript
// Pseudocode for where this fits
class ContextAssembler {
  async assemble(message: UserMessage, project: Project): Promise<Context> {
    const context = new Context();
    context.add(await this.loadClaudeMd(project));
    context.add(await this.loadMemory(project));
    
    // NEW: conditional experiment context
    if (this.detectsEmpiricalWork(message, project)) {
      context.add(await this.loadExperimentHistory(project));
      context.setReasoningMode("empirical");
    }
    
    return context;
  }
}
```

### 2. Response Generation (Layers 2-3)

**Where:** The system prompt / behavioral instructions that guide Claude's reasoning.

**Change:** When empirical mode is active, append analytical reasoning guidelines to the system prompt. This is the lightest possible touch — no code changes to the model, just prompt enrichment.

```typescript
// Added to system prompt when empirical mode active
const EMPIRICAL_REASONING_SUPPLEMENT = `
When analyzing empirical results in this conversation:
- Before comparing two measurements, verify they come from comparable conditions
- Account for every unit of a measured metric (decompose into components)
- Good results require more scrutiny: what assumption must hold? what breaks it?
- Bad results require structured investigation: list causes, measure each, quantify gap
- Never claim causation without mechanism explanation AND magnitude match
- Always report what went wrong alongside what went well
- If citing a prior measurement, verify its conditions still apply
`;
```

### 3. Tool Extensions (Layer 4)

**Where:** The tool registry / tool execution system.

**Change:** Add Experiment-lifecycle tools alongside existing Task tools:

| Existing | New (parallel) |
|----------|----------------|
| `TaskCreate` | `ExperimentCreate` |
| `TaskUpdate` | `ExperimentUpdate` |
| `TaskGet` | `ExperimentGet` |
| `TaskList` | `ExperimentList` |

These are structurally identical to Tasks but with:
- A `status` field with experiment-specific states (plan → preflight → running → complete → analyzed)
- An `on_complete` handler that triggers analysis
- A `monitoring` section with daemon management
- Session-start integration for automatic status reporting

### 4. Hooks (Cross-Cutting)

**Where:** The hooks system (settings.json `hooks` field).

**Change:** Add experiment-aware hook events:

```jsonc
{
  "hooks": {
    // Existing hooks unchanged
    "PreToolUse": [...],
    "PostToolUse": [...],
    
    // New: experiment lifecycle events
    "ExperimentComplete": [
      {
        "command": "echo 'Experiment complete' | notify-send",
        "description": "Desktop notification on experiment completion"
      }
    ],
    "ExperimentCritical": [
      {
        "command": "send-alert --channel telegram",
        "description": "Alert on critical threshold"
      }
    ],
    "SessionStart": [
      {
        "command": "check-active-experiments",
        "description": "Report active experiments on session start"
      }
    ]
  }
}
```

---

## Progressive Activation Model

The system should scale its involvement based on experiment criticality:

| Signal | Activation Level | Behavior |
|--------|-----------------|----------|
| `time ./program` | Minimal | Remember result for later comparison |
| "How does this compare to before?" | Layer 2 | Check comparison fairness |
| "Run the benchmark" | Layers 1-3 | Load history, validate environment, analyze results |
| "Run the 6-hour force merge and monitor it" | All layers | Full lifecycle management |
| No empirical signals | None | Zero behavioral change |

This prevents the system from being annoying during normal coding work while being maximally helpful during experiments.

---

## What This Enables (User Stories)

### Story 1: Accidental Confound Prevention
```
User: "The latency dropped from 8ms to 3ms after my change!"
Claude: "I see the 3ms measurement. Before we attribute this to your 
  change — I notice the prior 8ms was measured with heap_factor=1.03, 
  but the current run uses 1.08. That parameter change alone explains 
  the improvement (from the parameter sweep in run 2026-05-25). 
  To validate your code change, re-run with the same heap_factor."
```

### Story 2: Stale Baseline Detection
```
User: "Compare our current throughput against the baseline"
Claude: "The last recorded baseline is from May 15 on OpenSearch 2.18. 
  We're now on 2.19 with 3 plugin changes since then. The baseline 
  may not be comparable. Want me to re-run the baseline on current 
  software first?"
```

### Story 3: Transparent Long-Running Management
```
User: "Start the full ingest + force merge + search validation pipeline"
Claude: "That's roughly 4.5h ingest + 5.5h merge + 10min search = ~10h.
  
  I'll set this up to run autonomously:
  - Phase monitoring every 30s (RSS, disk, progress)
  - Alert if RSS exceeds 110 GB (92% of node RAM)
  - Auto-trigger search validation after merge completes
  - Full analysis report when everything finishes
  
  You can close this session. I'll have results when you're back."

[10 hours later, new session]
Claude: "Your pipeline completed at 3:42 AM. Results:
  - Ingest: 137.9M docs, 8.1K docs/s, no errors
  - Force merge: 59.8 GB peak RSS, 12.5 min build
  - Search: 3ms p50, no regression
  
  One anomaly: Node 2 had a 45-second GC pause during Phase 3 
  that I wasn't expecting. Didn't affect the result but worth 
  investigating if it recurs. Full report saved."
```

### Story 4: Cross-Session Memory Without Manual Effort
```
[Session 1, last week]
User: "Why did the build take so long?"
Claude: [discovers index_thread_qty=1, explains, user fixes to 32]

[Session 2, today]
User: "Run the force merge"
Claude: [loads lesson from memory] 
  "Before starting — confirming index_thread_qty is set to 32. 
  Last time this was accidentally at 1, causing a 50h build. 
  ... confirmed, it's 32. Proceeding."
```

### Story 5: Honest Failure Reporting
```
User: "How did the benchmark go?"
Claude: "Mixed results. The primary metric improved (61 vs 69 GB), 
  but I found three issues:
  
  1. Node 3 started with fewer segments (44 vs 47) due to a 
     background merge I didn't prevent. This is a minor confound.
  2. The eviction thread logged 3 failed madvise calls. No impact 
     on this run, but indicates an edge case in the /proc parser.
  3. Build time was 12.7 min vs expected 12.5 min. Within noise, 
     but I want to flag it for tracking.
  
  Verdict: PASS with caveats. The improvement is real but the 
  code has latent issues that should be fixed before production."
```

---

## Implementation Roadmap

### Phase 1: Prompt Enrichment (1-2 weeks, zero code changes to Claude Code)

What: Create a CLAUDE.md snippet + memory entries that activate empirical reasoning patterns. This is what we already built with the benchmark_agent plugin — it works today.

Validates: Does prompt-based behavioral modification actually prevent confounded comparisons and improve analysis quality?

### Phase 2: Context Detection Hook (2-3 weeks, small Claude Code change)

What: Add a SessionStart hook that checks for active experiments and loads relevant context. Add a PostToolUse hook that detects empirical output (timing data, metrics) and enriches the reasoning context.

Validates: Does automatic context loading reduce "rediscovery time" at session start?

### Phase 3: Experiment Primitive (4-6 weeks, medium Claude Code change)

What: Add `ExperimentCreate/Update/Get/List` tools parallel to Task tools. Add session-start integration. Add completion handlers.

Validates: Does native lifecycle management improve reliability over nohup + /loop hacks?

### Phase 4: Reasoning Mode (6-8 weeks, requires model-level work)

What: Formal "empirical reasoning mode" that adjusts Claude's analytical behavior when activated. This goes beyond prompt engineering into training-time or fine-tuning work.

Validates: Does a model trained to be skeptical about measurements produce fewer false conclusions?

---

## Success Metrics

How to measure if this integration works:

| Metric | How to Measure | Target |
|--------|---------------|--------|
| Confound detection rate | % of unfair comparisons caught before the user notices | >80% |
| Session startup time | Time from new session to productive benchmark work | <2 min (vs 30+ min today) |
| False conclusion rate | % of benchmark reports later found to have wrong conclusions | <5% |
| Wasted run rate | % of long runs that produce uninterpretable results | <10% |
| Recovery time | Time to resume monitoring after session death | <30s (automatic) |
| User trust | Does the user trust Claude's analysis without double-checking? | Qualitative |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Over-activation: triggers on non-benchmark work | Annoying, user disables it | Conservative signal thresholds; explicit opt-out |
| False skepticism: questions valid results unnecessarily | Slows down work | Only challenge when confound is concrete and nameable |
| Context bloat: loading too much history | Slow responses, high cost | Only load index + most recent comparable run, not all history |
| Stale reasoning: applying old lessons that no longer apply | Wrong conclusions | Lessons must have conditions; verify conditions still hold |
| Daemon management complexity: nohup/cron fragility | Lost monitoring, missed completions | Phase 3 native daemon solves this; Phase 1-2 accept the limitation |

---

## Comparison: Plugin vs Deep Integration

| Aspect | Plugin (Today) | Deep Integration (Proposed) |
|--------|---------------|---------------------------|
| Activation | Explicit `/benchmark_agent` | Automatic when context detected |
| Context loading | Manual step in skill | Transparent in context assembly |
| Comparison checks | Only during analysis phase | Every time a comparison is made |
| Session resilience | nohup + /loop (fragile) | Native experiment lifecycle |
| Reasoning quality | Prompt-engineered | Potential model-level enhancement |
| User effort | Must know to invoke skill | Zero — just works |
| Portability | Any Claude Code user with plugin | Built into Claude Code for everyone |

---

## Summary

This proposal takes the benchmark agent from "a tool you invoke" to "intelligence that's always there when you need it." The key insight is that empirical reasoning should be a **mode** of Claude Code, not a **command** — activated by context, not by the user remembering to type `/benchmark_agent`.

The implementation is progressive: Phase 1 works today with zero Claude Code changes. Each subsequent phase adds deeper integration while remaining non-intrusive to users who don't do benchmark work.

The ultimate vision: any Claude Code user who runs a performance test gets the benefit of skeptical analysis, fair comparison enforcement, and long-running operation management — without learning any new commands or changing their workflow.
