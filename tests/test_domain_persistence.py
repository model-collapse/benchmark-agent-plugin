# SPDX-License-Identifier: Apache-2.0
"""Engine-level prep caching via domain save/load — reuse across runs/sessions."""

import clusterbench_domains.demo as demo
from clusterbench_domains.demo import DemoDomain
from clusterbench_core.lifecycle import run_lifecycle
from clusterbench_core.model import BenchmarkConfig, RunStatus, TreatmentVariable


def _cfg(knob):
    c = BenchmarkConfig(domain="demo", hypothesis="h",
                        treatment_variable=TreatmentVariable("demo.knob", 0.5, knob))
    c.set_param("demo.knob", knob)
    c.set_param("demo.n", 1000)
    return c


def test_prep_built_once_and_reused_across_runs(tmp_path):
    demo.BUILD_COUNT = 0
    r1 = run_lifecycle(_cfg(0.5), DemoDomain(), workdir=tmp_path)
    assert r1.result.status is RunStatus.COMPLETED
    assert demo.BUILD_COUNT == 1

    # Different treatment (measure differs) but identical build_key → prep reused.
    r2 = run_lifecycle(_cfg(0.9), DemoDomain(), workdir=tmp_path)
    assert r2.result.status is RunStatus.COMPLETED
    assert demo.BUILD_COUNT == 1          # NOT rebuilt — on-disk cache hit
    assert r2.result.metrics["p50_ms"] != r1.result.metrics["p50_ms"]  # measure still ran


def test_fresh_instance_reuses_on_disk_cache(tmp_path):
    demo.BUILD_COUNT = 0
    run_lifecycle(_cfg(0.5), DemoDomain(), workdir=tmp_path)      # instance 1 builds
    run_lifecycle(_cfg(0.5), DemoDomain(), workdir=tmp_path)      # fresh instance (new "session")
    assert demo.BUILD_COUNT == 1          # second fresh instance reused the on-disk artifact


def test_stale_cached_artifact_fails_loud(tmp_path):
    import json
    from pathlib import Path
    demo.BUILD_COUNT = 0
    run_lifecycle(_cfg(0.5), DemoDomain(), workdir=tmp_path)  # builds + caches
    # corrupt the cached artifact so it no longer matches its stored descriptor
    art = next(Path(tmp_path / "_cache").rglob("artifact.json"))
    art.write_text(json.dumps({"n": 999999}))
    lr = run_lifecycle(_cfg(0.9), DemoDomain(), workdir=tmp_path)  # same build_key -> hit -> load
    assert lr.result.status is RunStatus.FAILED  # StaleArtifact surfaced loudly, not silent


def test_cross_fingerprint_prep_reuse_refused(tmp_path):
    import json
    from pathlib import Path
    demo.BUILD_COUNT = 0
    run_lifecycle(_cfg(0.5), DemoDomain(), workdir=tmp_path)  # builds + stamps fingerprint
    fp = next(Path(tmp_path / "_cache").rglob("_fingerprint.json"))
    data = json.loads(fp.read_text()); data["code_version"] = "different-sha"; fp.write_text(json.dumps(data))
    lr = run_lifecycle(_cfg(0.9), DemoDomain(), workdir=tmp_path)  # cache hit, different env
    assert lr.result.status is RunStatus.FAILED  # cross-fingerprint reuse refused, loud
