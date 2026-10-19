from clusterbench_core.model import (
    BenchmarkConfig,
    ControlledVar,
    Param,
    PhaseMetrics,
    ReliabilityTag,
    ResourceBudget,
    RunResult,
    RunStatus,
    TreatmentVariable,
)


def make_cfg(**over):
    cfg = BenchmarkConfig(
        domain="seismic",
        hypothesis="lower heap_factor speeds up search",
        treatment_variable=TreatmentVariable(name="seismic.heap_factor", baseline_value=0.7, value=0.9),
    )
    cfg.set_param("seismic.n_postings", 3500, source="inherited")
    cfg.set_param("seismic.heap_factor", 0.9, source="treatment")
    for k, v in over.items():
        cfg.set_param(k, v)
    return cfg


def test_param_from_bare_scalar_and_record():
    assert Param.from_dict(5).value == 5
    assert Param.from_dict(5).source == "default"
    p = Param.from_dict({"value": 7, "source": "treatment", "note": "x"})
    assert (p.value, p.source, p.note) == (7, "treatment", "x")


def test_resource_budget_thresholds_and_verdict():
    rb = ResourceBudget(total_ram_kb=1000, estimated_peak_kb=800)
    assert rb.warn_kb == 750 and rb.hard_kb == 850 and rb.emergency_kb == 920
    assert rb.verdict == "GO"
    rb2 = ResourceBudget(total_ram_kb=1000, estimated_peak_kb=900)
    assert rb2.verdict == "REJECT"


def test_config_roundtrip():
    cfg = make_cfg()
    cfg.controlled_variables.append(ControlledVar("seismic.k", 10, verify="noop"))
    cfg.resource_budget = ResourceBudget(total_ram_kb=2000, estimated_peak_kb=100)
    back = BenchmarkConfig.from_dict(cfg.to_dict())
    assert back.to_dict() == cfg.to_dict()
    assert back.get("seismic.n_postings") == 3500
    assert back.treatment_variable.name == "seismic.heap_factor"


def test_signature_stable_and_param_sensitive():
    a = make_cfg()
    b = make_cfg()
    assert a.signature() == b.signature()  # same config -> same signature (cache hit)
    b.set_param("seismic.n_postings", 1000)
    assert a.signature() != b.signature()  # param change -> different signature


def test_signature_ignores_prose_but_tracks_nonce():
    a = make_cfg()
    b = make_cfg()
    b.hypothesis = "totally different prose"
    assert a.signature() == b.signature()  # prose is not identity
    b.repro_nonce = 1
    assert a.signature() != b.signature()  # reproduction nonce forces fresh identity


def test_run_id_contains_treatment_and_signature():
    cfg = make_cfg()
    rid = cfg.run_id()
    assert rid.startswith("seismic__seismic.heap_factor=0.9__")
    assert rid.endswith(cfg.signature())


def test_runresult_roundtrip():
    r = RunResult(
        run_id="r1",
        signature="deadbeef",
        status=RunStatus.COMPLETED,
        reliability_tag=ReliabilityTag.QUALIFIED,
        metrics={"p50_ms": 12.3},
        phases=[PhaseMetrics(name="build", duration_s=4.0, peak_rss_kb=100)],
        functional_validation={"recall@10": 0.98},
    )
    back = RunResult.from_dict(r.to_dict())
    assert back.to_dict() == r.to_dict()
    assert back.status is RunStatus.COMPLETED
    assert back.phases[0].name == "build"


def test_frozen_config_rejects_set_param():
    import pytest
    from clusterbench_core.model import FrozenConfigError
    cfg = make_cfg().freeze()
    with pytest.raises(FrozenConfigError):
        cfg.set_param("seismic.n_postings", 1)
    cfg.assert_unchanged()  # unmutated -> no raise


def test_assert_unchanged_detects_direct_mutation():
    import pytest
    from clusterbench_core.model import FrozenConfigError, Param
    cfg = make_cfg().freeze()
    cfg.params["seismic.n_postings"] = Param(value=999)  # bypass set_param
    with pytest.raises(FrozenConfigError):
        cfg.assert_unchanged()
