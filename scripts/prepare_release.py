#!/usr/bin/env python3
"""Prepare release metadata and release notes."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^(?:v)?(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$")
RELEASE_VERSION_RE = re.compile(r"^(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$")
PROJECT_VERSION_RE = re.compile(r'(?ms)(^\[project\]\n.*?^version = ")(?P<version>[^"]+)(")')
CITATION_VERSION_RE = re.compile(r"(?m)^version: .+$")
CITATION_DATE_RE = re.compile(r"(?m)^date-released: .+$")
UNRELEASED_TEMPLATE = "### Added\n\n### Changed\n\n### Deprecated\n\n### Removed\n\n### Fixed\n\n### Security"


class ReleaseError(Exception):
    """Raised when release metadata cannot be prepared or validated."""


def normalize_version(raw_version: str) -> str:
    """Return a validated X.Y.Z version without a leading v."""
    match = VERSION_RE.match(raw_version.strip())
    if not match:
        raise ReleaseError(f"Version must be X.Y.Z with an optional leading v; got {raw_version!r}.")
    return match.group("version")


def validate_date(raw_date: str) -> str:
    """Return a validated ISO release date."""
    try:
        dt.date.fromisoformat(raw_date)
    except ValueError as error:
        raise ReleaseError(f"Release date must be YYYY-MM-DD; got {raw_date!r}.") from error
    return raw_date


def read_text(path: Path) -> str:
    """Read a UTF-8 text file."""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    """Write a UTF-8 text file."""
    path.write_text(content, encoding="utf-8")


def update_pyproject(root: Path, version: str) -> None:
    """Update the project version in pyproject.toml."""
    path = root / "pyproject.toml"
    content = read_text(path)
    updated, count = PROJECT_VERSION_RE.subn(
        lambda match: f"{match.group(1)}{version}{match.group(3)}", content, count=1
    )
    if count != 1:
        raise ReleaseError("Could not find [project] version in pyproject.toml.")
    write_text(path, updated)


def update_citation(root: Path, version: str, release_date: str) -> None:
    """Update version and date-released in CITATION.cff."""
    path = root / "CITATION.cff"
    content = read_text(path)

    content, version_count = CITATION_VERSION_RE.subn(f"version: {version}", content, count=1)
    if version_count != 1:
        raise ReleaseError("Could not find version in CITATION.cff.")

    date_line = f'date-released: "{release_date}"'
    content, date_count = CITATION_DATE_RE.subn(date_line, content, count=1)
    if date_count == 0:
        content = content.replace(f"version: {version}\n", f"version: {version}\n{date_line}\n", 1)

    write_text(path, content)


def release_heading_pattern(version: str) -> re.Pattern[str]:
    """Return a regex matching a changelog release heading."""
    return re.compile(rf"(?m)^## {re.escape(version)} - (?P<date>\d{{4}}-\d{{2}}-\d{{2}})\n")


def find_next_heading(content: str, start: int) -> int:
    """Return the start of the next level-two heading or EOF."""
    match = re.search(r"(?m)^## ", content[start:])
    if not match:
        return len(content)
    return start + match.start()


def update_changelog(root: Path, version: str, release_date: str) -> None:
    """Move the Unreleased changelog block into a dated release section."""
    path = root / "CHANGELOG.md"
    content = read_text(path)
    release_pattern = release_heading_pattern(version)
    if release_pattern.search(content):
        updated = release_pattern.sub(f"## {version} - {release_date}\n", content, count=1)
        write_text(path, updated)
        return

    unreleased_match = re.search(r"(?m)^## Unreleased\n", content)
    if not unreleased_match:
        raise ReleaseError("Could not find ## Unreleased in CHANGELOG.md.")

    body_start = unreleased_match.end()
    next_heading = find_next_heading(content, body_start)
    unreleased_body = content[body_start:next_heading].strip()
    release_body = unreleased_body or UNRELEASED_TEMPLATE
    new_unreleased = f"## Unreleased\n\n{UNRELEASED_TEMPLATE}\n\n"
    release_block = f"## {version} - {release_date}\n\n{release_body}\n\n"
    updated = content[: unreleased_match.start()] + new_unreleased + release_block + content[next_heading:]
    write_text(path, updated)


def pyproject_version(root: Path) -> str:
    """Return the version from pyproject.toml."""
    match = PROJECT_VERSION_RE.search(read_text(root / "pyproject.toml"))
    if not match:
        raise ReleaseError("Could not find [project] version in pyproject.toml.")
    return match.group("version")


def citation_metadata(root: Path) -> tuple[str, str]:
    """Return version and date-released from CITATION.cff."""
    content = read_text(root / "CITATION.cff")
    version_match = re.search(r"(?m)^version: (?P<version>\S+)$", content)
    date_match = re.search(r'(?m)^date-released: "(?P<date>\d{4}-\d{2}-\d{2})"$', content)
    if not version_match:
        raise ReleaseError("Could not find version in CITATION.cff.")
    if not date_match:
        raise ReleaseError("Could not find date-released in CITATION.cff.")
    return version_match.group("version"), date_match.group("date")


def changelog_section(root: Path, version: str) -> tuple[str, str]:
    """Return the release date and body for a changelog version section."""
    content = read_text(root / "CHANGELOG.md")
    match = release_heading_pattern(version).search(content)
    if not match:
        raise ReleaseError(f"Could not find CHANGELOG.md section for {version}.")
    body_start = match.end()
    body_end = find_next_heading(content, body_start)
    body = content[body_start:body_end].strip()
    if not body:
        raise ReleaseError(f"CHANGELOG.md section for {version} is empty.")
    return match.group("date"), body


def validate_release(root: Path, version: str) -> None:
    """Validate that release metadata is internally consistent."""
    project = pyproject_version(root)
    citation_version, citation_date = citation_metadata(root)
    changelog_date, _ = changelog_section(root, version)

    errors = []
    if project != version:
        errors.append(f"pyproject.toml version is {project}, expected {version}.")
    if citation_version != version:
        errors.append(f"CITATION.cff version is {citation_version}, expected {version}.")
    if citation_date != changelog_date:
        errors.append(f"CITATION.cff date {citation_date} does not match changelog date {changelog_date}.")

    if errors:
        raise ReleaseError("\n".join(errors))


def release_notes(root: Path, version: str) -> str:
    """Return release notes for a version from CHANGELOG.md."""
    _, body = changelog_section(root, version)
    return body + "\n"


def run_uv_lock(root: Path) -> None:
    """Update uv.lock after pyproject.toml changes."""
    subprocess.run(["uv", "lock"], cwd=root, check=True)


def validate_release_version(raw_version: str | None) -> str:
    """Return a valid BENCHMATRIX_RELEASE_VERSION value."""
    if not raw_version:
        raise ReleaseError("Set BENCHMATRIX_RELEASE_VERSION=X.Y.Z before running this release target.")
    match = RELEASE_VERSION_RE.match(raw_version.strip())
    if not match:
        raise ReleaseError(f"BENCHMATRIX_RELEASE_VERSION must be X.Y.Z without a leading v; got {raw_version!r}.")
    return match.group("version")


def validate_version(args: argparse.Namespace) -> int:
    """Validate and print the release version used by Make targets."""
    version = validate_release_version(args.version)
    print(f"Release version is {version}.")
    return 0


def prepare(args: argparse.Namespace) -> int:
    """Prepare release metadata."""
    root = args.repo_root.resolve()
    version = normalize_version(args.version)
    release_date = validate_date(args.date or dt.date.today().isoformat())

    update_pyproject(root, version)
    update_citation(root, version, release_date)
    update_changelog(root, version, release_date)
    if not args.no_lock:
        run_uv_lock(root)
    validate_release(root, version)

    print(f"Prepared release {version} dated {release_date}.")
    if not args.no_lock:
        print("Updated uv.lock with uv lock.")
    return 0


def validate(args: argparse.Namespace) -> int:
    """Validate release metadata."""
    version = normalize_version(args.version)
    validate_release(args.repo_root.resolve(), version)
    print(f"Release metadata is consistent for {version}.")
    return 0


def notes(args: argparse.Namespace) -> int:
    """Write release notes for a version."""
    version = normalize_version(args.version)
    output = release_notes(args.repo_root.resolve(), version)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    root_parser = argparse.ArgumentParser(description=__doc__)
    root_parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root to operate on.")
    subparsers = root_parser.add_subparsers(dest="command", required=True)

    validate_version_parser = subparsers.add_parser("validate-version", help="Check release version syntax.")
    validate_version_parser.add_argument(
        "version",
        nargs="?",
        default=os.environ.get("BENCHMATRIX_RELEASE_VERSION"),
        help="Release version as X.Y.Z without a leading v. Defaults to BENCHMATRIX_RELEASE_VERSION.",
    )
    validate_version_parser.set_defaults(func=validate_version)

    prepare_parser = subparsers.add_parser("prepare", help="Update release metadata and uv.lock.")
    prepare_parser.add_argument("version", help="Release version, with or without a leading v.")
    prepare_parser.add_argument("--date", help="Release date as YYYY-MM-DD. Defaults to today.")
    prepare_parser.add_argument("--no-lock", action="store_true", help="Skip uv lock; intended for tests only.")
    prepare_parser.set_defaults(func=prepare)

    validate_parser = subparsers.add_parser("validate", help="Check release metadata consistency.")
    validate_parser.add_argument("version", help="Release version, with or without a leading v.")
    validate_parser.set_defaults(func=validate)

    notes_parser = subparsers.add_parser("notes", help="Print release notes from CHANGELOG.md.")
    notes_parser.add_argument("version", help="Release version, with or without a leading v.")
    notes_parser.add_argument("--output", type=Path, help="File to write release notes to.")
    notes_parser.set_defaults(func=notes)

    return root_parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
