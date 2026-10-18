# SPDX-License-Identifier: Apache-2.0
"""Guards the Apache-2.0 relicense and the removal of the GPL experimaestro dep."""

import importlib
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_experimaestro_not_a_dependency():
    pp = (ROOT / "pyproject.toml").read_text()
    assert "experimaestro" not in pp


def test_license_is_apache():
    txt = (ROOT / "LICENSE").read_text()
    assert "Apache License" in txt and "Version 2.0" in txt
    assert "GNU GENERAL PUBLIC LICENSE" not in txt


def test_xpm_module_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("clusterbench_core.xpm")
