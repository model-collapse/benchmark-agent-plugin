# SPDX-License-Identifier: Apache-2.0
from clusterbench_core.engine.step import Step, StepRef, StepResult, edges


def _s(name, inputs=None, depends_on=None, cacheable=True):
    return Step(name=name, fn="m:f", inputs=inputs or {}, cache_key=("c",) if cacheable else None,
                cacheable=cacheable, depends_on=depends_on or [])


def test_edges_from_ref():
    prep = _s("prep")
    meas = _s("measure", inputs={"idx": StepRef("prep")}, cacheable=False)
    assert edges([prep, meas])["measure"] == {"prep"}


def test_edges_from_explicit_depends_on():
    a, b = _s("a"), _s("b", depends_on=["a"])
    assert edges([a, b])["b"] == {"a"}


def test_edges_from_ref_inside_list():
    a = _s("a")
    b = _s("b", inputs={"xs": [StepRef("a"), 7]})
    assert edges([a, b])["b"] == {"a"}


def test_independent_steps_have_no_edges():
    assert edges([_s("a"), _s("b")]) == {"a": set(), "b": set()}


def test_stepresult_defaults():
    r = StepResult(status="COMPLETED")
    assert r.metrics == {} and r.effective_params == {} and r.phases == []
