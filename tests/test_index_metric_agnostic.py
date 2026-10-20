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


def test_load_runs_flattens_arbitrary_fv(tmp_path):   # review Important 3: no hard-coded recall@10
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "results.yaml").write_text(yaml.safe_dump({
        "run_id": "r1", "status": "COMPLETED", "reliability_tag": "QUALIFIED",
        "metrics": {"p50_ms": 5.0},
        "functional_validation": {"ndcg@10": 0.5, "passed": True}}))
    from benchmark_engine.report_index import load_runs
    rows = load_runs(tmp_path / "runs")
    assert rows[0]["ndcg@10"] == 0.5   # arbitrary quality metric flattened, not just recall@10
