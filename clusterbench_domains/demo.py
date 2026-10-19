# SPDX-License-Identifier: Apache-2.0
"""DemoDomain — a tiny, dependency-free reference domain.

Template for new domains and for exercising the engine (cache, launchers, loop
guard) without a cluster or native library. Deterministic: a lower treatment
value is modeled as faster. Implements the optional prep-persistence hooks
(build_key / save_prep / load_prep / prep_descriptor) so the engine can cache
its prep across runs/sessions.
"""

from __future__ import annotations

import json
from pathlib import Path

from clusterbench_core.domain import MeasureOutcome, PrepArtifact
from clusterbench_core.model import BenchmarkConfig, PhaseMetrics

# Module-level counter so tests can detect whether prep actually (re)built.
BUILD_COUNT = 0


class DemoDomain:
    name = "demo"
    measure_import = "clusterbench_domains.demo:DemoDomain"  # no-arg → subprocess-measurable

    def required_params(self) -> dict:
        return {}

    def apply_config(self, cfg: BenchmarkConfig, ctx) -> dict:
        return {"note": "demo domain; nothing to apply"}

    def verify_config(self, cfg: BenchmarkConfig, ctx):
        return {}

    # --- prep caching hooks ---
    def build_key(self, cfg: BenchmarkConfig) -> tuple:
        return ("demo", cfg.get("demo.n", 1000))

    def prep(self, cfg: BenchmarkConfig, ctx) -> PrepArtifact:
        global BUILD_COUNT
        BUILD_COUNT += 1
        return PrepArtifact(kind="demo", meta={"n": cfg.get("demo.n", 1000), "sig": cfg.signature()})

    def prep_descriptor(self, artifact: PrepArtifact) -> dict:
        return {"n": artifact.meta.get("n")}

    def save_prep(self, artifact: PrepArtifact, path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        (path / "artifact.json").write_text(json.dumps(artifact.meta))

    def load_prep(self, path) -> PrepArtifact:
        from clusterbench_core.engine.cache import StaleArtifact

        path = Path(path)
        meta = json.loads((path / "artifact.json").read_text())
        # Verify the loaded artifact matches the stored descriptor (catches a
        # silently-changed/rebuilt cached artifact — the StaleArtifact guarantee).
        desc_file = path / "descriptor.json"
        if desc_file.exists():
            desc = json.loads(desc_file.read_text())
            if desc.get("n") != meta.get("n"):
                raise StaleArtifact(f"cached demo artifact n={meta.get('n')} != descriptor {desc.get('n')}")
        return PrepArtifact(kind="demo", meta=meta)

    def measure(self, cfg: BenchmarkConfig, prep: PrepArtifact, ctx) -> MeasureOutcome:
        v = float(cfg.treatment_variable.value)
        p50 = round(10.0 + 5.0 * v, 4)  # higher value -> slower
        return MeasureOutcome(
            metrics={"p50_ms": p50, "peak_rss_kb": 1000},
            phases=[PhaseMetrics(name="measure", duration_s=p50 / 1000, peak_rss_kb=1000)],
            functional_validation={"passed": True, "recall@10": 0.98},
        )
