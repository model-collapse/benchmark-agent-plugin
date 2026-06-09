# Benchmark Agent Plugin for Claude Code

An autonomous benchmark agent that plans, executes, monitors, and analyzes performance experiments on distributed systems. Produces reproducible results with honest, evidence-backed conclusions.

## Install

```bash
# Add the marketplace
/plugin marketplace add model-collapse/benchmark-agent-plugin

# Install the plugin
/plugin install benchmark-agent@benchmark-tools
```

Or install directly from repo:
```bash
/plugin marketplace add model-collapse/benchmark-agent-plugin
```

## Skills Included

| Skill | Command | Purpose |
|-------|---------|---------|
| **benchmark_agent** | `/benchmark_agent` | Brain — plans, validates, generates scripts, analyzes results, manages history |
| **benchmark_run** | `/benchmark_run` | Muscle — launches nohup scripts, monitors via `/loop`, detects completion |

## How It Works

```
You: "benchmark force merge with the new eviction fix"
  → /benchmark_agent activates automatically
  → Loads prior run history and lessons
  → Challenges if request is misaligned with context
  → Produces run plan with comparison matrix
  → Generates execution/monitor/check scripts
  → You approve

You: "run it"
  → /benchmark_run launches nohup scripts
  → Starts /loop for periodic check-in
  → You can close your session

[Hours later, benchmark completes]
  → Loop detects completion signal
  → Triggers /benchmark_agent analyze
  → Skeptical analysis protocol runs
  → Report produced with mandatory "What Went Wrong" section
  → Results index updated with reliability tag
```

## Core Principles

| Principle | Meaning |
|-----------|---------|
| **Fair Comparison** | Only the treatment variable changes between runs |
| **Memory Continuity** | Every run inherits full context of prior runs |
| **Safety First** | Validate hardware capacity before execution |
| **Skeptical Analysis** | Good results get more scrutiny, not less |
| **Honest Reporting** | All findings reported — especially inconvenient ones |
| **Root Cause Depth** | No guessing. Trace causation, not correlation |

## Key Features

- **Challenge Protocol** — Agent pushes back on misaligned requests before wasting hours on confounded runs
- **Reliability Tags** — Every run classified as RELIABLE / QUALIFIED / UNRELIABLE / EXPLORATORY
- **Session Resilience** — Benchmark scripts survive session death via nohup; reconnect with `/benchmark_run resume`
- **Skeptical Analysis** — Different protocols for good vs bad results (good results get MORE scrutiny)
- **Mandatory "What Went Wrong" Section** — Reports without this section are rejected
- **Physical Artifact Verification** — Catches logical vs physical file format mismatches
- **Phase Decomposition** — Instruments per-phase to reveal true bottlenecks
- **Resource Budget** — Computes worst-case before execution to prevent OOM

## Data Directory

The plugin uses `$BENCHMARK_HOME` (defaults to `./benchmark_data/` in your project):

```
benchmark_data/
  results_index.md          — Single source of truth for all runs
  lessons.md                — Accumulated lessons (append-only)
  risks.md                  — Known fragilities and scaling limits
  runs/
    run_<date>_<slug>.md    — Individual run records
  plans/
    plan_<date>_<slug>.md   — Approved run plans
  scripts/
    execute_<id>.sh         — Generated execution scripts
    monitor_<id>.sh         — Generated resource monitors
    check_<id>.sh           — Generated status check scripts
  monitors/
    <id>_monitor.log        — CSV resource metrics
    <id>_events.log         — Phase transitions
    <id>.running            — Active run signal
    <id>.complete           — Completion signal
    <id>.failed             — Failure signal
  settings/
    <system>_settings.md    — Environment configs
```

## Configuration

Set `BENCHMARK_HOME` environment variable to customize the data directory:
```bash
export BENCHMARK_HOME=/path/to/your/benchmark_data
```

Or leave unset — defaults to `./benchmark_data/` relative to your project root.

## Origin

Built from lessons learned running force-merge/RSS/latency benchmarks on a 138M-doc SEISMIC sparse vector index across 3-node clusters. Every feature exists because its absence caused a real problem:

- Comparison matrix: prevented by segment-count confound that nearly discarded a correct fix
- Challenge protocol: prevented by a misaligned run that wasted 5+ hours
- Reliability tags: prevented by citing an invalidated run as baseline
- Physical artifact verification: prevented by 20 GB blind spot from compound file formats
- Skeptical analysis: prevented by celebrating results that hid 6 bugs

See `BENCHMARK_LESSONS_LEARNED.md` for the full story.

## License

Apache-2.0
