"""Tests for release tag automation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from _helpers import load_script_module

pytestmark = pytest.mark.unit


def test_release_tag_plan_uses_standard_tag_metadata() -> None:
    release_tag = load_script_module("create_release_tag")

    plan = release_tag.release_tag_plan("v1.2.3", "main")

    assert plan.version == "1.2.3"
    assert plan.tag == "v1.2.3"
    assert plan.base == "main"
    assert plan.message == "benchmatrix 1.2.3"


def test_create_release_tag_pulls_validates_tags_and_pushes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_tag = load_script_module("create_release_tag")
    commands: list[list[str]] = []

    monkeypatch.setattr(release_tag, "ensure_git", lambda: None)
    monkeypatch.setattr(release_tag, "ensure_clean_tree", lambda root: None)
    monkeypatch.setattr(release_tag, "switch_to_base", lambda root, base: None)
    monkeypatch.setattr(release_tag, "validate_release", lambda root, version: None)
    monkeypatch.setattr(release_tag, "local_tag_exists", lambda root, tag: False)
    monkeypatch.setattr(release_tag, "remote_tag_exists", lambda root, tag: False)

    def record(command: list[str], *, cwd: Path, capture: bool = False, check: bool = True) -> None:
        commands.append(command)

    monkeypatch.setattr(release_tag, "run_command", record)

    release_tag.create_release_tag(tmp_path, release_tag.release_tag_plan("1.2.3", "main"))

    assert commands == [
        ["git", "pull", "--ff-only", "origin", "main"],
        ["git", "tag", "-a", "v1.2.3", "-m", "benchmatrix 1.2.3"],
        ["git", "push", "origin", "v1.2.3"],
    ]


def test_release_version_arg_validates_env_version(monkeypatch: pytest.MonkeyPatch) -> None:
    release_tag = load_script_module("create_release_tag")

    assert release_tag.release_version_arg("v1.2.3") == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "1.2.3")
    assert release_tag.release_version_arg(None) == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "v1.2.3")
    with pytest.raises(release_tag.ReleaseError, match="without a leading v"):
        release_tag.release_version_arg(None)


def test_create_release_tag_rejects_existing_local_tag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_tag = load_script_module("create_release_tag")
    commands: list[list[str]] = []

    monkeypatch.setattr(release_tag, "ensure_git", lambda: None)
    monkeypatch.setattr(release_tag, "ensure_clean_tree", lambda root: None)
    monkeypatch.setattr(release_tag, "switch_to_base", lambda root, base: None)
    monkeypatch.setattr(release_tag, "validate_release", lambda root, version: None)
    monkeypatch.setattr(release_tag, "local_tag_exists", lambda root, tag: True)
    monkeypatch.setattr(release_tag, "remote_tag_exists", lambda root, tag: False)

    def record(command: list[str], *, cwd: Path, capture: bool = False, check: bool = True) -> None:
        commands.append(command)

    monkeypatch.setattr(release_tag, "run_command", record)

    with pytest.raises(release_tag.ReleaseError, match="Local tag already exists"):
        release_tag.create_release_tag(tmp_path, release_tag.release_tag_plan("1.2.3", "main"))

    assert commands == [["git", "pull", "--ff-only", "origin", "main"]]


def test_remote_tag_exists_reports_lookup_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_tag = load_script_module("create_release_tag")

    def fail(
        command: list[str],
        *,
        cwd: Path,
        capture: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 128, "", "remote unavailable")

    monkeypatch.setattr(release_tag, "run_command", fail)

    with pytest.raises(release_tag.ReleaseError, match="Could not check remote tag"):
        release_tag.remote_tag_exists(tmp_path, "v1.2.3")
