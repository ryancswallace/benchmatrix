"""Tests to ensure the project's Python environment is functional."""

from __future__ import annotations


def test_project_package_importable() -> None:
    assert benchkit.__version__
