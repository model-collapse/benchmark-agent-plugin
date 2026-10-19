# SPDX-License-Identifier: Apache-2.0
from benchmark_engine.measurement import (
    MeasureStats,
    comparable_cv,
    is_real_improvement,
    measure_repeated,
)


def test_measure_repeated_constant_has_zero_cv():
    s = measure_repeated(lambda i: 10.0, R=7)
    assert s.median == 10.0 and s.cv == 0.0 and s.n == 7


def test_small_effect_under_noise_is_not_real():
    # baseline ~10 with 5% noise; candidate ~9.9 (1% faster) — below MDE and noise
    base = MeasureStats(median=10.0, stdev=0.5, cv=0.05, n=7, ci_lo=9.6, ci_hi=10.4, samples=[])
    cand = MeasureStats(median=9.9, stdev=0.5, cv=0.05, n=7, ci_lo=9.5, ci_hi=10.3, samples=[])
    assert not is_real_improvement(base, cand, mde=0.03)


def test_large_effect_low_noise_is_real():
    base = MeasureStats(median=10.0, stdev=0.2, cv=0.02, n=7, ci_lo=9.9, ci_hi=10.1, samples=[])
    cand = MeasureStats(median=9.0, stdev=0.2, cv=0.02, n=7, ci_lo=8.9, ci_hi=9.1, samples=[])
    assert is_real_improvement(base, cand, mde=0.03)


def test_cv_ceiling():
    assert comparable_cv(MeasureStats(10, 1.0, 0.10, 7, 9, 11, []), ceiling=0.15)
    assert not comparable_cv(MeasureStats(10, 2.0, 0.20, 7, 8, 12, []), ceiling=0.15)


def test_measure_repeated_bootstrap_ci_brackets_median():
    import random
    rng = random.Random(0)
    s = measure_repeated(lambda i: 10.0 + rng.uniform(-1, 1), R=15)
    assert s.ci_lo <= s.median <= s.ci_hi
