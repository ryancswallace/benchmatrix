"""Tests to ensure the project's Python environment is functional."""

from __future__ import annotations

import benchkit


def test_project_package_importable() -> None:
    assert benchkit.__version__ and "unknown" not in benchkit.__version__
