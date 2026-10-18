# SPDX-License-Identifier: Apache-2.0
from clusterbench_core.engine.signature import signature, field_diff


def test_signature_stable_and_order_independent():
    assert signature({"a": 1, "b": 2}) == signature({"b": 2, "a": 1})


def test_signature_sensitive():
    assert signature({"a": 1}) != signature({"a": 2})


def test_signature_is_16_hex():
    s = signature({"a": 1})
    assert len(s) == 16 and all(c in "0123456789abcdef" for c in s)


def test_field_diff_names_changed_keys_only():
    assert field_diff({"x": 1, "y": 2}, {"x": 1, "y": 9}) == {"y": (2, 9)}


def test_field_diff_handles_missing_keys():
    assert field_diff({"x": 1}, {"x": 1, "z": 5}) == {"z": (None, 5)}
    assert field_diff({"x": 1, "z": 5}, {"x": 1}) == {"z": (5, None)}
