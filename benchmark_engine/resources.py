# SPDX-License-Identifier: Apache-2.0
"""GPU/accelerator resource management: budget declaration, device pinning,
GPU-hours/cost accounting, and a VRAM-OOM guard — all behind an injectable VRAM
probe so every path is testable without hardware.

`default_probe()` resolves to pynvml → nvidia-smi → NullProbe (CPU box) and never
raises on import, so declaring `resources.gpus` on a machine with no GPU is safe:
VRAM polling is a no-op and GPU-hours are still accounted by wall-time × gpus.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class GpuSpec:
    gpus: int = 0
    vram_mb: int | None = None
    est_gpu_hours: float | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> "GpuSpec":
        d = d or {}
        return cls(gpus=int(d.get("gpus", 0)),
                   vram_mb=d.get("vram_mb"),
                   est_gpu_hours=d.get("est_gpu_hours"))


def pin_env(base_env: dict, device_ids: list[int]) -> dict:
    """Return a copy of base_env with CUDA_VISIBLE_DEVICES set to the device ids
    (unchanged when the list is empty)."""
    env = dict(base_env)
    if device_ids:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(str(d) for d in device_ids)
    return env


def gpu_hours(gpus: int, seconds: float) -> float:
    return gpus * seconds / 3600.0


def cost(gpu_hours_val: float, rate_per_gpu_hour: float) -> float:
    return gpu_hours_val * rate_per_gpu_hour


@runtime_checkable
class VramProbe(Protocol):
    def used_mb(self, device_ids: list[int]) -> int:
        """Max VRAM (MB) in use across the given devices; 0 if unknown."""


class NullProbe:
    def used_mb(self, device_ids: list[int]) -> int:
        return 0


class NvmlProbe:
    def __init__(self, pynvml):
        self._nvml = pynvml

    def used_mb(self, device_ids: list[int]) -> int:
        peak = 0
        for d in device_ids or [0]:
            try:
                h = self._nvml.nvmlDeviceGetHandleByIndex(d)
                used = self._nvml.nvmlDeviceGetMemoryInfo(h).used // (1024 * 1024)
                peak = max(peak, int(used))
            except Exception:  # noqa: BLE001
                continue
        return peak


class SmiProbe:
    def used_mb(self, device_ids: list[int]) -> int:
        ids = ",".join(str(d) for d in device_ids) if device_ids else "0"
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used",
                 "--format=csv,noheader,nounits", "-i", ids],
                capture_output=True, text=True, timeout=5)
            vals = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
            return max(vals) if vals else 0
        except Exception:  # noqa: BLE001
            return 0


def default_probe() -> VramProbe:
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        return NvmlProbe(pynvml)
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("nvidia-smi"):
        return SmiProbe()
    return NullProbe()
