"""The invariant lifecycle backbone.

    budget -> manifest -> preflight(apply+verify) -> prep -> measure(guarded)
    -> validate -> classify -> persist

Prep is the deterministic/cacheable step; measure is always-run. Any hard-gate
failure short-circuits to an ABORTED_* status but STILL persists a RunResult
(the "always write the record" rule).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from clusterbench_core.discipline import analysis, preflight
from clusterbench_core.discipline.manifest import check_manifest
from clusterbench_core.discipline.reliability import (
    ClassifyInput,
    classify,
    reproduced_within_tolerance,
)
from clusterbench_core.guard import OOMGuard, GuardAction
from clusterbench_core.model import (
    BenchmarkConfig,
    ReliabilityTag,
    RunResult,
    RunStatus,
)


@dataclass
class LifecycleResult:
    result: RunResult
    report: str
    run_dir: Path
    preflight: preflight.PreflightResult | None = None


def _persist(run_dir: Path, cfg: BenchmarkConfig, result: RunResult, report: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(cfg.to_dict(), sort_keys=False))
    (run_dir / "results.yaml").write_text(yaml.safe_dump(result.to_dict(), sort_keys=False))
    (run_dir / "report.md").write_text(report)


def _finish(run_dir, cfg, result, prior) -> LifecycleResult:
    report = analysis.generate_report(cfg, result, prior)
    _persist(run_dir, cfg, result, report)
    return LifecycleResult(result=result, report=report, run_dir=run_dir)


def run_lifecycle(
    cfg: BenchmarkConfig,
    domain,
    ctx=None,
    workdir: str | Path = "./clusterbench_data/runs",
    baseline: BenchmarkConfig | None = None,
    apply: bool = True,
    prior: RunResult | None = None,
    launcher=None,
) -> LifecycleResult:
    run_id = cfg.run_id()
    sig = cfg.signature()
    run_dir = Path(workdir) / run_id

    def aborted(status: RunStatus, reason: str, extra_note: str = "") -> LifecycleResult:
        r = RunResult(
            run_id=run_id, signature=sig, status=status,
            reliability_tag=ReliabilityTag.UNRELIABLE if status == RunStatus.ABORTED_GUARDRAIL
            else ReliabilityTag.EXPLORATORY,
            abort={"status": status.value, "reason": reason},
            notes=[n for n in [extra_note] if n],
        )
        return _finish(run_dir, cfg, r, prior)

    # Step 1 — budget
    if cfg.resource_budget and cfg.resource_budget.verdict == "REJECT":
        return aborted(
            RunStatus.ABORTED_PREFLIGHT,
            f"resource budget REJECT: estimated_peak {cfg.resource_budget.estimated_peak_kb}KB "
            f"> hard ceiling {cfg.resource_budget.hard_kb}KB",
        )

    # Step 2 — manifest HARD GATE
    manifest = domain.required_params()
    if manifest:
        chk = check_manifest(cfg, manifest)
        if not chk.ok:
            return aborted(RunStatus.ABORTED_PREFLIGHT,
                           "manifest: missing " + ",".join(m.path for m in chk.missing))

    # Step 3 — preflight A/B/C
    pf = preflight.run_preflight(cfg, domain, ctx, baseline=baseline, apply=apply)
    if not pf.passed:
        lr = aborted(RunStatus.ABORTED_PREFLIGHT, pf.blocked_reason)
        lr.preflight = pf
        return lr

    # Gate 1: freeze the config at submit — any mutation from here is a new run.
    cfg.freeze()

    # Steps 4-5 — prep (cacheable) + measure (always-run) on the native engine.
    # If the domain exposes build_key()+save_prep()+load_prep(), prep is cached
    # on-disk by its build signature and reused across runs/sessions; the artifact
    # is persisted into the prep step dir and loaded back on a cache hit.
    from clusterbench_core.engine.cache import SignatureCache
    from clusterbench_core.engine.effective import EffectiveRecorder
    from clusterbench_core.engine.launcher import InProcessLauncher
    from clusterbench_core.engine.scheduler import Scheduler
    from clusterbench_core.engine.step import Step, StepRef

    cacheable = all(hasattr(domain, m) for m in ("build_key", "save_prep", "load_prep"))
    cache = SignatureCache(Path(workdir) / "_cache") if cacheable else None
    prep_wd = run_dir / "steps" / "prep"
    recorder = EffectiveRecorder()   # Gate 1: capture effective params at point of use

    def _prep_fn():
        art = domain.prep(cfg, recorder)
        desc = domain.prep_descriptor(art) if hasattr(domain, "prep_descriptor") else {}
        if cacheable:
            domain.save_prep(art, prep_wd)   # into the step workdir → scheduler caches it
            # Gate 2: stamp the build environment so a cross-fingerprint reuse is refused.
            from clusterbench_core.fingerprint import env_fingerprint
            (prep_wd / "_fingerprint.json").write_text(json.dumps(env_fingerprint()))
        return {"outputs": {"artifact": art, "descriptor": desc}}

    def _measure_fn(idx):
        art = idx.get("artifact")
        if art is None:                       # cache hit → load the persisted artifact
            fp_file = Path(idx["cache_dir"]) / "_fingerprint.json"
            if fp_file.exists():
                from clusterbench_core.fingerprint import (
                    assert_comparable_fingerprint, env_fingerprint)
                assert_comparable_fingerprint(json.loads(fp_file.read_text()), env_fingerprint())
            art = domain.load_prep(idx["cache_dir"])
        out = domain.measure(cfg, art, recorder)
        return {"metrics": out.metrics, "phases": out.phases,
                "outputs": {"functional_validation": out.functional_validation}}

    prep_step = Step(name="prep", fn=_prep_fn, inputs={},
                     cache_key=tuple(domain.build_key(cfg)) if cacheable else None,
                     cacheable=cacheable)
    measure_step = Step(name="measure", fn=_measure_fn, inputs={"idx": StepRef("prep")},
                        cacheable=False)
    step_results = Scheduler(launcher or InProcessLauncher(), cache=cache).run(
        [prep_step, measure_step], run_dir / "steps"
    )
    pr, mr = step_results["prep"], step_results["measure"]
    if pr.status != "COMPLETED" or mr.status != "COMPLETED":
        lr = aborted(RunStatus.FAILED, f"engine step failed: {pr.error or mr.error or 'unknown'}")
        lr.preflight = pf
        return lr

    metrics, phases = mr.metrics, mr.phases
    fv = mr.outputs.get("functional_validation", {})
    peak = int(metrics.get("peak_rss_kb", 0))
    if cfg.resource_budget and peak:
        action = OOMGuard(cfg.resource_budget).observe(peak)
        if action in (GuardAction.HARD_KILL, GuardAction.EMERGENCY_KILL):
            r = RunResult(
                run_id=run_id, signature=sig, status=RunStatus.ABORTED_GUARDRAIL,
                reliability_tag=ReliabilityTag.UNRELIABLE,
                metrics=metrics, phases=phases,
                abort={"status": "ABORTED_GUARDRAIL",
                       "reason": f"peak {peak}KB breached ceiling ({action.value})"},
                notes=[f"Guard {action.value} at {peak}KB; node protected."],
            )
            return _finish(run_dir, cfg, r, prior)

    # Step 6/7 — validate + classify
    result = RunResult(
        run_id=run_id, signature=sig, status=RunStatus.COMPLETED,
        reliability_tag=ReliabilityTag.QUALIFIED, metrics=metrics,
        phases=phases, functional_validation=fv,
        effective_params=dict(recorder.params),
    )
    notes: list[str] = []

    # Gate 1 — effective-vs-declared signature gate
    from clusterbench_core.engine.signature import field_diff, signature as _sig
    # Only gate params the config actually declares; a captured value whose name
    # is not a declared config param is not an identity param to compare against.
    declared_subset = {n: cfg.get(n) for n in recorder.params if n in cfg.params}
    captured_subset = {n: v for n, v in recorder.params.items() if n in cfg.params}
    diff = field_diff(declared_subset, captured_subset)
    result.effective_signature = _sig(captured_subset)
    result.signature_diff = {k: {"declared": a, "effective": b} for k, (a, b) in diff.items()}
    effective_matches = len(diff) == 0
    if not effective_matches:
        notes.append("EFFECTIVE != DECLARED: " + ", ".join(
            f"{k}({v['declared']}->{v['effective']})" for k, v in result.signature_diff.items()))

    reproduced = False
    if prior is not None:
        repro = reproduced_within_tolerance(prior, result)
        reproduced = repro.reproduced
        notes.append(f"reproduction vs {prior.run_id}: "
                     f"{'REPRODUCED' if reproduced else 'NOT reproduced'}")
    tag, rationale = classify(ClassifyInput(
        reproduced=reproduced,
        functional_validation_passed=fv.get("passed"),
        mechanism_explained=bool(phases),
        effective_matches_declared=effective_matches,
    ))
    result.reliability_tag = tag
    result.notes = notes + [f"reliability: {rationale}"]
    result.provenance = _provenance(cfg, result, launcher)
    # RSS is per-trial attributable only when measured in a fresh subprocess;
    # in-process peak_rss (ru_maxrss) is a process high-water mark contaminated by
    # prep and prior trials — flag it so the tuner never selects on it.
    result.measurement_flags = {"memory_comparable": type(launcher).__name__ == "LocalProcessLauncher"}
    from clusterbench_core.discipline.reliability import fairness_assert
    fairness_assert(result)  # fail-loud: effective!=declared can never be RELIABLE/QUALIFIED
    cfg.assert_unchanged()   # Gate 1: config must not have mutated during the run
    lr = _finish(run_dir, cfg, result, prior)
    lr.preflight = pf
    return lr


def _provenance(cfg: BenchmarkConfig, result: RunResult, launcher) -> dict:
    import datetime as _dt
    import socket
    import subprocess

    repo_root = Path(__file__).resolve().parents[1]
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                             capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        sha = "unknown"
    limits = {}
    if cfg.resource_budget:
        limits = {"total_ram_kb": cfg.resource_budget.total_ram_kb,
                  "hard_kb": cfg.resource_budget.hard_kb}
    return {
        "declared_signature": result.signature,
        "effective_signature": result.effective_signature,
        "code_version": sha,
        "seeds": {k: p.value for k, p in cfg.params.items() if k.endswith(".seed")},
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "launcher": type(launcher).__name__ if launcher is not None else "InProcessLauncher",
        "resource_limits": limits,
        "fingerprint": _env_fingerprint(),
    }


def _env_fingerprint() -> dict:
    from clusterbench_core.fingerprint import env_fingerprint
    return env_fingerprint()
