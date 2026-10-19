import yaml

from benchmark_engine.lifecycle import run_lifecycle
from benchmark_engine.model import ReliabilityTag, ResourceBudget, RunStatus

from conftest import FakeDomain, make_base_config


def test_full_lifecycle_completes_and_persists(tmp_path):
    cfg = make_base_config(0.9)
    lr = run_lifecycle(cfg, FakeDomain(), workdir=tmp_path, baseline=make_base_config(0.7))
    assert lr.result.status is RunStatus.COMPLETED
    # single run with passing validation but no reproduction -> QUALIFIED
    assert lr.result.reliability_tag is ReliabilityTag.QUALIFIED
    assert lr.result.metrics["p50_ms"] < 50.0
    # persisted artifacts
    assert (lr.run_dir / "results.yaml").exists()
    assert (lr.run_dir / "config.yaml").exists()
    assert "## What Went Wrong" in (lr.run_dir / "report.md").read_text()
    saved = yaml.safe_load((lr.run_dir / "results.yaml").read_text())
    assert saved["status"] == "COMPLETED"


def test_budget_reject_aborts_preflight(tmp_path):
    cfg = make_base_config(0.9)
    cfg.resource_budget = ResourceBudget(total_ram_kb=1000, estimated_peak_kb=950)
    lr = run_lifecycle(cfg, FakeDomain(), workdir=tmp_path)
    assert lr.result.status is RunStatus.ABORTED_PREFLIGHT
    assert "budget REJECT" in lr.result.abort["reason"]
    assert (lr.run_dir / "results.yaml").exists()  # record still written


def test_preflight_verify_mismatch_aborts_and_does_not_measure(tmp_path):
    cfg = make_base_config(0.9)
    dom = FakeDomain(live_overrides={"fake.n_postings": 1})
    lr = run_lifecycle(cfg, dom, workdir=tmp_path, baseline=make_base_config(0.7))
    assert lr.result.status is RunStatus.ABORTED_PREFLIGHT
    assert "phase_c_verify" in lr.result.abort["reason"]
    assert not lr.result.metrics  # never measured


def test_forced_oom_aborts_guardrail_and_persists(tmp_path):
    cfg = make_base_config(1.0)  # treatment >= oom_at triggers huge peak
    cfg.resource_budget = ResourceBudget(total_ram_kb=10_000)
    dom = FakeDomain(oom_at=1.0)
    lr = run_lifecycle(cfg, dom, workdir=tmp_path, baseline=make_base_config(0.7))
    assert lr.result.status is RunStatus.ABORTED_GUARDRAIL
    assert lr.result.reliability_tag is ReliabilityTag.UNRELIABLE
    assert "breached ceiling" in lr.result.abort["reason"]
    assert (lr.run_dir / "results.yaml").exists()


def test_manifest_gate_blocks_lifecycle(tmp_path, fake_manifest_file):
    from benchmark_engine.discipline.manifest import load_manifest
    cfg = make_base_config(0.9)
    del cfg.params["fake.n_postings"]
    dom = FakeDomain(manifest=load_manifest(fake_manifest_file))
    lr = run_lifecycle(cfg, dom, workdir=tmp_path, baseline=None)
    assert lr.result.status is RunStatus.ABORTED_PREFLIGHT
    assert "manifest" in lr.result.abort["reason"]


def test_reproduction_promotes_to_reliable(tmp_path):
    # First run (no prior) -> QUALIFIED. Second run with same config as prior and
    # agreeing metrics -> reproduced -> RELIABLE.
    cfg = make_base_config(0.9)
    first = run_lifecycle(cfg, FakeDomain(), workdir=tmp_path, baseline=make_base_config(0.7))
    assert first.result.reliability_tag is ReliabilityTag.QUALIFIED

    cfg2 = make_base_config(0.9)
    cfg2.repro_nonce = 1  # fresh identity, deterministic FakeDomain -> identical metrics
    second = run_lifecycle(cfg2, FakeDomain(), workdir=tmp_path,
                           baseline=make_base_config(0.7), prior=first.result)
    assert "REPRODUCED" in " ".join(second.result.notes)
    assert second.result.reliability_tag is ReliabilityTag.RELIABLE


def test_lifecycle_runs_via_explicit_inprocess_launcher(tmp_path):
    from benchmark_engine.engine.launcher import InProcessLauncher
    cfg = make_base_config(0.9)
    lr = run_lifecycle(cfg, FakeDomain(), workdir=tmp_path, baseline=make_base_config(0.7),
                       launcher=InProcessLauncher())
    assert lr.result.status is RunStatus.COMPLETED
    assert lr.result.metrics["p50_ms"] < 50.0
