"""OOM crash-prevention: the framework must kill a runaway process before it
exhausts host RAM, and record the abort rather than letting the machine crash.

- Launcher level: a real subprocess that grows memory toward 2 GB is SIGKILLed by
  the guard at the budget ceiling (~0.3 GB), far short of its target.
- Lifecycle level: a measurement whose peak breaches the budget yields an
  ABORTED_GUARDRAIL RunResult that is still persisted (always-write-the-record).
"""

from pathlib import Path

from benchmark_engine.engine.launcher import LocalProcessLauncher
from benchmark_engine.engine.step import Step
from benchmark_engine.domain import MeasureOutcome, PrepArtifact
from benchmark_engine.lifecycle import run_lifecycle
from benchmark_engine.model import ResourceBudget, RunStatus

from conftest import make_base_config


def test_guard_kills_runaway_process_before_oom(tmp_path):
    # Budget ~350 MB ⇒ hard ≈ 297 MB, emergency ≈ 322 MB. The step tries to reach 2 GB.
    budget = ResourceBudget(total_ram_kb=350 * 1024)
    marker = tmp_path / "reached_mb"
    step = Step(
        name="hog",
        fn="benchmark_engine.engine.sample_steps:grow",
        inputs={"target_mb": 2000, "chunk_mb": 20, "sleep_s": 0.1, "marker": str(marker)},
        cacheable=False,
    )
    r = LocalProcessLauncher(budget=budget, poll_interval=0.1).run(step, step.inputs, tmp_path / "hog")

    assert r.status == "ABORTED_GUARDRAIL"          # the guard killed the child
    assert "guard" in r.error.lower()
    reached = int(marker.read_text()) if marker.exists() else 0
    # halted near the ~0.3 GB ceiling, nowhere near its 2 GB target → host never OOMs
    assert 0 < reached < 1000, f"runaway reached {reached} MB (expected it stopped near the budget)"


class _BigMemDomain:
    """Measurement reports a peak that breaches the budget."""
    name = "fake"

    def required_params(self): return {}
    def apply_config(self, cfg, ctx): return {}
    def verify_config(self, cfg, ctx): return {}
    def prep(self, cfg, ctx): return PrepArtifact(kind="fake")

    def measure(self, cfg, prep, ctx):
        return MeasureOutcome(metrics={"peak_rss_kb": 10_000_000},   # ~10 GB
                              functional_validation={"passed": True})


def test_lifecycle_aborts_on_budget_breach_and_still_persists(tmp_path):
    cfg = make_base_config(0.9)
    cfg.resource_budget = ResourceBudget(total_ram_kb=1_000_000)   # emergency ≈ 920 MB < 10 GB
    lr = run_lifecycle(cfg, _BigMemDomain(), workdir=tmp_path, baseline=make_base_config(0.9))

    assert lr.result.status is RunStatus.ABORTED_GUARDRAIL         # framework aborts, not crashes
    assert (lr.run_dir / "results.yaml").exists()                  # record always written
    assert lr.result.reliability_tag.value == "UNRELIABLE"


def test_budget_rejects_infeasible_run_before_execution(tmp_path):
    # a plan whose estimated peak exceeds the hard ceiling is rejected up front
    cfg = make_base_config(0.9)
    cfg.resource_budget = ResourceBudget(total_ram_kb=1_000_000, estimated_peak_kb=950_000)
    assert cfg.resource_budget.verdict == "REJECT"
    lr = run_lifecycle(cfg, _BigMemDomain(), workdir=tmp_path, baseline=make_base_config(0.9))
    assert lr.result.status is RunStatus.ABORTED_PREFLIGHT
