# SPDX-License-Identifier: Apache-2.0
"""Command-stage runner: the primitive behind CommandDomain.

A *stage* is one shell command. ``run_command_stage`` substitutes ``{name}``
tokens (from params + upstream artifacts, each shell-quoted), runs the command,
collects the artifact paths it was told it ``produces``, and — for a measurement
stage — extracts metrics from the command's stdout or an output file.

Token substitution is deliberately NOT ``str.format``: a command may legitimately
contain literal braces (e.g. JSON on stdout), so we replace only the exact
``{name}`` tokens for names we know, leaving everything else intact.
"""

from __future__ import annotations

import csv
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from benchmark_engine.resources import (
    GpuSpec, NullProbe, VramExceeded, cost, gpu_hours, pin_env)


class CommandStageError(RuntimeError):
    """A stage command exited non-zero."""


class MetricExtractionError(RuntimeError):
    """A metrics payload was missing, unparseable, or lacked a requested field."""


def _substitute(cmd: str, values: dict[str, Any]) -> str:
    out = cmd
    for name, val in values.items():
        token = "{" + name + "}"
        if token in out:
            out = out.replace(token, shlex.quote(str(val)))
    return out


def _descriptor(path: Path) -> dict[str, Any]:
    try:
        st = path.stat()
        return {"path": str(path), "size": st.st_size, "mtime": st.st_mtime}
    except OSError:
        return {"path": str(path), "size": None, "mtime": None}


def extract_metrics(spec: dict, workdir: str) -> dict[str, Any]:
    """Parse a metrics payload and select ``fields``.

    ``spec`` is ``{"stdout": True, "fields": [...]}`` (payload passed as ``_stdout``)
    or ``{"file": "<path>", "fields": [...]}``. JSON by default; ``.csv`` → first row.
    Missing/empty/unparseable payload or a missing field → MetricExtractionError.
    """
    fields = spec.get("fields") or []
    if spec.get("file"):
        p = Path(spec["file"])
        if not p.is_absolute():
            p = Path(workdir) / p
        if not p.exists():
            raise MetricExtractionError(f"metrics file not found: {p}")
        raw = p.read_text()
        is_csv = p.suffix == ".csv"
    else:
        raw = spec.get("_stdout", "")
        is_csv = False

    if raw is None or not raw.strip():
        raise MetricExtractionError("empty metrics payload")

    try:
        if is_csv:
            rows = list(csv.DictReader(raw.splitlines()))
            if not rows:
                raise MetricExtractionError("empty CSV metrics payload")
            data = {k: _coerce(v) for k, v in rows[0].items()}
        else:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise MetricExtractionError("metrics JSON is not an object")
    except json.JSONDecodeError as e:
        raise MetricExtractionError(f"unparseable metrics JSON: {e}") from e

    out: dict[str, Any] = {}
    for f in fields:
        if f not in data:
            raise MetricExtractionError(f"metric field '{f}' not in payload")
        out[f] = data[f]
    return out


def _coerce(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return float(v) if ("." in v or "e" in v.lower()) else int(v)
        except ValueError:
            return v
    return v


def run_command_stage(cmd: str, params: dict, artifacts: dict, workdir: str,
                      produces: list[str] | None = None,
                      metrics_from: dict | None = None,
                      gpu: GpuSpec | None = None, probe=None,
                      rate_per_gpu_hour: float = 0.0) -> dict:
    """Run one stage command. Returns a step-fn dict with ``outputs`` (produced
    artifact paths + a ``descriptor`` map) and, if ``metrics_from`` is set or GPU
    accounting applies, ``metrics``. Non-zero exit → CommandStageError;
    over-budget VRAM → VramExceeded. When ``gpu.gpus > 0`` the command runs with
    CUDA_VISIBLE_DEVICES pinned to range(gpu.gpus), VRAM is checked after it runs,
    and gpu_hours (and cost, if a rate is set) are recorded."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    produces = produces or []
    resolved_artifacts = dict(artifacts)
    for name in produces:
        resolved_artifacts.setdefault(name, str(workdir / name))

    values = {**params, **resolved_artifacts}
    final_cmd = _substitute(cmd, values)

    device_ids = list(range(gpu.gpus)) if (gpu and gpu.gpus > 0) else []
    env = pin_env(dict(os.environ), device_ids) if device_ids else None

    t0 = time.time()
    if device_ids:
        # GPU stage: sample VRAM live while the child runs so we observe its PEAK,
        # not the (freed) memory after it exits.
        _p = probe or NullProbe()
        proc = subprocess.Popen(final_cmd, shell=True, cwd=str(workdir),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env)
        peak_mb = 0
        while proc.poll() is None:
            peak_mb = max(peak_mb, _p.used_mb(device_ids))
            time.sleep(0.05)
        stdout, stderr = proc.communicate()
        peak_mb = max(peak_mb, _p.used_mb(device_ids))
        returncode = proc.returncode
    else:
        r = subprocess.run(final_cmd, shell=True, cwd=str(workdir),
                           capture_output=True, text=True)
        stdout, stderr, returncode, peak_mb = r.stdout, r.stderr, r.returncode, 0
    elapsed = time.time() - t0

    if returncode != 0:
        raise CommandStageError(
            f"stage command exited {returncode}: {final_cmd}\n{stderr}")
    if device_ids and gpu.vram_mb is not None and peak_mb > gpu.vram_mb:   # fail loud on VRAM-OOM
        raise VramExceeded(
            f"VRAM peak {peak_mb}MB exceeded budget {gpu.vram_mb}MB on devices {device_ids}")

    outputs: dict[str, Any] = {}
    descriptor: dict[str, Any] = {}
    for name in produces:
        path = Path(resolved_artifacts[name])
        outputs[name] = str(path)
        descriptor[name] = _descriptor(path)
    outputs["descriptor"] = descriptor

    metrics: dict[str, Any] = {}
    if metrics_from is not None:
        spec = dict(metrics_from)
        if spec.get("stdout"):
            spec["_stdout"] = stdout
        metrics.update(extract_metrics(spec, str(workdir)))
    if gpu and gpu.gpus > 0:   # resource accounting (not a science metric)
        gh = gpu_hours(gpu.gpus, elapsed)
        metrics["gpu_hours"] = gh
        if rate_per_gpu_hour:
            metrics["cost"] = cost(gh, rate_per_gpu_hour)

    result: dict[str, Any] = {"outputs": outputs}
    if metrics:
        result["metrics"] = metrics
    return result
