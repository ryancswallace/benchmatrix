# Changelog

All notable changes to benchmatrix will be documented in this file.

The project follows [Semantic Versioning](https://semver.org/), with the
additional pre-1.0 compatibility expectations described in
[the release policy](RELEASING.md).

## Unreleased

### Added

### Changed

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
