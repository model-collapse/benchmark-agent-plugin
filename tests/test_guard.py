from benchmark_engine.guard import GuardAction, OOMGuard, evaluate_stream
from benchmark_engine.model import ResourceBudget

RB = ResourceBudget(total_ram_kb=1000)  # warn 750, hard 850, emergency 920


def test_ok_below_warn():
    assert OOMGuard(RB).observe(500) is GuardAction.OK


def test_warn_then_hard_kill_requires_sustained():
    g = OOMGuard(RB, hard_sustained=2)
    assert g.observe(900) is GuardAction.WARN   # 1st over hard
    assert g.observe(900) is GuardAction.HARD_KILL  # 2nd sustained -> kill


def test_emergency_kills_immediately():
    assert OOMGuard(RB).observe(950) is GuardAction.EMERGENCY_KILL


def test_warn_resets_hard_count():
    g = OOMGuard(RB, hard_sustained=2)
    assert g.observe(900) is GuardAction.WARN
    assert g.observe(800) is GuardAction.WARN  # back into warn band resets hard streak
    assert g.observe(900) is GuardAction.WARN  # single over-hard again, not sustained yet


def test_evaluate_stream_terminal():
    assert evaluate_stream(RB, [500, 600, 500]) is GuardAction.OK
    assert evaluate_stream(RB, [500, 900, 900]) is GuardAction.HARD_KILL
    assert evaluate_stream(RB, [500, 999]) is GuardAction.EMERGENCY_KILL
