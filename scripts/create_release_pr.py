#!/usr/bin/env python3
"""Create or reuse a standardized release pull request."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from prepare_release import ReleaseError, normalize_version, release_version_arg, validate_release

RELEASE_FILES = ("pyproject.toml", "CITATION.cff", "CHANGELOG.md", "uv.lock")


@dataclass(frozen=True)
class ReleasePrPlan:
    """Standardized GitHub pull request metadata for a release."""

    version: str
    branch: str
    base: str
    commit_message: str
    title: str
    body: str


def release_pr_plan(raw_version: str, base: str) -> ReleasePrPlan:
    """Return standardized branch, commit, title, and body values."""
    version = normalize_version(raw_version)
    branch = f"release/v{version}"
    title = f"Release {version}"
    commit_message = f"Prepare benchmatrix {version} release"
    body = f"""## Summary
- Prepare benchmatrix {version} release metadata and changelog.
- Validate the release artifact set through `make check`.

## Verification
- [ ] `make check` passes locally
- [ ] Required pull request checks pass
"""
    return ReleasePrPlan(
        version=version,
        branch=branch,
        base=base,
        commit_message=commit_message,
        title=title,
        body=body,
    )


def run_command(
    command: list[str], *, cwd: Path, capture: bool = False, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a command with consistent text output handling."""
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
    )


def output(command: list[str], *, cwd: Path, check: bool = True) -> str:
    """Run a command and return stripped stdout."""
    return run_command(command, cwd=cwd, capture=True, check=check).stdout.rstrip()


def ensure_tools() -> None:
    """Ensure required external tools are available."""
    missing = [tool for tool in ("git", "gh") if shutil.which(tool) is None]
    if missing:
        raise ReleaseError(f"Missing required command(s): {', '.join(missing)}.")


def status_paths(root: Path) -> set[str]:
    """Return paths with tracked or untracked working-tree status."""
    status = output(["git", "status", "--porcelain=v1"], cwd=root)
    paths: set[str] = set()
    for line in status.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", maxsplit=1)[1]
        paths.add(path)
    return paths


def has_staged_changes(root: Path) -> bool:
    """Return whether the index has staged changes."""
    result = run_command(["git", "diff", "--cached", "--quiet"], cwd=root, check=False)
    return result.returncode == 1


def local_branch_exists(root: Path, branch: str) -> bool:
    """Return whether a local branch exists."""
    result = run_command(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=root, check=False)
    return result.returncode == 0


def current_branch(root: Path) -> str:
    """Return the current branch name."""
    branch = output(["git", "branch", "--show-current"], cwd=root)
    if not branch:
        raise ReleaseError("Cannot create a release PR from a detached HEAD.")
    return branch


def ensure_branch(root: Path, branch: str) -> None:
    """Switch to the release branch, creating it when needed."""
    if current_branch(root) == branch:
        return
    if local_branch_exists(root, branch):
        run_command(["git", "switch", branch], cwd=root)
    else:
        run_command(["git", "switch", "-c", branch], cwd=root)


def changed_release_files(root: Path) -> list[str]:
    """Return changed release files, rejecting unrelated local changes."""
    changed_paths = status_paths(root)
    release_paths = sorted(path for path in changed_paths if path in RELEASE_FILES)
    unrelated = sorted(path for path in changed_paths if path not in RELEASE_FILES)
    if unrelated:
        formatted = "\n".join(f"  - {path}" for path in unrelated)
        raise ReleaseError(f"Refusing to create a release PR with unrelated working-tree changes:\n{formatted}")
    return release_paths


def commit_release_changes(root: Path, plan: ReleasePrPlan, changed_files: list[str]) -> bool:
    """Stage and commit release metadata changes when present."""
    if not changed_files:
        return False
    run_command(["git", "add", "--", *RELEASE_FILES], cwd=root)
    if not has_staged_changes(root):
        return False
    run_command(["git", "commit", "-m", plan.commit_message], cwd=root)
    return True


def push_branch(root: Path, branch: str) -> None:
    """Push the release branch to origin."""
    run_command(["git", "push", "-u", "origin", branch], cwd=root)


def existing_pr_url(root: Path, branch: str) -> str | None:
    """Return the existing pull request URL for a branch, when one exists."""
    result = run_command(
        ["gh", "pr", "view", branch, "--json", "url", "--jq", ".url"],
        cwd=root,
        capture=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def create_pr(root: Path, plan: ReleasePrPlan, *, draft: bool) -> str:
    """Create the GitHub pull request and return its URL."""
    command = [
        "gh",
        "pr",
        "create",
        "--base",
        plan.base,
        "--head",
        plan.branch,
        "--title",
        plan.title,
        "--body",
        plan.body,
    ]
    if draft:
        command.append("--draft")
    return output(command, cwd=root)


def create_release_pr(root: Path, plan: ReleasePrPlan, *, draft: bool) -> str:
    """Create or reuse a standardized release pull request."""
    ensure_tools()
    validate_release(root, plan.version)
    changed_files = changed_release_files(root)
    ensure_branch(root, plan.branch)
    committed = commit_release_changes(root, plan, changed_files)
    if committed:
        print(f"Committed release changes with message: {plan.commit_message}")
    elif changed_files:
        raise ReleaseError("Release files changed before switching branches, but nothing was committed.")
    else:
        print("No uncommitted release metadata changes found; reusing the current branch state.")

    push_branch(root, plan.branch)
    pr_url = existing_pr_url(root, plan.branch)
    if pr_url:
        print(f"Release pull request already exists: {pr_url}")
        return pr_url

    pr_url = create_pr(root, plan, draft=draft)
    print(f"Created release pull request: {pr_url}")
    return pr_url


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument(
        "version",
        nargs="?",
        help="Release version without a leading v. Defaults to BENCHMATRIX_RELEASE_VERSION.",
    )
    arg_parser.add_argument("--base", default="main", help="Pull request base branch.")
    arg_parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root to operate on.")
    arg_parser.add_argument("--draft", action="store_true", help="Create the pull request as a draft.")
    return arg_parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    args = parser().parse_args(argv)
    try:
        plan = release_pr_plan(release_version_arg(args.version), args.base)
        _ = create_release_pr(args.repo_root.resolve(), plan, draft=args.draft)
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
