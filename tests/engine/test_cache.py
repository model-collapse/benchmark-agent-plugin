# SPDX-License-Identifier: Apache-2.0
import pytest

from benchmark_engine.engine.cache import SignatureCache, StaleArtifact


def test_store_then_hit(tmp_path):
    c = SignatureCache(tmp_path)
    assert not c.has("prep", "sig1")
    c.store("prep", "sig1", {"docs": 100}, lambda p: (p / "idx").write_text("x"))
    assert c.has("prep", "sig1")
    assert (c.load("prep", "sig1", {"docs": 100}) / "idx").read_text() == "x"


def test_descriptor_mismatch_is_stale(tmp_path):
    c = SignatureCache(tmp_path)
    c.store("prep", "sig1", {"docs": 100}, lambda p: (p / "idx").write_text("x"))
    with pytest.raises(StaleArtifact):
        c.load("prep", "sig1", {"docs": 999})


def test_miss_before_store(tmp_path):
    c = SignatureCache(tmp_path)
    with pytest.raises(KeyError):
        c.load("prep", "nope", {})


def test_store_is_atomic_on_producer_error(tmp_path):
    c = SignatureCache(tmp_path)

    def boom(p):
        (p / "partial").write_text("x")
        raise RuntimeError("producer failed")

    with pytest.raises(RuntimeError):
        c.store("prep", "sig1", {"d": 1}, boom)
    # a failed producer must not leave a visible cache hit
    assert not c.has("prep", "sig1")


def test_cross_instance_hit(tmp_path):
    SignatureCache(tmp_path).store("prep", "s", {"d": 1}, lambda p: (p / "f").write_text("y"))
    # a fresh instance (simulating a new process/session) sees the on-disk entry
    assert SignatureCache(tmp_path).has("prep", "s")
