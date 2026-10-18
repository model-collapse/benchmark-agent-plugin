# SPDX-License-Identifier: Apache-2.0
"""Subprocess measurement entry point.

Runs a domain's measure() in a fresh process so peak RSS is per-trial
attributable (not a shared-process high-water mark). The domain is reconstructed
by import path (no-arg constructible) and the prep artifact is loaded from the
persisted cache dir — so step inputs stay JSON-serializable.
"""

from __future__ import annotations

import importlib
import json

from clusterbench_core.engine.effective import EffectiveRecorder
from clusterbench_core.model import BenchmarkConfig


def run_measure(config_json: str, domain_import: str, idx: dict) -> dict:
    cfg = BenchmarkConfig.from_dict(json.loads(config_json))
    mod, _, cls = domain_import.partition(":")
    domain = getattr(importlib.import_module(mod), cls)()
    recorder = EffectiveRecorder()
    art = domain.load_prep(idx["cache_dir"])
    out = domain.measure(cfg, art, recorder)
    return {
        "metrics": out.metrics,
        "phases": [p.to_dict() for p in out.phases],
        "effective_params": recorder.params,
        "outputs": {"functional_validation": out.functional_validation},
    }
