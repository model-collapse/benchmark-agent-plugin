"""Happy-path (a): real OpenSearch (Docker) SPLADE force-merge tuning. -m happy."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("opensearchpy")


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


pytestmark = [
    pytest.mark.happy,
    pytest.mark.skipif(not _docker_ok(), reason="docker not available"),
]


@pytest.fixture(scope="module")
def cluster():
    from clusterbench_domains.opensearch import OpenSearchCluster

    c = OpenSearchCluster(heap="4g").start(timeout_s=240)
    yield c
    c.stop()


def test_opensearch_splade_forcemerge_tuning(cluster, tmp_path):
    from experiments.opensearch_splade import run

    res, info = run(
        tmp_path, cluster,
        segment_values=(16, 8, 4, 1),
        n_docs=4000, n_queries=80, vocab=5000, avg_nnz=60,
        ingest_chunks=16, baseline_segments=16,
        splade_model="naver/splade-v3",
    )
    # the tuner searched the grid and recommended a configuration
    assert res.strategy == "grid"
    assert len(res.trials) == 4
    assert res.best is not None and res.best.feasible

    # it tuned toward fewer segments and got faster at a recall within 1pp
    assert res.best.params["forcemerge.max_num_segments"] == 1
    assert res.improvement is not None and res.improvement > 1.3
    assert (info["baseline_recall"] - res.best.quality) <= 0.0101

    # the recommended run actually force-merged to 1 segment and persisted a report
    import yaml
    r = yaml.safe_load((Path(tmp_path) / res.best.run_id / "results.yaml").read_text())
    assert r["metrics"]["segments_after"] == 1
    assert "## What Went Wrong" in (Path(tmp_path) / res.best.run_id / "report.md").read_text()
    assert "naver/splade-v3" in (Path(tmp_path) / res.best.run_id / "config.yaml").read_text()
