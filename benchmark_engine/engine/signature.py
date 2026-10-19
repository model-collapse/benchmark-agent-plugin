# SPDX-License-Identifier: Apache-2.0
"""Content-hash signatures + structured field diffs.

A signature is a deterministic, order-independent hash of a payload dict; it is
the identity primitive for cache keys and the effective-vs-declared gate. The
field diff names *which* keys changed, so a deviation can be explained.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def signature(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def field_diff(declared: dict, effective: dict) -> dict[str, tuple[Any, Any]]:
    """Per-key (declared, effective) for every key whose stringified value differs
    or that is missing from one side."""
    out: dict[str, tuple[Any, Any]] = {}
    for k in set(declared) | set(effective):
        a = declared.get(k)
        b = effective.get(k)
        if (k not in declared) or (k not in effective) or str(a) != str(b):
            out[k] = (a, b)
    return out
