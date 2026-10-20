# SPDX-License-Identifier: Apache-2.0
"""Recipe loader. A recipe is a pre-filled CommandDomain `spec` (stages +
required_params manifest) for a common scenario; `load_recipe` reads the YAML
and deep-merges caller overrides so a recipe is a starting point, not a cage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_DIR = Path(__file__).parent


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_recipe(name: str, overrides: dict | None = None) -> dict[str, Any]:
    path = _DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no recipe {name!r} (looked in {_DIR})")
    spec = yaml.safe_load(path.read_text()) or {}
    if overrides:
        spec = _deep_merge(spec, overrides)
    return spec
