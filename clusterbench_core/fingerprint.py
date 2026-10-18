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
COMPARABILITY_KEYS = ("host", "cpu", "python", "code_version", "libs")


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
            libs[name] = getattr(mod, "__version__", "present")
        except Exception:  # noqa: BLE001
            libs[name] = "absent"
    return libs


def env_fingerprint() -> dict:
    return {
        "host": socket.gethostname(),
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "code_version": _git_sha(),
        "libs": _lib_versions(),
    }


def assert_comparable_fingerprint(baseline_fp: dict, current_fp: dict) -> None:
    """Raise if the two fingerprints differ on any comparability-relevant key."""
    diffs = {k: (baseline_fp.get(k), current_fp.get(k))
             for k in COMPARABILITY_KEYS if baseline_fp.get(k) != current_fp.get(k)}
    if diffs:
        raise BaselineFingerprintMismatch(
            "baseline/current environment differ (re-establish the baseline): " + str(diffs)
        )
