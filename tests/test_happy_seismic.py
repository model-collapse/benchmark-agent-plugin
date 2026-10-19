"""Happy-path (b): real SEISMIC build + iterative heap_factor tuning. -m happy."""

from pathlib import Path

import pytest

seismic = pytest.importorskip("seismic")

from experiments.seismic_splade import run  # noqa: E402


@pytest.mark.happy
def test_seismic_splade_tuning(tmp_path):
    res, info = run(
        tmp_path, points=4, rounds=3,
        n_docs=4000, n_queries=120, vocab=3000, avg_nnz=40,
        splade_model="naver/splade-v2",
    )
    # a real search happened (iterative refinement over several rounds, not one grid)
    assert len(res.trials) > 4
    assert res.strategy == "refine"

    # it recommended a configuration and reports an improvement over the baseline
    assert res.best is not None
    assert res.best.feasible
    assert res.improvement is not None and res.improvement > 1.0

    # the recommended point clears the 1pp recall floor
    assert res.best.quality >= info["recall_floor"]
    assert (info["baseline_recall"] - res.best.quality) <= 0.0101

    # every trial persisted a RunResult; the recommended run has a report
    report = Path(tmp_path) / res.best.run_id / "report.md"
    assert "## What Went Wrong" in report.read_text()
    assert "naver/splade-v2" in (Path(tmp_path) / res.best.run_id / "config.yaml").read_text()

    # the recommendation improves on the conservative starting point
    assert res.best.params["seismic.heap_factor"] > res.start.params["seismic.heap_factor"]
