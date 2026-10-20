# SPDX-License-Identifier: Apache-2.0
"""Environment + code fingerprint.

A baseline measured on one host/CPU/container/code revision is not comparable to
trials measured on another — even at an identical config signature. The
fingerprint stamps the comparability-relevant environment so a cross-fingerprint
baseline reuse can be refused rather than silently compared.
"""

from __future__ import annotations

import platform
import socket
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# keys that must match for two measurements to be comparable
COMPARABILITY_KEYS = ("host", "cpu", "python", "code_version", "libs", "accelerator")


class BaselineFingerprintMismatch(RuntimeError):
    pass


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT,
                              capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _lib_versions() -> dict:
    libs = {}
    for name in ("seismic", "opensearchpy"):
        try:
            mod = __import__(name)
            libs[name] = str(getattr(mod, "__version__", "present"))  # str → JSON-stable
        except Exception:  # noqa: BLE001
            libs[name] = "absent"
    return libs


def _accelerator() -> str:
    """GPU/accelerator identity (name + driver), best-effort; 'absent' on a CPU box.
    A result measured on an A100 is not comparable to one on an H100."""
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        name = name.decode() if isinstance(name, bytes) else str(name)
        return f"{name} driver={pynvml.nvmlSystemGetDriverVersion()}"
    except Exception:  # noqa: BLE001
        pass
    try:
        import shutil
        if shutil.which("nvidia-smi"):
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,driver_version",
                 "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
            line = out.stdout.strip().splitlines()
            if line:
                return line[0].strip()
    except Exception:  # noqa: BLE001
        pass
    return "absent"


def env_fingerprint() -> dict:
    return {
        "host": socket.gethostname(),
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "code_version": _git_sha(),
        "libs": _lib_versions(),
        "accelerator": _accelerator(),
    }


def assert_comparable_fingerprint(baseline_fp: dict, current_fp: dict) -> None:
    """Raise if the two fingerprints differ on any comparability-relevant key."""
    diffs = {k: (baseline_fp.get(k), current_fp.get(k))
             for k in COMPARABILITY_KEYS if baseline_fp.get(k) != current_fp.get(k)}
    if diffs:
        raise BaselineFingerprintMismatch(
            "baseline/current environment differ (re-establish the baseline): " + str(diffs)
        )


def assert_comparable_eval(baseline: dict, current: dict) -> None:
    """Refuse to compare runs evaluated on different eval suites/versions — a
    higher score on an easier/newer suite is not an improvement."""
    for k in ("eval_suite", "eval_suite_version"):
        if baseline.get(k) != current.get(k):
            raise BaselineFingerprintMismatch(
                f"eval-suite mismatch on {k}: {baseline.get(k)} vs {current.get(k)} "
                "— not comparable")
