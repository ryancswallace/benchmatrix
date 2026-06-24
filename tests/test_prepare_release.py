"""Tests for release preparation automation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from _helpers import load_script_module

pytestmark = pytest.mark.unit


def _write_release_files(root: Path) -> None:
    """Create the minimal release metadata files used by the helper."""
    _ = (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "benchmatrix"
            version = "0.1.0"
            description = "A package."
            """
        ).lstrip(),
        encoding="utf-8",
    )
    _ = (root / "CITATION.cff").write_text(
        textwrap.dedent(
            """
            cff-version: 1.2.0
            message: Cite this package.
            title: benchmatrix
            version: 0.1.0
            date-released: "2026-06-01"
            """
        ).lstrip(),
        encoding="utf-8",
    )
    _ = (root / "CHANGELOG.md").write_text(
        textwrap.dedent(
            """
            # Changelog

            ## Unreleased

            ### Added

            * New release helper.

            ### Changed

            * Release preparation is shorter.

            ## 0.1.0 - 2026-06-01

            ### Added

            * Initial release.
            """
        ).lstrip(),
        encoding="utf-8",
    )


def test_prepare_updates_release_metadata_and_runs_uv_lock(tmp_path: Path) -> None:
    release = load_script_module("prepare_release")
    _write_release_files(tmp_path)
    lock_roots: list[Path] = []

    def fake_run_uv_lock(root: Path) -> None:
        assert 'version = "1.2.3"' in (root / "pyproject.toml").read_text(encoding="utf-8")
        lock_roots.append(root)

    release.run_uv_lock = fake_run_uv_lock

    exit_code = release.main(["--repo-root", str(tmp_path), "prepare", "v1.2.3", "--date", "2026-06-23"])

    assert exit_code == 0
    assert lock_roots == [tmp_path]
    assert 'version = "1.2.3"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    citation = (tmp_path / "CITATION.cff").read_text(encoding="utf-8")
    assert "version: 1.2.3" in citation
    assert 'date-released: "2026-06-23"' in citation
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## Unreleased\n\n### Added\n\n### Changed" in changelog
    assert "## 1.2.3 - 2026-06-23" in changelog
    assert "* New release helper." in changelog
    assert "* Release preparation is shorter." in changelog


def test_validate_rejects_inconsistent_release_metadata(tmp_path: Path) -> None:
    release = load_script_module("prepare_release")
    _write_release_files(tmp_path)

    exit_code = release.main(["--repo-root", str(tmp_path), "validate", "1.2.3"])

    assert exit_code == 1


def test_validate_release_version_requires_env_style_version() -> None:
    release = load_script_module("prepare_release")

    assert release.validate_release_version("1.2.3") == "1.2.3"

    with pytest.raises(release.ReleaseError, match="Set BENCHMATRIX_RELEASE_VERSION"):
        release.validate_release_version("")

    with pytest.raises(release.ReleaseError, match="without a leading v"):
        release.validate_release_version("v1.2.3")

    with pytest.raises(release.ReleaseError, match=r"must be X\.Y\.Z"):
        release.validate_release_version("1.2")


def test_validate_version_cli_reports_missing_or_malformed_versions(capsys: pytest.CaptureFixture[str]) -> None:
    release = load_script_module("prepare_release")

    assert release.main(["validate-version", ""]) == 1
    missing = capsys.readouterr()
    assert "Set BENCHMATRIX_RELEASE_VERSION=X.Y.Z" in missing.err

    assert release.main(["validate-version", "v1.2.3"]) == 1
    malformed = capsys.readouterr()
    assert "without a leading v" in malformed.err

    assert release.main(["validate-version", "1.2.3"]) == 0
    valid = capsys.readouterr()
    assert "Release version is 1.2.3." in valid.out


def test_notes_cli_prints_and_writes_release_notes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = load_script_module("prepare_release")
    _write_release_files(tmp_path)

    assert release.main(["--repo-root", str(tmp_path), "prepare", "v1.2.3", "--date", "2026-06-23", "--no-lock"]) == 0
    _ = capsys.readouterr()

    output_path = tmp_path / "release-notes.md"

    assert release.main(["--repo-root", str(tmp_path), "notes", "1.2.3", "--output", str(output_path)]) == 0
    assert "* New release helper." in output_path.read_text(encoding="utf-8")

    assert release.main(["--repo-root", str(tmp_path), "notes", "v1.2.3"]) == 0
    printed = capsys.readouterr()
    assert "* Release preparation is shorter." in printed.out
