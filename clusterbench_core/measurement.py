# SPDX-License-Identifier: Apache-2.0
"""Measurement-comparability statistics (Gate 2).

A trial is R independent measurement runs compared as a distribution of
run-level values. A speedup is "real" only if the relative improvement clears a
minimum detectable effect (MDE) AND the median shift is large relative to the
measured noise (so we never act on a difference smaller than run-to-run jitter).
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class MeasureStats:
    median: float
    stdev: float
    cv: float            # stdev / median
    n: int
    ci_lo: float
    ci_hi: float
    samples: list[float] = field(default_factory=list)


def measure_repeated(run_once: Callable[[int], float], R: int = 7,
                     bootstrap: int = 2000, seed: int = 0) -> MeasureStats:
    xs = [float(run_once(i)) for i in range(R)]
    med = statistics.median(xs)
    sd = statistics.pstdev(xs) if len(xs) > 1 else 0.0
    cv = (sd / med) if med else 0.0
    # bootstrap CI of the median
    rng = random.Random(seed)
    meds = sorted(statistics.median(rng.choices(xs, k=len(xs))) for _ in range(bootstrap))
    lo = meds[int(0.025 * bootstrap)]
    hi = meds[int(0.975 * bootstrap) - 1]
    return MeasureStats(median=med, stdev=sd, cv=cv, n=R, ci_lo=lo, ci_hi=hi, samples=xs)


def is_real_improvement(baseline: MeasureStats, cand: MeasureStats,
                        mde: float = 0.03, minimize: bool = True) -> bool:
    """True only if the candidate improves on the baseline by >= MDE AND the
    median shift exceeds 3x the pooled standard error (effect > noise)."""
    if not baseline.median:
        return False
    rel = ((baseline.median - cand.median) / baseline.median) if minimize \
        else ((cand.median - baseline.median) / baseline.median)
    if rel < mde:
        return False
    se = ((baseline.stdev ** 2) / max(baseline.n, 1) + (cand.stdev ** 2) / max(cand.n, 1)) ** 0.5
    return abs(baseline.median - cand.median) >= 3 * se


def comparable_cv(stats: MeasureStats, ceiling: float = 0.15) -> bool:
    return stats.cv <= ceiling
