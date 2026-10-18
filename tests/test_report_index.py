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
