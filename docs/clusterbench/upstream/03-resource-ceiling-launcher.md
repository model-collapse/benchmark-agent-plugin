# experimaestro — feature proposal: memory/resource ceiling for local launchers (OOM guard)

**Type:** feature proposal (with a reference implementation to upstream)
**Version observed:** experimaestro 2.7.0

## Motivation

For benchmarking / heavy jobs on a single host (the Direct launcher over a Local
connector), a task that over-allocates can OOM-kill the whole machine. On Slurm
this is handled by cgroup `--mem`, but experimaestro's local launcher has no
equivalent:

- `Launcher.__init__(self, connector, *, priority=0)` — no resource spec.
- `tokens` exist, but they are **concurrency semaphores** (count-based admission),
  not a memory watchdog.

So there is no built-in way to say "kill this job if its RSS exceeds N GB" when
running locally — the exact protection a benchmarking workload needs.

## Proposal

Add an optional per-job **resource ceiling** to the local launcher, enforced by a
lightweight monitor thread that polls the job process tree's RSS and escalates
`SIGTERM → SIGKILL` on a sustained breach:

```python
launcher = LocalLauncher(memory_limit="0.85 of total",   # or absolute "64g"
                         on_breach="terminate")           # warn | terminate
```

Thresholds as fractions of host RAM (warn / hard / emergency), sustained-sample
debouncing to avoid transient spikes, and an event log of guard actions.

## Reference implementation (willing to upstream)

We built exactly this in ClusterBench (`clusterbench_core/guard.py`, GPL-3.0 —
compatible with experimaestro's GPL-3.0):

- `OOMGuard(budget).observe(rss_kb) -> OK | WARN | HARD_KILL | EMERGENCY_KILL`
  — pure, debounced decision logic (unit-tested).
- `monitor_process(pid, budget, interval, on_event)` — polls the process tree
  via `psutil`, escalates `SIGTERM`→`SIGKILL`, returns the terminal action
  (tested against a real over-budget subprocess).

Thresholds derive from a budget (`warn 0.75 / hard 0.85 / emergency 0.92` of
total RAM by default). This maps cleanly onto a `LocalLauncher` option and would
give local runs parity with Slurm's memory enforcement.

Happy to adapt the API to experimaestro's launcher conventions and send a PR if
the maintainers are interested.
