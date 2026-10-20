import json
import pytest
from pathlib import Path
from benchmark_ops.command import (
    run_command_stage, extract_metrics, CommandStageError, MetricExtractionError)


def test_substitutes_params_and_runs(tmp_path):
    out = run_command_stage(
        cmd='echo {greeting} > {msg}', params={"greeting": "hi"}, artifacts={},
        workdir=str(tmp_path), produces=["msg"])
    assert (tmp_path / "msg").read_text().strip() == "hi"
    assert out["outputs"]["msg"].endswith("msg")
    assert "msg" in out["outputs"]["descriptor"]


def test_metrics_from_stdout_json(tmp_path):
    spec = {"stdout": True, "fields": ["p50_ms", "qps"]}
    out = run_command_stage(
        cmd='echo \'{"p50_ms": 12.0, "qps": 800, "ignored": 1}\'',
        params={}, artifacts={}, workdir=str(tmp_path), metrics_from=spec)
    assert out["metrics"] == {"p50_ms": 12.0, "qps": 800}


def test_metrics_from_json_file(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps({"acc": 0.91, "n": 5}))
    assert extract_metrics({"file": str(tmp_path / "r.json"), "fields": ["acc"]}, str(tmp_path)) == {"acc": 0.91}


def test_metrics_from_csv_file(tmp_path):
    (tmp_path / "r.csv").write_text("acc,loss\n0.9,0.3\n")
    assert extract_metrics({"file": str(tmp_path / "r.csv"), "fields": ["acc", "loss"]}, str(tmp_path)) == {"acc": 0.9, "loss": 0.3}


def test_nonzero_exit_raises(tmp_path):
    with pytest.raises(CommandStageError):
        run_command_stage(cmd='exit 3', params={}, artifacts={}, workdir=str(tmp_path))


def test_empty_metrics_payload_fails_loud(tmp_path):   # Review Focus: malformed output
    (tmp_path / "r.json").write_text("")
    with pytest.raises(MetricExtractionError):
        extract_metrics({"file": str(tmp_path / "r.json"), "fields": ["acc"]}, str(tmp_path))


def test_artifact_path_with_spaces_is_safe(tmp_path):  # Review Focus: injection
    weird = tmp_path / "a b;c"
    out = run_command_stage(cmd='echo ok > {dst}', params={}, artifacts={"dst": str(weird)},
                            workdir=str(tmp_path), produces=["dst"])
    assert Path(out["outputs"]["dst"]).read_text().strip() == "ok"
