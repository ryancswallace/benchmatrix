#!/usr/bin/env python3
"""Create and push the annotated release tag from the default branch."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from prepare_release import ReleaseError, normalize_version, validate_release, validate_release_version


@dataclass(frozen=True)
class ReleaseTagPlan:
    """Standardized Git tag metadata for a release."""

    version: str
    tag: str
    base: str
    message: str


def release_version_arg(cli_version: str | None) -> str:
    """Return a version from the CLI argument or BENCHMATRIX_RELEASE_VERSION."""
    if cli_version is not None:
        return normalize_version(cli_version)
    return validate_release_version(os.environ.get("BENCHMATRIX_RELEASE_VERSION"))


def release_tag_plan(raw_version: str, base: str) -> ReleaseTagPlan:
    """Return standardized tag metadata."""
    version = normalize_version(raw_version)
    return ReleaseTagPlan(
        version=version,
        tag=f"v{version}",
        base=base,
        message=f"benchmatrix {version}",
    )


def run_command(
    command: list[str], *, cwd: Path, capture: bool = False, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a command with consistent text output handling."""
    return subprocess.run(command, cwd=cwd, check=check, text=True, capture_output=capture)


def output(command: list[str], *, cwd: Path, check: bool = True) -> str:
    """Run a command and return stripped stdout."""
    return run_command(command, cwd=cwd, capture=True, check=check).stdout.strip()


def ensure_git() -> None:
    """Ensure Git is available."""
    if shutil.which("git") is None:
        raise ReleaseError("Missing required command: git.")


def current_branch(root: Path) -> str:
    """Return the current branch name."""
    branch = output(["git", "branch", "--show-current"], cwd=root)
    if not branch:
        raise ReleaseError("Cannot tag a release from a detached HEAD.")
    return branch


def ensure_clean_tree(root: Path) -> None:
    """Require a clean working tree before switching, pulling, or tagging."""
    status = output(["git", "status", "--porcelain=v1"], cwd=root)
    if status:
        raise ReleaseError("Refusing to tag with local working-tree changes.")


def switch_to_base(root: Path, base: str) -> None:
    """Switch to the release base branch."""
    if current_branch(root) != base:
        run_command(["git", "switch", base], cwd=root)


def local_tag_exists(root: Path, tag: str) -> bool:
    """Return whether the release tag exists locally."""
    result = run_command(["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"], cwd=root, check=False)
    return result.returncode == 0


def remote_tag_exists(root: Path, tag: str) -> bool:
    """Return whether the release tag exists on origin."""
    result = run_command(
        ["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"], cwd=root, check=False
    )
    return result.returncode == 0


def create_release_tag(root: Path, plan: ReleaseTagPlan) -> None:
    """Create and push the release tag from an up-to-date base branch."""
    ensure_git()
    ensure_clean_tree(root)
    switch_to_base(root, plan.base)
    run_command(["git", "pull", "--ff-only", "origin", plan.base], cwd=root)
    validate_release(root, plan.version)
    if local_tag_exists(root, plan.tag):
        raise ReleaseError(f"Local tag already exists: {plan.tag}")
    if remote_tag_exists(root, plan.tag):
        raise ReleaseError(f"Remote tag already exists on origin: {plan.tag}")
    run_command(["git", "tag", "-a", plan.tag, "-m", plan.message], cwd=root)
    run_command(["git", "push", "origin", plan.tag], cwd=root)
    print(f"Pushed release tag {plan.tag} from {plan.base}.")


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument(
        "version",
        nargs="?",
        help="Release version without a leading v. Defaults to BENCHMATRIX_RELEASE_VERSION.",
    )
    arg_parser.add_argument("--base", default="main", help="Branch to tag after pulling with --ff-only.")
    arg_parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root to operate on.")
    return arg_parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    args = parser().parse_args(argv)
    try:
        create_release_tag(args.repo_root.resolve(), release_tag_plan(release_version_arg(args.version), args.base))
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
