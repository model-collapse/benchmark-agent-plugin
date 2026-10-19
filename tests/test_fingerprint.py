# SPDX-License-Identifier: Apache-2.0
import pytest
from clusterbench_core.fingerprint import (
    BaselineFingerprintMismatch,
    assert_comparable_fingerprint,
    env_fingerprint,
)


def test_fingerprint_has_comparability_keys():
    fp = env_fingerprint()
    for k in ("host", "cpu", "python", "code_version", "libs"):
        assert k in fp


def test_identical_fingerprints_are_comparable():
    fp = env_fingerprint()
    assert_comparable_fingerprint(fp, dict(fp))  # no raise


def test_mismatched_fingerprint_refuses_reuse():
    fp = env_fingerprint()
    other = dict(fp)
    other["code_version"] = "deadbeef"
    with pytest.raises(BaselineFingerprintMismatch):
        assert_comparable_fingerprint(fp, other)
