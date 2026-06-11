# Domain Required-Parameters Manifests

This directory holds per-domain `required_params.yaml` files. Each manifest is the agent's growing checklist of parameters that **any run in this domain must declare**, regardless of whether prior runs declared them.

## Why this layer exists

The structured config schema's parameter alignment check has a coverage gap: if a baseline run never listed parameter X (because X was at default), a follow-up run isn't required to list X either. **Defaults are invisible to the alignment check.**

Domain manifests close this gap. They are the "things that have ever surprised us" list. Once a parameter ends up here, every future run in that domain must explicitly declare its value — even if the value is the system default.

## Lifecycle of a manifest entry

1. **Incident** — A run is invalidated or produces unexplained results because of a silent parameter change.
2. **Forensic identification** — Investigation finds the smoking-gun parameter (e.g., the eviction-merge slowdown traced to `max_thread_count`/`max_merge_count`/`auto_throttle`).
3. **Promotion** — The parameter is added to the appropriate `<domain>/required_params.yaml` with:
   - `since:` date of promotion
   - `incident:` the run ID that forced this entry
   - `reason:` short rationale
   - `default:` the system default (for awareness)
   - `baseline_value:` the value the most recent RELIABLE run used
   - `verify:` a command to read the current actual value
   - `impact_if_drift:` what goes wrong if the value silently changes
4. **Enforcement** — All future plans in this domain MUST declare this parameter in their `config.yaml`.

## Agent behavior

### At plan time

```
1. Determine the run's domain (e.g., "opensearch_forcemerge")
2. Load domains/<domain>/required_params.yaml
3. For each required parameter:
   a. Check config.yaml declares it (in any section)
   b. If missing → BLOCK the plan, output:
      "Domain manifest requires <param>. Add it to config.yaml.
       Suggested value from baseline: <baseline_value>
       Reason: <reason>
       Verify: <verify command>"
4. Generate config.yaml with ALL manifest params present
```

### At preflight

```
1. Run each `verify` command against the actual cluster
2. Compare actual to declared
3. If mismatch → BLOCK execution, force reconciliation
```

### At post-run

```
1. Snapshot actual cluster + index settings to artifacts/
2. Diff against baseline run's snapshots
3. Any parameter that drifted but isn't in the manifest → flag for review
   (candidate for promotion to the manifest)
```

## Manifest vs config.yaml

| Aspect | Manifest | config.yaml |
|--------|----------|-------------|
| Scope | Domain-wide | Single run |
| Lifetime | Permanent (entries grow) | Run-specific |
| Authority | "These MUST be declared" | "This is what was declared" |
| Source | Forensic + expert knowledge | Plan + alignment check |
| Update | When a new failure mode is found | Per run |

## Adding a new domain

1. Create directory: `domains/<new_domain>/`
2. Add `required_params.yaml` following the schema in any existing manifest
3. Reference the domain in run `config.yaml` via top-level `domain:` field

## Existing domains

- `opensearch_forcemerge/` — OpenSearch sparse vector force-merge benchmarks (RSS, build time, search latency)
