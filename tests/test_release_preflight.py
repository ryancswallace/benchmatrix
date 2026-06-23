"""Tests for release preflight checks."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

pytestmark = pytest.mark.unit

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_release_preflight() -> Any:
    """Load the release preflight helper script as a module."""
    scripts_dir = _PROJECT_ROOT / "scripts"
    script_path = scripts_dir / "release_preflight.py"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location("release_preflight", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(cast(ModuleType, module))
    return module


def test_tool_check_reports_missing_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    release_preflight = _load_release_preflight()

    monkeypatch.setattr(shutil, "which", lambda tool: "/usr/bin/git" if tool == "git" else None)

    result = release_preflight.tool_check("git", "gh")

    assert not result.ok
    assert result.name == "tools"
    assert "gh" in result.message


def test_local_changes_check_allows_release_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_preflight = _load_release_preflight()

    monkeypatch.setattr(release_preflight, "status_paths", lambda root: {"CHANGELOG.md", "uv.lock"})

    result = release_preflight.local_changes_check(tmp_path)

    assert result.ok
    assert "Only release metadata" in result.message


def test_local_changes_check_rejects_unrelated_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_preflight = _load_release_preflight()

    monkeypatch.setattr(release_preflight, "status_paths", lambda root: {"CHANGELOG.md", "README.md"})

    result = release_preflight.local_changes_check(tmp_path)

    assert not result.ok
    assert "README.md" in result.message


def test_github_token_check_requires_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    release_preflight = _load_release_preflight()

    monkeypatch.setenv("GH_TOKEN", "")
    monkeypatch.setenv("GITHUB_TOKEN", "")

    missing = release_preflight.github_token_check()

    assert not missing.ok
    assert "GH_TOKEN" in missing.message

    monkeypatch.setenv("GH_TOKEN", "example-token")

    present = release_preflight.github_token_check()

    assert present.ok


def test_release_version_arg_validates_env_version(monkeypatch: pytest.MonkeyPatch) -> None:
    release_preflight = _load_release_preflight()

    assert release_preflight.release_version_arg("v1.2.3") == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "1.2.3")
    assert release_preflight.release_version_arg(None) == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "v1.2.3")
    with pytest.raises(release_preflight.ReleaseError, match="without a leading v"):
        release_preflight.release_version_arg(None)
