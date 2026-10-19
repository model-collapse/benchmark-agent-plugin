# SPDX-License-Identifier: Apache-2.0
"""Subprocess worker: load a step function by name, run it, write a result JSON.

Invoked as ``python -m clusterbench_core.engine.worker <spec.json>``. The parent
sets PYTHONPATH so the step module is importable here (ClusterBench owns this
launch, so there is no missing-import gap).
"""

from __future__ import annotations

import importlib
import json
import os
import sys

_RESULT_KEYS = ("metrics", "outputs", "effective_params", "phases")


def main(argv=None):
    argv = argv or sys.argv[1:]
    spec = json.loads(open(argv[0]).read())
    os.makedirs(spec["workdir"], exist_ok=True)
    os.chdir(spec["workdir"])
    try:
        mod, _, fn = spec["fn"].partition(":")
        f = getattr(importlib.import_module(mod), fn)
        out = f(**spec["inputs"]) or {}
        res = {"status": "COMPLETED"}
        for k in _RESULT_KEYS:
            if k in out:
                res[k] = out[k]
    except Exception as e:  # noqa: BLE001 — report, don't crash the protocol
        res = {"status": "FAILED", "error": repr(e)}
    open(spec["result_path"], "w").write(json.dumps(res))


if __name__ == "__main__":
    main()
