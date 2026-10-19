import yaml
from benchmark_engine.report_index import update_index


def test_index_lists_arbitrary_metrics(tmp_path):
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "results.yaml").write_text(yaml.safe_dump({
        "run_id": "r1", "status": "COMPLETED", "reliability_tag": "QUALIFIED",
        "metrics": {"mmlu_acc": 0.63, "tokens_per_s": 1800.0}, "functional_validation": {}}))
    out = update_index(tmp_path / "runs").read_text()
    assert "mmlu_acc" in out and "tokens_per_s" in out
    assert "p50_ms" not in out   # no hard-coded retrieval columns when the metric is absent
