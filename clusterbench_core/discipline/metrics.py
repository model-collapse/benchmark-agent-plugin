# SPDX-License-Identifier: Apache-2.0
"""Metric-definition integrity.

`recall@10` must be scored with a fixed k==10; comparing runs that used a
different k is apples-to-oranges (the metric name is a lie). If k != 10 the run's
functional validation is marked *skipped* (passed=None → EXPLORATORY) with a
reason, rather than silently reporting a structurally-capped recall as if it were
comparable.
"""

from __future__ import annotations

from typing import Any


def recall_validation(recall: float, k: int, integrity_passed: bool, **extra: Any) -> dict:
    base = {"recall@10": round(recall, 4), "k": k, **extra}
    if k != 10:
        return {"passed": None, "reason": "recall@10 requires k==10", **base}
    return {"passed": integrity_passed, **base}
