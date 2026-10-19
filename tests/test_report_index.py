from clusterbench_core.lifecycle import run_lifecycle
from clusterbench_core.report_index import update_index

from conftest import FakeDomain, make_base_config


def test_update_index_groups_by_tag(tmp_path):
    for v in (0.5, 0.9):
        run_lifecycle(make_base_config(v), FakeDomain(), workdir=tmp_path,
                      baseline=make_base_config(0.7))
    out = update_index(tmp_path)
    text = out.read_text()
    assert "# Benchmark Results Index" in text
    assert "## Qualified Runs" in text
    assert "## Active Baselines (RELIABLE)" in text
    # two qualified single-runs recorded
    assert text.count("fake__fake.heap_factor") >= 2


def test_load_runs_flattens_results(tmp_path):
    from clusterbench_core.report_index import load_runs
    for v in (0.5, 0.9):
        run_lifecycle(make_base_config(v), FakeDomain(), workdir=tmp_path,
                      baseline=make_base_config(0.7))
    rows = load_runs(tmp_path)
    assert len(rows) == 2
    r = rows[0]
    assert {"run_id", "status", "reliability_tag", "p50_ms", "treatment"} <= set(r)
    assert r["treatment"] == "fake.heap_factor"
