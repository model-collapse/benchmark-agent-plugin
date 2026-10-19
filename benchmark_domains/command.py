# SPDX-License-Identifier: Apache-2.0
"""CommandDomain — a generic Domain whose prep/measure are declared as shell
command *stages* forming a DAG.

One abstraction benchmarks anything: retrieval (build→search), embedding
(train→eval), LLM (data_prep→train→eval). ``kind: prep`` stages are deterministic
and signature-cached (reused across trials/sessions when a stable ``workroot`` is
given); ``kind: measure`` stages always re-run and their metrics become the run's
metrics. Dependencies are declared with ``needs:``; produced files flow by name.

CommandDomain implements the existing ``Domain`` protocol by running its prep
stages inside ``prep()`` and its measure stages inside ``measure()``, both over
the engine's ``Scheduler`` + on-disk ``SignatureCache``.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"\{([A-Za-z_][\w.]*)\}")

from benchmark_engine.discipline.manifest import ManifestEntry
from benchmark_engine.domain import MeasureOutcome, PrepArtifact
from benchmark_engine.engine.cache import SignatureCache
from benchmark_engine.engine.launcher import InProcessLauncher
from benchmark_engine.engine.scheduler import Scheduler
from benchmark_engine.engine.step import Step, StepRef
from benchmark_engine.model import BenchmarkConfig
from benchmark_ops.command import run_command_stage


def _artifact_path(dep_outputs: dict, name: str) -> str:
    """Resolve a produced artifact's path from an upstream step's outputs,
    whether it ran (``outputs[name]``) or was a cache hit (``cache_dir/name``)."""
    if name in dep_outputs:
        return dep_outputs[name]
    cache_dir = dep_outputs.get("cache_dir")
    if cache_dir:
        return str(Path(cache_dir) / name)
    raise KeyError(f"artifact {name!r} not found in upstream outputs")


class CommandDomain:
    def __init__(self, spec: dict, name: str = "command", workroot: str | None = None):
        self.spec = spec
        self.name = name
        self.workroot = Path(workroot) if workroot else Path(tempfile.mkdtemp(prefix="cmddomain_"))
        self.workroot.mkdir(parents=True, exist_ok=True)
        self._cache = SignatureCache(self.workroot / "_command_cache")
        self._stages = {s["name"]: s for s in spec.get("stages", [])}
        self._produces = {s["name"]: list(s.get("produces", [])) for s in spec.get("stages", [])}

    # ---- Domain protocol ----
    def required_params(self) -> dict:
        out: dict[str, ManifestEntry] = {}
        for p, raw in (self.spec.get("required_params") or {}).items():
            raw = raw or {}
            out[p] = ManifestEntry(
                path=p, reason=raw.get("reason", ""), incident=raw.get("incident", ""),
                default=raw.get("default"), baseline_value=raw.get("baseline_value"),
                verify=raw.get("verify", ""), impact_if_drift=raw.get("impact_if_drift", ""))
        return out

    def validate(self, cfg: BenchmarkConfig) -> list[str]:
        """Static DAG checks (run in preflight before any stage): unknown `needs`,
        cycles, and `{placeholder}` tokens that are neither a declared param nor an
        artifact produced by some stage."""
        errors: list[str] = []
        names = set(self._stages)
        produced = {a for arts in self._produces.values() for a in arts}
        valid_tokens = set(cfg.params) | produced

        for s in self.spec.get("stages", []):
            for dep in s.get("needs", []):
                if dep not in names:
                    errors.append(f"stage {s['name']!r} needs unknown stage {dep!r}")
            scan = [s.get("cmd", "")]
            for key in ("metrics_from", "effective_from"):
                if isinstance(s.get(key), dict) and s[key].get("file"):
                    scan.append(s[key]["file"])
            for text in scan:
                for tok in _TOKEN.findall(text):
                    if tok not in valid_tokens:
                        errors.append(f"stage {s['name']!r} references unknown placeholder {{{tok}}}")

        # cycle detection over the needs-graph
        edges = {s["name"]: [d for d in s.get("needs", []) if d in names]
                 for s in self.spec.get("stages", [])}
        done, stack = set(), set()

        def _visit(n):
            if n in done:
                return False
            if n in stack:
                return True
            stack.add(n)
            cyc = any(_visit(m) for m in edges.get(n, []))
            stack.discard(n)
            done.add(n)
            return cyc

        if any(_visit(n) for n in edges):
            errors.append("stage DAG has a cycle")
        return errors

    def apply_config(self, cfg: BenchmarkConfig, ctx: Any) -> dict:
        return {}

    def verify_config(self, cfg: BenchmarkConfig, ctx: Any) -> dict:
        return {}

    def prep(self, cfg: BenchmarkConfig, ctx: Any) -> PrepArtifact:
        prep_stages = [s for s in self.spec.get("stages", []) if s.get("kind", "prep") == "prep"]
        results = self._run_stages(prep_stages, cfg, upstream_artifacts={}, ctx=ctx)
        artifacts: dict[str, str] = {}
        for s in prep_stages:
            out = results[s["name"]].outputs
            for name in self._produces[s["name"]]:
                artifacts[name] = _artifact_path(out, name)
        return PrepArtifact(kind="command", meta={"artifacts": artifacts})

    def measure(self, cfg: BenchmarkConfig, prep: PrepArtifact, ctx: Any) -> MeasureOutcome:
        measure_stages = [s for s in self.spec.get("stages", []) if s.get("kind") == "measure"]
        upstream = dict(prep.meta.get("artifacts", {}))
        results = self._run_stages(measure_stages, cfg, upstream_artifacts=upstream, ctx=ctx)
        metrics: dict[str, Any] = {}
        for s in measure_stages:
            metrics.update(results[s["name"]].metrics or {})
        fv = {"passed": True}
        if "passed" in metrics:
            fv["passed"] = metrics.pop("passed")
        return MeasureOutcome(metrics=metrics, phases=[], functional_validation=fv)

    # ---- engine wiring ----
    def _run_stages(self, stages: list[dict], cfg: BenchmarkConfig, upstream_artifacts: dict, ctx: Any = None):
        if not stages:
            return {}
        params = {p: cfg.get(p) for p in cfg.params}
        local_names = {s["name"] for s in stages}
        steps = [self._to_step(s, params, upstream_artifacts, local_names) for s in stages]
        subdir = "prep" if stages[0].get("kind", "prep") == "prep" else "measure"
        results = Scheduler(InProcessLauncher(), cache=self._cache).run(steps, self.workroot / subdir)
        # fail loud: a stage that crashed or produced unparseable metrics must abort
        # the run (not be silently dropped into an empty-metrics "success").
        for sname, r in results.items():
            if r.status != "COMPLETED":
                raise RuntimeError(f"command stage {sname!r} did not complete: {r.error}")
        self._capture_effective(stages, subdir, ctx, results)
        return results

    def _capture_effective(self, stages, subdir, ctx, results):
        """Gate 1: record each stage's point-of-use resolved config so the
        effective-vs-declared gate can see a value the command actually used."""
        if ctx is None or not hasattr(ctx, "effective"):
            return
        for s in stages:
            ef = s.get("effective_from")
            if not (isinstance(ef, dict) and ef.get("file")):
                continue
            p = Path(ef["file"])
            if not p.is_absolute():
                p = self.workroot / subdir / s["name"] / ef["file"]
            if not p.exists():
                cache_dir = (results.get(s["name"]).outputs or {}).get("cache_dir")
                if cache_dir:
                    p = Path(cache_dir) / ef["file"]
            if p.exists():
                for k, v in (json.loads(p.read_text()) or {}).items():
                    ctx.effective(k, v)

    def _to_step(self, stage: dict, params: dict, upstream_artifacts: dict, local_names: set) -> Step:
        name = stage["name"]
        cmd = stage["cmd"]
        needs = list(stage.get("needs", []))
        produces = self._produces[name]
        metrics_from = stage.get("metrics_from")
        cacheable = stage.get("kind", "prep") == "prep"
        parallel_safe = bool(stage.get("parallel"))
        referenced = {p: v for p, v in params.items() if ("{" + p + "}") in cmd}

        # Only same-run deps get a StepRef (so the scheduler topo-orders them);
        # deps from an earlier phase (prep → measure) are already resolved and
        # supplied via `upstream_artifacts`.
        inputs = {dep: StepRef(dep) for dep in needs if dep in local_names}

        def fn(**resolved):
            arts = dict(upstream_artifacts)
            for dep in needs:
                dep_out = resolved.get(dep)
                if not dep_out:   # upstream-phase dep: already in upstream_artifacts
                    continue
                for art_name in self._produces.get(dep, []):
                    arts[art_name] = _artifact_path(dep_out, art_name)
            wd = self.workroot / ("prep" if cacheable else "measure") / name
            return run_command_stage(cmd, params, arts, workdir=str(wd),
                                     produces=produces, metrics_from=metrics_from)

        cache_key = self._prep_key(name, params, {}) if cacheable else None
        return Step(name=name, fn=fn, inputs=inputs, cache_key=cache_key,
                    cacheable=cacheable, parallel_safe=parallel_safe)

    def _prep_key(self, name: str, params: dict, memo: dict) -> tuple:
        """Content identity of a prep stage, INCLUDING its upstream prep stages'
        identities (recursively). Without the upstream keys a downstream stage
        whose own cmd/params/needs are unchanged would be a false cache HIT when an
        upstream artifact's content changed (e.g. a param only the upstream cmd
        references) — serving a stale artifact across a tuning sweep."""
        if name in memo:
            return memo[name]
        stage = self._stages[name]
        cmd = stage["cmd"]
        referenced = tuple(sorted((p, v) for p, v in params.items() if ("{" + p + "}") in cmd))
        upstream = tuple(
            self._prep_key(dep, params, memo)
            for dep in sorted(stage.get("needs", []))
            if dep in self._stages and self._stages[dep].get("kind", "prep") == "prep")
        key = (name, cmd, referenced, upstream)
        memo[name] = key
        return key
