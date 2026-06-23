"""Tests for release pull request automation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

pytestmark = pytest.mark.unit

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_create_release_pr() -> Any:
    """Load the release PR helper script as a module."""
    scripts_dir = _PROJECT_ROOT / "scripts"
    script_path = scripts_dir / "create_release_pr.py"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location("create_release_pr", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(cast(ModuleType, module))
    return module


def test_release_pr_plan_uses_standard_release_metadata() -> None:
    release_pr = _load_create_release_pr()

    plan = release_pr.release_pr_plan("v1.2.3", "main")

    assert plan.version == "1.2.3"
    assert plan.branch == "release/v1.2.3"
    assert plan.base == "main"
    assert plan.commit_message == "Prepare benchmatrix 1.2.3 release"
    assert plan.title == "Release 1.2.3"
    assert "Prepare benchmatrix 1.2.3 release metadata" in plan.body
    assert "`make check`" in plan.body


def test_changed_release_files_rejects_unrelated_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_pr = _load_create_release_pr()

    monkeypatch.setattr(release_pr, "status_paths", lambda root: {"CHANGELOG.md", "docs/runbooks/release.md"})

    with pytest.raises(release_pr.ReleaseError, match="unrelated working-tree changes"):
        release_pr.changed_release_files(tmp_path)


def test_changed_release_files_returns_release_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_pr = _load_create_release_pr()

    monkeypatch.setattr(release_pr, "status_paths", lambda root: {"uv.lock", "CHANGELOG.md"})

    assert release_pr.changed_release_files(tmp_path) == ["CHANGELOG.md", "uv.lock"]


def test_release_version_arg_validates_env_version(monkeypatch: pytest.MonkeyPatch) -> None:
    release_pr = _load_create_release_pr()

    assert release_pr.release_version_arg("v1.2.3") == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "1.2.3")
    assert release_pr.release_version_arg(None) == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "v1.2.3")
    with pytest.raises(release_pr.ReleaseError, match="without a leading v"):
        release_pr.release_version_arg(None)

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "")
    with pytest.raises(release_pr.ReleaseError, match="Set BENCHMATRIX_RELEASE_VERSION"):
        release_pr.release_version_arg(None)
