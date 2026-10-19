# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from benchmark_engine.discipline.manifest import load_manifest

ROOT = Path(__file__).resolve().parents[1] / "benchmark_domains"


def test_warmup_is_a_controlled_param_in_both_manifests():
    assert "seismic.warmup" in load_manifest(ROOT / "seismic" / "required_params.yaml")
    assert "query.warmup" in load_manifest(ROOT / "opensearch" / "required_params.yaml")
