"""Tests for release tag automation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

pytestmark = pytest.mark.unit

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_create_release_tag() -> Any:
    """Load the release tag helper script as a module."""
    scripts_dir = _PROJECT_ROOT / "scripts"
    script_path = scripts_dir / "create_release_tag.py"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location("create_release_tag", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(cast(ModuleType, module))
    return module


def test_release_tag_plan_uses_standard_tag_metadata() -> None:
    release_tag = _load_create_release_tag()

    plan = release_tag.release_tag_plan("v1.2.3", "main")

    assert plan.version == "1.2.3"
    assert plan.tag == "v1.2.3"
    assert plan.base == "main"
    assert plan.message == "benchmatrix 1.2.3"


def test_create_release_tag_pulls_validates_tags_and_pushes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release_tag = _load_create_release_tag()
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
    release_tag = _load_create_release_tag()

    assert release_tag.release_version_arg("v1.2.3") == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "1.2.3")
    assert release_tag.release_version_arg(None) == "1.2.3"

    monkeypatch.setenv("BENCHMATRIX_RELEASE_VERSION", "v1.2.3")
    with pytest.raises(release_tag.ReleaseError, match="without a leading v"):
        release_tag.release_version_arg(None)
