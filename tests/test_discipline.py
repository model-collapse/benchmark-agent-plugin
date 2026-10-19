import copy

from clusterbench_core.discipline import analysis, manifest, preflight, reliability
from clusterbench_core.discipline.reliability import ClassifyInput
from clusterbench_core.model import ReliabilityTag, RunResult, RunStatus

from conftest import FakeDomain, make_base_config


# ---------------- manifest gate ----------------

def test_manifest_loads_and_skips_pseudo_entries(fake_manifest_file):
    m = manifest.load_manifest(fake_manifest_file)
    assert "fake.n_postings" in m and "fake.heap_factor" in m
    assert m["fake.n_postings"].baseline_value == 3500


def test_manifest_blocks_when_param_missing(fake_manifest_file):
    m = manifest.load_manifest(fake_manifest_file)
    cfg = make_base_config()
    del cfg.params["fake.n_postings"]
    chk = manifest.check_manifest(cfg, m)
    assert not chk.ok
    assert chk.missing[0].path == "fake.n_postings"
    assert chk.missing[0].suggested == 3500
    assert "DOMAIN MANIFEST CHECK FAILED" in chk.render()


def test_manifest_passes_when_all_declared(fake_manifest_file):
    m = manifest.load_manifest(fake_manifest_file)
    cfg = make_base_config()
    assert manifest.check_manifest(cfg, m).ok


def test_autofill_then_gate_passes(fake_manifest_file):
    m = manifest.load_manifest(fake_manifest_file)
    cfg = make_base_config()
    del cfg.params["fake.n_postings"]
    filled = manifest.autofill_from_manifest(cfg, m)
    assert "fake.n_postings" in filled
    assert manifest.check_manifest(cfg, m).ok


# ---------------- preflight Phase A ----------------

def test_phase_a_treatment_is_allowed():
    base = make_base_config(0.7)
    new = make_base_config(0.9)  # only the treatment var differs
    d = preflight.baseline_diff(new, base)
    assert d.ok
    assert any(k == "fake.heap_factor" for k, *_ in d.treatments)


def test_phase_a_unexpected_diff_blocks():
    base = make_base_config(0.7)
    new = make_base_config(0.7)
    new.set_param("fake.n_postings", 9999)  # silent change, not treatment, not allowed
    d = preflight.baseline_diff(new, base)
    assert not d.ok
    assert d.unexpected and d.unexpected[0][0] == "fake.n_postings"


def test_phase_a_missing_param_blocks():
    base = make_base_config(0.7)
    new = make_base_config(0.7)
    del new.params["fake.n_postings"]
    d = preflight.baseline_diff(new, base)
    assert not d.ok
    assert d.missing_from_new[0][0] == "fake.n_postings"


def test_phase_a_allowed_drift_passes():
    base = make_base_config(0.7)
    new = make_base_config(0.7)
    new.set_param("fake.n_postings", 9999)
    new.expected_diff_from_baseline = [
        {"parameter": "fake.n_postings", "reason": "index pre-exists", "accepted_by": "user"}
    ]
    d = preflight.baseline_diff(new, base)
    assert d.ok
    assert d.allowed_drift[0][0] == "fake.n_postings"


# ---------------- preflight Phase C + orchestration ----------------

def test_run_preflight_passes_clean():
    cfg = make_base_config(0.9)
    res = preflight.run_preflight(cfg, FakeDomain(), ctx=None, baseline=make_base_config(0.7))
    assert res.passed
    assert res.phase_c.ok


def test_run_preflight_blocks_on_verify_mismatch():
    cfg = make_base_config(0.9)
    dom = FakeDomain(live_overrides={"fake.n_postings": 1})  # cluster didn't honor the setting
    res = preflight.run_preflight(cfg, dom, ctx=None, baseline=make_base_config(0.7))
    assert not res.passed
    assert "phase_c_verify" in res.blocked_reason


def test_run_preflight_blocks_on_phase_a_before_apply():
    cfg = make_base_config(0.7)
    cfg.set_param("fake.n_postings", 1234)  # unexpected drift
    dom = FakeDomain()
    res = preflight.run_preflight(cfg, dom, ctx=None, baseline=make_base_config(0.7))
    assert not res.passed and res.blocked_reason == "phase_a_baseline_diff"
    assert dom.applied == {}  # must not apply when Phase A fails


# ---------------- reliability ----------------

