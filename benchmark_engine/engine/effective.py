# SPDX-License-Identifier: Apache-2.0
"""EffectiveRecorder — captures the value a step ACTUALLY used for an identity
param, at the point of use.

A domain's measure/prep calls ``ctx.effective(name, value)`` where the value is
consumed (passed into the search/build call), and gets the value back. Recording
the declared value by re-reading the config proves nothing; recording at the call
site is what makes an adaptive clamp visible to the effective-vs-declared gate.
"""

from __future__ import annotations

from typing import Any


class EffectiveRecorder:
    def __init__(self):
        self.params: dict[str, Any] = {}

    def effective(self, name: str, value: Any) -> Any:
        self.params[name] = value
        return value
