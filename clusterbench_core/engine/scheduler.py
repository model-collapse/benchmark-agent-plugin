# SPDX-License-Identifier: Apache-2.0
"""DAG scheduler: topo-order the steps, run independent cacheable steps in
parallel, run measurement (non-cacheable) steps serialized (never overlapping any
other step — timing/RSS under contention is not comparable), consult the on-disk
cache before launching, and propagate a failed dependency to its dependents.
"""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clusterbench_core.engine.cache import SignatureCache
from clusterbench_core.engine.signature import signature
from clusterbench_core.engine.step import Step, StepRef, StepResult, edges


def _resolve(value, results: dict[str, StepResult]):
    if isinstance(value, StepRef):
        return results[value.step_name].outputs
    if isinstance(value, list):
        return [_resolve(v, results) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, results) for k, v in value.items()}
    return value


def _step_sig(step: Step) -> str:
    return signature({"name": step.name, "key": list(step.cache_key or ())})


class Scheduler:
    def __init__(self, launcher, cache: SignatureCache | None = None, max_parallel: int = 4,
                 measure_launcher=None):
        self.launcher = launcher
        self.cache = cache
        self.max_parallel = max_parallel
        # optional launcher for non-cacheable (measurement) steps — e.g. a subprocess
        # launcher so RSS is per-trial attributable
        self.measure_launcher = measure_launcher

    def run(self, steps: list[Step], workroot: str | Path) -> dict[str, StepResult]:
        workroot = Path(workroot)
        by_name = {s.name: s for s in steps}
        deps = edges(steps)
        results: dict[str, StepResult] = {}
        done: set[str] = set()
        remaining = set(by_name)

        while remaining:
            ready = [n for n in remaining if deps[n] <= done]
            if not ready:
                raise RuntimeError(f"dependency cycle or unresolved deps among {remaining}")

            # dependents of a failed/aborted step fail without launching
            for n in list(ready):
                if any(results[d].status != "COMPLETED" for d in deps[n]):
                    results[n] = StepResult(status="FAILED", error="upstream failed")
                    done.add(n)
                    remaining.discard(n)
                    ready.remove(n)

            cacheable = [n for n in ready if by_name[n].cacheable]
            measurement = [n for n in ready if not by_name[n].cacheable]

            # cacheable: parallel
            if cacheable:
                with ThreadPoolExecutor(max_workers=max(1, self.max_parallel)) as ex:
                    for n, r in zip(cacheable, ex.map(lambda n: self._run_one(by_name[n], results, workroot), cacheable)):
                        results[n] = r
            # measurement: serialized, strictly after cacheables in this wave
            for n in measurement:
                results[n] = self._run_one(by_name[n], results, workroot)

            done |= set(ready)
            remaining -= set(ready)

        return results

    def _run_one(self, step: Step, results: dict[str, StepResult], workroot: Path) -> StepResult:
        inputs = {k: _resolve(v, results) for k, v in step.inputs.items()}
        wd = workroot / step.name

        if step.cacheable and self.cache is not None:
            sig = _step_sig(step)
            if self.cache.has(step.name, sig):
                return StepResult(
                    status="COMPLETED",
                    outputs={"cache_dir": str(self.cache.path_for(step.name, sig)), "cached": True},
                )

        launcher = self.measure_launcher if (not step.cacheable and self.measure_launcher) else self.launcher
        r = launcher.run(step, inputs, wd)

        if step.cacheable and self.cache is not None and r.status == "COMPLETED":
            sig = _step_sig(step)
            desc = r.outputs.get("descriptor", {})
            self.cache.store(step.name, sig, desc, lambda dst: _copy_into(wd, dst))
            r.outputs["cache_dir"] = str(self.cache.path_for(step.name, sig))
        return r


def _copy_into(src: Path, dst: Path) -> None:
    src = Path(src)
    if not src.exists():
        return
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
