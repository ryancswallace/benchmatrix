# Changelog

All notable changes to benchmatrix will be documented in this file.

The project follows [Semantic Versioning](https://semver.org/), with the
additional pre-1.0 compatibility expectations described in
[the release policy](RELEASING.md).

## Unreleased

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## 0.3.0 - 2026-06-24

### Added

* Add runtime validation for benchmark metric names, implementation names, case
    names, work-unit names, empty matrices, non-callable implementations, and
    invalid case values.
* Add runnable factorial examples documentation and tests that verify example
    benchmark matrices remain collectable.
* Add docs section landing pages, a Project docs section, improved MkDocs
    navigation styling, and a prominent README link to the published docs site.
* Add pre-push `make check` automation and expanded workflow linting through
    pre-commit.

### Changed

* Reorganize project documentation under `docs/project/` and align README,
    package metadata, docs navigation, and runbook indexes with the published
    documentation site.
* Expand Ruff, basedpyright, pytest, coverage, spelling, and ignored-directory
    configuration to cover examples, scripts, docs helpers, and repository
    automation more consistently.
* Improve Docker, `.dockerignore`, and devcontainer setup for reproducible uv,
    Node, Docker, and Codex-compatible development workflows.
* Harden release helper scripts and tests around release-note output, existing
    release PR reuse, duplicate local tag detection, and warning-only preflight
    checks.

### Removed

* Remove local-only devcontainer mounts and run arguments from the shared
    devcontainer configuration.

### Fixed

* Prefer pytest-benchmark `name` with `fullname` as a fallback when parsing
    benchmark JSON rows.
* Handle repositories without GitHub Actions workflow files when running
    workflow linting.

## 0.2.4 - 2026-06-24

### Fixed

* Check out repository for context of `release` workflow

## 0.2.3 - 2026-06-23

### Fixed

* Ensure all assets uploaded to draft GitHub release

## 0.2.2 - 2026-06-23

### Changed

* Change documentation site from built-in MkDocs theme to Material theme
* Automate several steps of the release process

### Fixed

* Ensure all assets, including wheels and SBOMs attached to GitHub releases
* Standardize Markdown formatting on four spaces for indentation

## 0.2.1 - 2026-06-22

### Changed

* Fix release and release-verify workflow bugs preventing creation of PyPI
    releases.

## 0.2.0 - 2026-06-22

### Added

* Initial benchmark matrix utilities.
* pytest-benchmark JSON parsing and display utilities.
* Automated linting, typing, security, dependency, test, coverage, and package
    validation for local development and pull requests, including scheduled
    audits of locked dependencies for known vulnerabilities.
* Pre-commit automation, secret scanning, Markdown linting, GitHub Actions
    workflow linting, and repository text and binary file attributes.
* MkDocs documentation site with strict builds, generated API reference pages,
    and operational maintainer runbooks.
* Reproducible CycloneDX SBOM generation for locked runtime dependencies.
* uv-backed nox automation for supported-Python tests, quality checks, and
    release artifact smoke testing.
* GitHub pull request auto-labeling and labels-as-code configuration for
    maintainers.
* Dependabot automation for Python, Node, pre-commit, GitHub Actions, Docker,
    and devcontainer dependency updates.
* Repository settings-as-code plus external setup checklists for branch
    protection, security features, Pages, environments, and PyPI publishing.
* Focused Python dependency groups for test, lint, type, docs, security,
    release, and automation tooling, with `dev` as the aggregate group.
* Compatibility, lifecycle, security-fix, release-branch, and deprecation
    policy documentation.
* GitHub Actions CI/CD workflows for quality checks, multi-version and
    cross-OS tests, docs deployment, PyPI Trusted Publishing, artifact
    attestations, CodeQL, dependency review, OpenSSF Scorecard, and workflow
    linting.
* CI test and coverage report artifacts, documentation link checking, minimum-
    dependency tests, and post-release PyPI installation verification.
* Docker runtime and test images, local Docker targets, Docker-outside-of-Docker
    devcontainer support, Dockerfile linting, GHCR publishing, image
    SBOM/provenance, and critical-vulnerability image scanning.
