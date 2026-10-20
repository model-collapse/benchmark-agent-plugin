import pytest
from benchmark_engine.resources import vram_check, VramExceeded


class _Fake:
    def __init__(self, mb):
        self._mb = mb

    def used_mb(self, device_ids):
        return self._mb


def test_vram_check_raises_over_budget():
    with pytest.raises(VramExceeded):
        vram_check(_Fake(80000), [0], 72000)


def test_vram_check_ok_within_budget():
    vram_check(_Fake(40000), [0], 72000)   # no raise


def test_vram_check_noop_without_budget():
    vram_check(_Fake(999999), [0], None)   # no raise
