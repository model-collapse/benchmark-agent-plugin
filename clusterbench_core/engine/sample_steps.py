# SPDX-License-Identifier: Apache-2.0
"""Sample step functions usable as `module:function` by the subprocess worker.

These live in the first-party package (not under tests/) so the worker can import
them by a stable dotted path regardless of how `tests` resolves on sys.path.
"""

import time


def add(a, b):
    return {"metrics": {"s": a + b}, "effective_params": {"a": a}}


def boom():
    raise RuntimeError("intentional failure")


def hog():
    _ = b"x" * (150 * 1024 * 1024)  # ~150 MB resident
    time.sleep(30)
    return {"metrics": {}}


def mem_report():
    import resource
    _ = bytearray(80 * 1024 * 1024)  # ~80 MB
    return {"metrics": {"peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}


# --- in-process instrumented steps (concurrency gauge + run/order recorders) ---
import threading as _threading  # noqa: E402

_g_lock = _threading.Lock()
_g_cur = 0
_g_peak = 0
_runs: dict = {}
_order: list = []


def gauge(sleep_s=0.2):
    global _g_cur, _g_peak
    with _g_lock:
        _g_cur += 1
        _g_peak = max(_g_peak, _g_cur)
    time.sleep(sleep_s)
    with _g_lock:
        _g_cur -= 1
    return {"metrics": {}}


def gauge_peak():
    return _g_peak


def gauge_reset():
    global _g_cur, _g_peak
    _g_cur = 0
    _g_peak = 0


def record(name, **_ignored):
    with _g_lock:
        _runs[name] = _runs.get(name, 0) + 1
        _order.append(name)
    return {"metrics": {}, "outputs": {"descriptor": {"name": name}}}


def runs_of(name):
    return _runs.get(name, 0)


def order():
    return list(_order)


def recorder_reset():
    _runs.clear()
    _order.clear()
