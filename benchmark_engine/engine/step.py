# SPDX-License-Identifier: Apache-2.0
"""Engine data types: Step, StepRef, StepResult, and edge derivation.

Dependencies are *hand-declared* — either an explicit ``depends_on`` list or by
passing a ``StepRef`` (a handle to another step's output) anywhere in ``inputs``.
No type metaclass infers them; ``edges`` just walks these two sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StepRef:
    """A handle to the output of an upstream step; its presence in `inputs`
    declares a dependency edge."""

    step_name: str


@dataclass
class Step:
    name: str
    fn: str                       # "module:function" — importable in a worker
    inputs: dict[str, Any] = field(default_factory=dict)
    cache_key: tuple | None = None   # identity for a cacheable step; None ⇒ not cached
    cacheable: bool = False
    depends_on: list[str] = field(default_factory=list)
    # a non-cacheable (measurement) step that records NO comparability-sensitive
    # performance metric may opt into running in parallel; perf measures stay serialized.
    parallel_safe: bool = False


@dataclass
class StepResult:
    status: str                   # COMPLETED | FAILED | ABORTED_GUARDRAIL
    outputs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    phases: list = field(default_factory=list)
    effective_params: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def _refs(value: Any) -> set[str]:
    if isinstance(value, StepRef):
        return {value.step_name}
    if isinstance(value, (list, tuple, set)):
        out: set[str] = set()
        for v in value:
            out |= _refs(v)
        return out
    if isinstance(value, dict):
        out = set()
        for v in value.values():
            out |= _refs(v)
        return out
    return set()


def edges(steps: list[Step]) -> dict[str, set[str]]:
    """name -> set of upstream step names it depends on."""
    out: dict[str, set[str]] = {}
    for s in steps:
        deps = set(s.depends_on)
        for v in s.inputs.values():
            deps |= _refs(v)
        out[s.name] = deps
    return out