def test_classify_reliable_requires_reproduction():
    base = ClassifyInput(reproduced=False)
    tag, _ = reliability.classify(base)
    assert tag is ReliabilityTag.QUALIFIED
    tag2, _ = reliability.classify(ClassifyInput(reproduced=True))
    assert tag2 is ReliabilityTag.RELIABLE


def test_classify_validation_skipped_caps_at_exploratory():
    tag, _ = reliability.classify(ClassifyInput(reproduced=True, functional_validation_passed=None))
    assert tag is ReliabilityTag.EXPLORATORY


def test_classify_confound_is_unreliable():
    tag, _ = reliability.classify(ClassifyInput(reproduced=True, gross_confound=True))
    assert tag is ReliabilityTag.UNRELIABLE


def test_classify_first_of_kind_exploratory():
    tag, _ = reliability.classify(ClassifyInput(multivariable_or_first_of_kind=True))
    assert tag is ReliabilityTag.EXPLORATORY


def test_reproduction_tolerance():
    a = RunResult("a", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED,
                  metrics={"p50_ms": 10.0, "peak_rss_kb": 1000},
                  functional_validation={"recall@10": 0.98})
    b = copy.deepcopy(a)
    b.metrics["p50_ms"] = 11.0  # +10% within 20% tol
    chk = reliability.reproduced_within_tolerance(a, b)
    assert chk.reproduced
    b.metrics["p50_ms"] = 20.0  # +100% out of tol
    assert not reliability.reproduced_within_tolerance(a, b).reproduced


def test_recall_uses_absolute_tolerance():
    a = RunResult("a", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED,
                  metrics={}, functional_validation={"recall@10": 0.98})
    b = RunResult("b", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED,
                  metrics={}, functional_validation={"recall@10": 0.978})  # -0.2pp within 0.5pp
    tol = {"recall@10": {"tol": 0.005, "absolute": True}}  # recall declared by the domain, not core
    assert reliability.reproduced_within_tolerance(a, b, tol).reproduced
    b.functional_validation["recall@10"] = 0.95  # -3pp out
    assert not reliability.reproduced_within_tolerance(a, b, tol).reproduced


def test_citation_rules():
    assert reliability.citation_allowed(ReliabilityTag.RELIABLE)
    assert reliability.citation_allowed(ReliabilityTag.QUALIFIED)
    assert not reliability.citation_allowed(ReliabilityTag.UNRELIABLE)
    assert not reliability.citation_allowed(ReliabilityTag.EXPLORATORY)


# ---------------- analysis report ----------------

def test_report_has_mandatory_sections_and_passes_audit():
    cfg = make_base_config(0.9)
    r = RunResult("rid", cfg.signature(), RunStatus.COMPLETED, ReliabilityTag.QUALIFIED,
                  metrics={"p50_ms": 12.0}, functional_validation={"passed": True, "recall@10": 0.98})
    report = analysis.generate_report(cfg, r)
    assert "## What Went Wrong or Remained Unknown" in report
    assert "## Primary Metrics" in report
    assert reliability.audit_claims(report, functional_validation_passed=True) == []


def test_audit_flags_no_regression_without_validation():
    text = "Everything fine. No regression observed.\n## What Went Wrong or Remained Unknown\n- none"
    v = reliability.audit_claims(text, functional_validation_passed=None)
    assert any("no regression" in x for x in v)


def test_classify_effective_mismatch_is_unreliable():
    tag, why = reliability.classify(ClassifyInput(
        reproduced=True, functional_validation_passed=True, effective_matches_declared=False))
    assert tag is ReliabilityTag.UNRELIABLE and "effective" in why.lower()


def test_p99_not_in_reproduction_gate():
    a = RunResult("a", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED,
                  metrics={"p50_ms": 10.0, "p99_ms": 50.0})
    b = RunResult("b", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED,
                  metrics={"p50_ms": 10.2, "p99_ms": 500.0})  # wild p99, fine p50
    assert reliability.reproduced_within_tolerance(a, b).reproduced  # p99 ignored


def test_p50_tightened_to_10pct():
    a = RunResult("a", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED, metrics={"p50_ms": 10.0})
    b = RunResult("b", "s", RunStatus.COMPLETED, ReliabilityTag.QUALIFIED, metrics={"p50_ms": 11.5})
    assert not reliability.reproduced_within_tolerance(a, b).reproduced  # 15% > 10%
