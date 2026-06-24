#!/usr/bin/env python3
"""Run release prerequisite checks before preparing a release PR."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from create_release_pr import RELEASE_FILES, current_branch, status_paths
from prepare_release import ReleaseError, normalize_version, release_version_arg


@dataclass(frozen=True)
class CheckResult:
    """A release preflight check result."""

    name: str
    ok: bool
    message: str
    warning: bool = False


def run_command(
    command: list[str], *, cwd: Path, capture: bool = True, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a command with consistent text output handling."""
    return subprocess.run(command, cwd=cwd, check=check, text=True, capture_output=capture)


def tool_check(*tools: str) -> CheckResult:
    """Check that required commands are available."""
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        return CheckResult("tools", False, f"Missing command(s): {', '.join(missing)}")
    return CheckResult("tools", True, f"Found command(s): {', '.join(tools)}")


def git_branch_check(root: Path, base: str) -> CheckResult:
    """Check that the current branch is the release base branch."""
    try:
        branch = current_branch(root)
    except ReleaseError as error:
        return CheckResult("branch", False, str(error))
    if branch != base:
        return CheckResult("branch", False, f"Current branch is {branch!r}; switch to {base!r} before release prep.")
    return CheckResult("branch", True, f"Current branch is {base}.")


def local_changes_check(root: Path) -> CheckResult:
    """Check that only release metadata files have local changes."""
    changed = status_paths(root)
    unrelated = sorted(path for path in changed if path not in RELEASE_FILES)
    if unrelated:
        formatted = ", ".join(unrelated)
        return CheckResult("local changes", False, f"Unrelated local changes present: {formatted}")
    if changed:
        return CheckResult("local changes", True, "Only release metadata files have local changes.")
    return CheckResult("local changes", True, "Working tree is clean.")


def base_sync_check(root: Path, base: str) -> CheckResult:
    """Check that the local release base branch matches origin."""
    fetch = run_command(["git", "fetch", "origin", base], cwd=root)
    if fetch.returncode != 0:
        return CheckResult("base sync", False, f"Could not fetch origin/{base}: {fetch.stderr.strip()}")
    local = run_command(["git", "rev-parse", base], cwd=root)
    remote = run_command(["git", "rev-parse", f"origin/{base}"], cwd=root)
    if local.returncode != 0 or remote.returncode != 0:
        return CheckResult("base sync", False, f"Could not resolve {base} and origin/{base}.")
    if local.stdout.strip() != remote.stdout.strip():
        return CheckResult("base sync", False, f"Local {base} does not match origin/{base}.")
    return CheckResult("base sync", True, f"{base} matches origin/{base}.")


def gh_auth_check(root: Path) -> CheckResult:
    """Check GitHub CLI authentication."""
    result = run_command(["gh", "auth", "status", "--hostname", "github.com"], cwd=root)
    if result.returncode != 0:
        return CheckResult("GitHub auth", False, "GitHub CLI is not authenticated for github.com.")
    return CheckResult("GitHub auth", True, "GitHub CLI is authenticated.")


def github_token_check() -> CheckResult:
    """Check that GitHub API token environment is available for workflow linting."""
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        return CheckResult("GitHub API token", True, "GH_TOKEN or GITHUB_TOKEN is available.")
    return CheckResult(
        "GitHub API token",
        False,
        "Set GH_TOKEN or GITHUB_TOKEN so workflow lint can query GitHub.",
    )


def tag_absence_check(root: Path, tag: str) -> CheckResult:
    """Check that the release tag does not already exist locally or remotely."""
    local = run_command(["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"], cwd=root)
    if local.returncode == 0:
        return CheckResult("release tag", False, f"Local tag already exists: {tag}")
    remote = run_command(["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"], cwd=root)
    if remote.returncode == 0:
        return CheckResult("release tag", False, f"Remote tag already exists on origin: {tag}")
    if remote.returncode not in {0, 2}:
        return CheckResult("release tag", False, f"Could not check remote tag {tag}: {remote.stderr.strip()}")
    return CheckResult("release tag", True, f"Tag {tag} is available.")


def github_release_absence_check(root: Path, tag: str) -> CheckResult:
    """Check that a GitHub Release does not already exist for the tag."""
    result = run_command(["gh", "release", "view", tag, "--json", "url", "--jq", ".url"], cwd=root)
    if result.returncode == 0:
        return CheckResult("GitHub Release", False, f"GitHub Release already exists: {result.stdout.strip()}")
    return CheckResult("GitHub Release", True, f"No GitHub Release exists for {tag}.")


def pypi_environment_check(root: Path) -> CheckResult:
    """Try to check that the GitHub pypi environment is visible."""
    repo = run_command(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=root)
    if repo.returncode != 0 or not repo.stdout.strip():
        return CheckResult("pypi environment", False, "Could not determine GitHub repository.", warning=True)
    env = run_command(["gh", "api", f"repos/{repo.stdout.strip()}/environments/pypi", "--jq", ".name"], cwd=root)
    if env.returncode != 0:
        return CheckResult("pypi environment", False, "Could not verify GitHub environment 'pypi'.", warning=True)
    return CheckResult("pypi environment", True, "GitHub environment 'pypi' is visible.")


def run_preflight(root: Path, raw_version: str, base: str) -> int:
    """Run release preflight checks."""
    version = normalize_version(raw_version)
    tag = f"v{version}"
    checks = [
        tool_check("git", "gh", "uv"),
        git_branch_check(root, base),
        local_changes_check(root),
        base_sync_check(root, base),
        gh_auth_check(root),
        github_token_check(),
        tag_absence_check(root, tag),
        github_release_absence_check(root, tag),
        pypi_environment_check(root),
    ]

    failed = False
    for check in checks:
        if check.ok:
            print(f"PASS {check.name}: {check.message}")
        elif check.warning:
            print(f"WARN {check.name}: {check.message}")
        else:
            failed = True
            print(f"FAIL {check.name}: {check.message}")
    return 1 if failed else 0


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument(
        "version",
        nargs="?",
        help="Release version without a leading v. Defaults to BENCHMATRIX_RELEASE_VERSION.",
    )
    arg_parser.add_argument("--base", default="main", help="Release base branch.")
    arg_parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root to operate on.")
    return arg_parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    args = parser().parse_args(argv)
    try:
        return run_preflight(args.repo_root.resolve(), release_version_arg(args.version), args.base)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
