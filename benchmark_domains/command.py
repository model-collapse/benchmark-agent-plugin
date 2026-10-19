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

import tempfile
from pathlib import Path
from typing import Any

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

    def apply_config(self, cfg: BenchmarkConfig, ctx: Any) -> dict:
        return {}

    def verify_config(self, cfg: BenchmarkConfig, ctx: Any) -> dict:
        return {}

    def prep(self, cfg: BenchmarkConfig, ctx: Any) -> PrepArtifact:
        prep_stages = [s for s in self.spec.get("stages", []) if s.get("kind", "prep") == "prep"]
        results = self._run_stages(prep_stages, cfg, upstream_artifacts={})
        artifacts: dict[str, str] = {}
        for s in prep_stages:
            out = results[s["name"]].outputs
            for name in self._produces[s["name"]]:
                artifacts[name] = _artifact_path(out, name)
        return PrepArtifact(kind="command", meta={"artifacts": artifacts})

    def measure(self, cfg: BenchmarkConfig, prep: PrepArtifact, ctx: Any) -> MeasureOutcome:
        measure_stages = [s for s in self.spec.get("stages", []) if s.get("kind") == "measure"]
        upstream = dict(prep.meta.get("artifacts", {}))
        results = self._run_stages(measure_stages, cfg, upstream_artifacts=upstream)
        metrics: dict[str, Any] = {}
        for s in measure_stages:
            metrics.update(results[s["name"]].metrics or {})
        fv = {"passed": True}
        if "passed" in metrics:
            fv["passed"] = metrics.pop("passed")
        return MeasureOutcome(metrics=metrics, phases=[], functional_validation=fv)

    # ---- engine wiring ----
    def _run_stages(self, stages: list[dict], cfg: BenchmarkConfig, upstream_artifacts: dict):
        if not stages:
            return {}
        params = {p: cfg.get(p) for p in cfg.params}
        local_names = {s["name"] for s in stages}
        steps = [self._to_step(s, params, upstream_artifacts, local_names) for s in stages]
        subdir = "prep" if stages[0].get("kind", "prep") == "prep" else "measure"
        return Scheduler(InProcessLauncher(), cache=self._cache).run(steps, self.workroot / subdir)

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

        cache_key = (name, cmd, tuple(sorted(referenced.items())), tuple(sorted(needs))) if cacheable else None
        return Step(name=name, fn=fn, inputs=inputs, cache_key=cache_key, cacheable=cacheable)
