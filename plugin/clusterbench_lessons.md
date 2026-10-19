# ClusterBench Lessons

Append-only record of incidents that invalidated or complicated a benchmark, and
the rule each one produced. The experiment-awareness hook surfaces this file, and
`clusterbench_plan` cites these IDs in its Forbidden list. Add an entry whenever a
run teaches something; never delete.

## L1 — Cold-cache / measurement-ordering confound (2026-10-16)
The first sweep point measured after an index build/force-merge pays cold page +
query caches, which **inverted** the result: aggressive query pruning looked
*slower* than the full query (5.07 ms vs 2.6 ms) purely because it ran first.
**Rule:** every `measure()` runs a warm-up pass (untimed) before timing; never
report a speedup without it. Status: fixed in both domains + enforced in the
domain-authoring skill.

## L2 — A knob that costs quality but doesn't move speed (2026-10-16)
Query-term pruning on OpenSearch at ~2–20k docs did not reduce p50 (latency was
dominated by request overhead, not clause count) — it only lowered recall. The
real speed knob was `forcemerge.max_num_segments` (16→1 ≈ 1.8–3.9× faster at equal
recall). **Rule:** before adopting a knob as a "speed optimization," confirm it
moves the *primary* metric at the target scale, not just the quality metric.

## L3 — A single successful run is not a benchmark (2026-10-16)
A happy path must be a **tuning search** that explores a space and recommends a
configuration with a measured improvement — not one successful run. **Rule:** use
`clusterbench_core.tuning.Tuner` (grid / refine / coordinate); report the
trajectory + recommended config + improvement. Status: `Tuner` added; experiments
and skills updated.

## L4 — Always tear down clusters in `finally` (2026-10-16)
A smoke test that errored *before* its teardown line leaked an OpenSearch
container ("Up 20 minutes" stray). **Rule:** cluster lifecycle must be in a
`try/finally` (or context manager); `clusterbench_run` verifies `docker ps` after
a run.

## L5 — task workers don't inherit the launcher's import path (2026-10-16, SUPERSEDED)
A worker that imports a module *by name* fails with `ModuleNotFoundError` unless the
import roots are propagated. **Superseded by the native engine:** experimaestro and
`clusterbench_core/xpm.py` were removed; the native `LocalProcessLauncher` sets
`PYTHONPATH` to the repo root when it spawns the worker subprocess
(`clusterbench_core/engine/launcher.py`), so the step module is always importable
and this class of failure is designed out rather than worked around. Kept as the
rationale for that design choice.

## Domain-specific gotchas
- **SEISMIC:** token arrays must be numpy `dtype='U30'` (`seismic.get_seismic_string()`)
  or you get an opaque `PyArray` conversion error; `pyseismic-lsr` needs Rust ≥1.99
  (`float_algebraic`). The PyPI name `seismic` is an unrelated seismology package.
- **OpenSearch:** `opensearch-py` calls require keyword args (`index=...`); set
  `number_of_replicas=0` on a single node to reach green.
