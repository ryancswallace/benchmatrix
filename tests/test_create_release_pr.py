"""Tests for release pull request automation."""

from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import load_script_module

pytestmark = pytest.mark.unit


def test_release_pr_plan_uses_standard_release_metadata() -> None:
    release_pr = load_script_module("create_release_pr")

    plan = release_pr.release_pr_plan("v1.2.3", "main")

    assert plan.version == "1.2.3"
    assert plan.branch == "release/v1.2.3"
    assert plan.base == "main"
    assert plan.commit_message == "Prepare benchmatrix 1.2.3 release"
    assert plan.title == "Release 1.2.3"
    assert "Prepare benchmatrix 1.2.3 release metadata" in plan.body
    assert "`make check`" in plan.body


def test_changed_release_files_rejects_unrelated_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_pr = load_script_module("create_release_pr")

    monkeypatch.setattr(release_pr, "status_paths", lambda root: {"CHANGELOG.md", "docs/runbooks/release.md"})

    with pytest.raises(release_pr.ReleaseError, match="unrelated working-tree changes"):
        release_pr.changed_release_files(tmp_path)


def test_changed_release_files_returns_release_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_pr = load_script_module("create_release_pr")

    monkeypatch.setattr(release_pr, "status_paths", lambda root: {"uv.lock", "CHANGELOG.md"})

    assert release_pr.changed_release_files(tmp_path) == ["CHANGELOG.md", "uv.lock"]


def test_release_version_arg_validates_env_version(monkeypatch: pytest.MonkeyPatch) -> None:
    release_pr = load_script_module("create_release_pr")

    assert release_pr.release_version_arg("v1.2.3") == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "1.2.3")
    assert release_pr.release_version_arg(None) == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "v1.2.3")
    with pytest.raises(release_pr.ReleaseError, match="without a leading v"):
        release_pr.release_version_arg(None)

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "")
    with pytest.raises(release_pr.ReleaseError, match="Set BENCHMATRIX_RELEASE_VERSION"):
        release_pr.release_version_arg(None)


def test_create_release_pr_reuses_existing_pull_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release_pr = load_script_module("create_release_pr")
    plan = release_pr.release_pr_plan("1.2.3", "main")
    calls: list[str] = []

    monkeypatch.setattr(release_pr, "ensure_tools", lambda: calls.append("ensure_tools"))
    monkeypatch.setattr(release_pr, "validate_release", lambda root, version: calls.append("validate_release"))
    monkeypatch.setattr(release_pr, "changed_release_files", lambda root: [])
    monkeypatch.setattr(release_pr, "ensure_branch", lambda root, branch: calls.append("ensure_branch"))
    monkeypatch.setattr(
        release_pr,
        "commit_release_changes",
        lambda root, release_plan, changed_files: False,
    )
    monkeypatch.setattr(release_pr, "push_branch", lambda root, branch: calls.append("push_branch"))
    monkeypatch.setattr(release_pr, "existing_pr_url", lambda root, branch: "https://example.test/pull/1")
    monkeypatch.setattr(release_pr, "create_pr", lambda root, release_plan, draft: pytest.fail("created a new PR"))

    url = release_pr.create_release_pr(tmp_path, plan, draft=True)

    assert url == "https://example.test/pull/1"
    assert calls == ["ensure_tools", "validate_release", "ensure_branch", "push_branch"]
    output = capsys.readouterr()
    assert "Release pull request already exists" in output.out
