# SPDX-License-Identifier: Apache-2.0
from benchmark_engine.engine.cache import SignatureCache
from benchmark_engine.engine.launcher import InProcessLauncher
from benchmark_engine.engine.scheduler import Scheduler
from benchmark_engine.engine.signature import signature
from benchmark_engine.engine.step import Step, StepRef

import benchmark_engine.engine.sample_steps as toy


def _prep(name, cacheable=True, inputs=None, depends_on=None, fn="benchmark_engine.engine.sample_steps:record"):
    return Step(name=name, fn=fn, inputs=inputs or ({"name": name} if "record" in fn else {}),
                cache_key=(name,) if cacheable else None, cacheable=cacheable,
                depends_on=depends_on or [])


def test_topo_order_prep_before_measure(tmp_path):
    toy.recorder_reset()
    prep = _prep("prep")
    meas = Step("measure", fn="benchmark_engine.engine.sample_steps:record",
                inputs={"name": "measure", "idx": StepRef("prep")},
                cache_key=None, cacheable=False, depends_on=[])
    Scheduler(InProcessLauncher()).run([meas, prep], tmp_path)
    assert toy.order() == ["prep", "measure"]


def test_failure_propagates_to_dependent(tmp_path):
    toy.recorder_reset()
    prep = Step("prep", fn="benchmark_engine.engine.sample_steps:boom", inputs={}, cache_key=("prep",),
                cacheable=True, depends_on=[])
    meas = Step("measure", fn="benchmark_engine.engine.sample_steps:record",
                inputs={"name": "measure", "idx": StepRef("prep")},
                cache_key=None, cacheable=False, depends_on=[])
    res = Scheduler(InProcessLauncher()).run([prep, meas], tmp_path)
    assert res["prep"].status == "FAILED"
    assert res["measure"].status == "FAILED" and "upstream" in res["measure"].error
    assert toy.runs_of("measure") == 0  # never launched


def test_cache_hit_skips_launch(tmp_path):
    toy.recorder_reset()
    cache = SignatureCache(tmp_path / "cache")
    sig = signature({"name": "prep", "key": ["prep"]})
    cache.store("prep", sig, {"name": "prep"}, lambda p: (p / "idx").write_text("x"))
    res = Scheduler(InProcessLauncher(), cache=cache).run([_prep("prep")], tmp_path / "wd")
    assert res["prep"].status == "COMPLETED" and res["prep"].outputs.get("cached") is True
    assert toy.runs_of("prep") == 0  # cache hit → fn not run


def test_parallel_prep_overlaps(tmp_path):
    toy.gauge_reset()
    steps = [_prep("a", fn="benchmark_engine.engine.sample_steps:gauge"), _prep("b", fn="benchmark_engine.engine.sample_steps:gauge")]
    for s in steps:
        s.inputs = {"sleep_s": 0.3}
    Scheduler(InProcessLauncher(), max_parallel=2).run(steps, tmp_path)
    assert toy.gauge_peak() == 2  # two independent cacheable steps ran concurrently


def test_measurement_never_overlaps(tmp_path):
    toy.gauge_reset()
    # two independent NON-cacheable (measurement) steps must serialize
    a = Step("a", fn="benchmark_engine.engine.sample_steps:gauge", inputs={"sleep_s": 0.3}, cache_key=None,
             cacheable=False, depends_on=[])
    b = Step("b", fn="benchmark_engine.engine.sample_steps:gauge", inputs={"sleep_s": 0.3}, cache_key=None,
             cacheable=False, depends_on=[])
    Scheduler(InProcessLauncher(), max_parallel=2).run([a, b], tmp_path)
    assert toy.gauge_peak() == 1  # serialized
