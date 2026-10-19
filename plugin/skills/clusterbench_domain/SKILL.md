---
name: clusterbench_domain
description: Author a new ClusterBench domain — a concrete system to benchmark (a database, index, service) — implementing the Domain protocol and its required-params manifest. Use when adding support for a system beyond OpenSearch/SEISMIC.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
user-invocable: true
argument-hint: <domain_name> — e.g. "elasticsearch" or "qdrant"
---

# ClusterBench Domain Authoring

A domain is the seam between the generic engine and a concrete system. Implement
the `benchmark_engine.domain.Domain` protocol. Template: `benchmark_domains/demo.py`
(minimal) and `benchmark_domains/seismic/` or `.../opensearch/` (real).

## Required pieces

### 1. The Domain class
```python
class MyDomain:
    name = "mydomain"
    def required_params(self): ...          # load_manifest(path-to-required_params.yaml)
    def apply_config(self, cfg, ctx): ...    # Phase B: push settings to the live system
    def verify_config(self, cfg, ctx): ...   # Phase C: {param: (declared, observed, ok)}
    def prep(self, cfg, ctx): ...            # cacheable deterministic build -> PrepArtifact
    def measure(self, cfg, prep, ctx): ...   # always-run -> MeasureOutcome(metrics, phases, functional_validation)
```
Rules:
- `prep` must be deterministic and keyed only by *build* parameters so a sweep
  over a *search* parameter reuses one build (cache the artifact in the domain).
- `measure` MUST include a **warm-up pass** before timing (cold caches invert
  results) and MUST return `functional_validation={"passed":bool, "recall@10":...}`.
- `apply_config`/`verify_config` implement real Phase B/C for live systems; a pure
  library domain may return `{}` from `verify_config` (fidelity is guaranteed
  because prep reads params straight from the config).

### 2. required_params.yaml (the manifest)
List every parameter whose silent change would make a comparison uninterpretable,
each with `reason`, `default`, `baseline_value`, and `verify`. A parameter earns
its place when a prior run was invalidated by changing it silently. Entries are
added, never removed.

### 3. Register + test
Export from `benchmark_domains/<name>/__init__.py`. Add a happy-path test
(mark `happy`) that builds a tiny real index and asserts a `Tuner` **search**
(grid/refine/coordinate) recommends a faster configuration within the recall
floor — not just one successful run (L3) — mirroring `tests/test_happy_seismic.py`.

## Verify
```bash
python -m pytest tests/ -q -m "not happy"          # engine + discipline still green
python -m pytest tests/ -q -m happy -k mydomain     # your real smoke
```
