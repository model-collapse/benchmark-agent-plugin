# Bring Your Own Experiment: the `Domain` API

ClusterBench is an **experiment harness**. You wrap *your* system (a retriever, a
reranker, a vector DB, any benchmarkable thing) in a `Domain`; the harness gives
you — for free — fair comparison, a required-params gate, preflight, an OOM guard,
the two fairness gates (frozen config + effective-param integrity), replication,
reproduction, provenance/fingerprint, the tuner, cross-session caching, the loop
guard, and honest persisted reports. The harness is **metric-agnostic**: you name
your own primary/quality metrics and emit whatever metrics you like.

## Minimal Domain (5 methods — everything else is optional)

```python
from benchmark_engine.domain import MeasureOutcome, PrepArtifact
from benchmark_engine.model import PhaseMetrics

class MyDomain:
    name = "mysystem"

    def required_params(self): return {}            # or load_manifest(path) for a HARD gate
    def apply_config(self, cfg, ctx): return {}      # Phase B: push settings to the live system
    def verify_config(self, cfg, ctx): return {}     # Phase C: {param: (declared, observed, ok)}; {} = skip
    def prep(self, cfg, ctx) -> PrepArtifact:        # deterministic build (index, corpus, ...)
        return PrepArtifact(kind="mysystem", handle=my_built_thing)
    def measure(self, cfg, prep, ctx) -> MeasureOutcome:
        eff = getattr(ctx, "effective", lambda n, v: v)      # capture AT POINT OF USE (Gate 1)
        topk = eff("mysystem.topk", int(cfg.get("mysystem.topk")))
        # ... run your experiment, time it, compute your quality metric ...
        return MeasureOutcome(
            metrics={"p50_ms": p50, "qps": qps, "ndcg@10": ndcg},   # any metrics you want
            phases=[PhaseMetrics(name="search", duration_s=t)],
            functional_validation={"passed": ndcg > 0, "ndcg@10": ndcg},  # you decide `passed`
        )
```

Run it:
```python
from benchmark_engine.tuning import Tuner, TuneDim
tuner = Tuner(base_cfg, MyDomain(), workdir, primary_metric="p50_ms", minimize=True,
              quality_metric="ndcg@10", quality_floor=0.40,
              replicates=7,                       # noise-band selection (Gate 2)
              measure_in_subprocess=True)         # attributable RSS
res = tuner.grid(TuneDim("mysystem.topk", values=[10, 50, 100, 200]))
print(res.render()); print("recommended:", res.recommendation)
```

### Capture effective params AT POINT OF USE (the one rule that matters)
Record each identity-bearing param with `ctx.effective(name, value)` **where the
value is actually consumed**, not by re-reading the config — otherwise an adaptive
clamp is invisible and the fairness gate is defeated. Declared ≠ effective ⇒ the
run is auto-tagged UNRELIABLE.

## Optional hooks (opt in for more harness power)

| Method / attribute | Enables |
|---|---|
| `required_params()` → `load_manifest(path)` | the **manifest HARD gate** — every listed param must be declared |
| `build_key(cfg)` + `save_prep(artifact, path)` + `load_prep(path)` + `prep_descriptor(artifact)` | **cross-session prep caching** keyed by build params (built once, reused); add `load_prep` verification for a `StaleArtifact` guard |
| `measure_import = "pkg.mod:MyDomain"` (no-arg) and/or `reconstruct(cache_dir)` | **subprocess measurement** → per-trial attributable RSS (`memory_comparable=True`) |
| config `reproduction_tolerances = {"ndcg@10": 0.01, "accuracy": {"tol": 0.01, "absolute": True}}` | your custom metric is **reproduction-gated** (RELIABLE requires it to reproduce). A float is a **relative** tolerance; `{"tol": x, "absolute": True}` is **absolute** — use absolute for metrics near zero or bounded in [0,1] (accuracy, recall) where relative is meaningless. The core defaults cover only generic `p50_ms`/`p95_ms`/`peak_rss_kb`; declare your own metrics here. |
| config `resource_budget = ResourceBudget(total_ram_kb=...)` | the OOM guard (SIGTERM→SIGKILL at the ceiling) |
| `controlled_variables` + a real `verify_config` | Phase C catches the live system drifting from the declared config |

## What you supply vs what the harness supplies
- **You:** the model/encoder, the dataset + qrels, the quality metric computation, the backend calls.
- **Harness:** everything about running it *fairly and reproducibly*, searching the config space, caching, and reporting.

See `benchmark_domains/demo.py` (minimal), `benchmark_domains/seismic/` and
`benchmark_domains/opensearch/` (full, with caching + subprocess measure) as
worked examples. Analyze results with
`benchmark_engine.report_index.load_runs(workdir)` → rows for pandas/notebook.
