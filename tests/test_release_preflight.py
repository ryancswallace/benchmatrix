"""Tests for release preflight checks."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from _helpers import load_script_module

pytestmark = pytest.mark.unit


def test_tool_check_reports_missing_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    release_preflight = load_script_module("release_preflight")

    monkeypatch.setattr(shutil, "which", lambda tool: "/usr/bin/git" if tool == "git" else None)

    result = release_preflight.tool_check("git", "gh")

    assert not result.ok
    assert result.name == "tools"
    assert "gh" in result.message


def test_local_changes_check_allows_release_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_preflight = load_script_module("release_preflight")

    monkeypatch.setattr(release_preflight, "status_paths", lambda root: {"CHANGELOG.md", "uv.lock"})

    result = release_preflight.local_changes_check(tmp_path)

    assert result.ok
    assert "Only release metadata" in result.message


def test_local_changes_check_rejects_unrelated_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_preflight = load_script_module("release_preflight")

    monkeypatch.setattr(release_preflight, "status_paths", lambda root: {"CHANGELOG.md", "README.md"})

    result = release_preflight.local_changes_check(tmp_path)

    assert not result.ok
    assert "README.md" in result.message


def test_github_token_check_requires_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    release_preflight = load_script_module("release_preflight")

    monkeypatch.setenv("GH_TOKEN", "")
    monkeypatch.setenv("GITHUB_TOKEN", "")

    missing = release_preflight.github_token_check()

    assert not missing.ok
    assert "GH_TOKEN" in missing.message

    monkeypatch.setenv("GH_TOKEN", "example-token")

    present = release_preflight.github_token_check()

    assert present.ok


def test_release_version_arg_validates_env_version(monkeypatch: pytest.MonkeyPatch) -> None:
    release_preflight = load_script_module("release_preflight")

    assert release_preflight.release_version_arg("v1.2.3") == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "1.2.3")
    assert release_preflight.release_version_arg(None) == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "v1.2.3")
    with pytest.raises(release_preflight.ReleaseError, match="without a leading v"):
        release_preflight.release_version_arg(None)


def test_run_preflight_treats_warning_checks_as_non_blocking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release_preflight = load_script_module("release_preflight")
    ok = release_preflight.CheckResult

    monkeypatch.setattr(release_preflight, "tool_check", lambda *tools: ok("tools", True, "ok"))
    monkeypatch.setattr(release_preflight, "git_branch_check", lambda root, base: ok("branch", True, "ok"))
    monkeypatch.setattr(release_preflight, "local_changes_check", lambda root: ok("local changes", True, "ok"))
    monkeypatch.setattr(release_preflight, "base_sync_check", lambda root, base: ok("base sync", True, "ok"))
    monkeypatch.setattr(release_preflight, "gh_auth_check", lambda root: ok("GitHub auth", True, "ok"))
    monkeypatch.setattr(release_preflight, "github_token_check", lambda: ok("GitHub API token", True, "ok"))
    monkeypatch.setattr(release_preflight, "tag_absence_check", lambda root, tag: ok("release tag", True, "ok"))
    monkeypatch.setattr(
        release_preflight,
        "github_release_absence_check",
        lambda root, tag: ok("GitHub Release", True, "ok"),
    )
    monkeypatch.setattr(
        release_preflight,
        "pypi_environment_check",
        lambda root: ok("pypi environment", False, "not visible", warning=True),
    )

    assert release_preflight.run_preflight(tmp_path, "v1.2.3", "main") == 0
    output = capsys.readouterr()
    assert "WARN pypi environment: not visible" in output.out
