# Changelog

All notable changes to benchmatrix will be documented in this file.

The project follows [Semantic Versioning](https://semver.org/) and the
compatibility expectations described in [the release policy](RELEASING.md).

## Unreleased

### Added

* Add `benchmatrix measure` as a managed pytest workflow with isolated pytest
    defaults, repeated-run collection, resumable manifests, and advanced pytest
    argument forwarding.
* Add compact text comparison summaries through `benchmatrix compare --summary`.
* Add `benchmatrix --version` and a complete GitHub Actions regression-gate
    guide.

### Changed

* Make the runtime container invoke the benchmatrix CLI, publish it only for
    reviewed GitHub Releases, and keep the development/test image internal.
* Streamline the README, first tutorial, examples, contributor setup, project
    navigation, and security-reporting guidance for new users.
* Prepare package metadata and release checks for the 1.1 release.

### Deprecated

### Removed

### Fixed

* Keep `measure --format json` and `collect --format json` stdout valid JSON by
    routing child pytest output to stderr.
* Reject duplicate or overlapping benchmark sources so one result file cannot
    masquerade as repeated-run evidence.
* Reject duplicate manifest paths, duplicate matrix cases and metrics, invalid
    callable factories, and incorrectly typed benchmark controls before
    measurement.
* Preserve unrelated pytest-benchmark metadata while preventing case metadata
    from replacing benchmatrix's schema fields.
* Validate tail-latency declarations and reject non-standard `NaN` and
    `Infinity` tokens in benchmark JSON.
* Publish the exact wheel and source archive reviewed on a draft GitHub Release
    instead of rebuilding and replacing them after approval.

### Security

## 1.0.0 - 2026-07-30

### Added

* Add a benchmatrix SVG logo to the README and documentation home page.
* Add first-class `BenchmarkRun` loading with top-level pytest-benchmark
    metadata and matrix dimension accessors.
* Add metric-aware comparison of baseline and candidate matrices, including
    explicit matched, missing, and incompatible cell results.
* Add strict, permissive, and disabled run-environment compatibility policies
    with structured blocking and warning findings.
* Add configurable regression thresholds by metric, implementation, case, or
    exact matrix cell, plus aggregate comparison outcomes.
* Add `benchmatrix compare` and `python -m benchmatrix` command-line entry
    points with text or JSON output and opt-in CI failure behavior.
* Add untimed result-validation and benchmark lifecycle hooks with structured
    invocation context and reliable cleanup after target or validation errors.
* Add repeated-run comparison groups with median aggregation, pairwise effect
    agreement, rounds, iterations, sample counts, IQR, CV, outlier diagnostics,
    cross-run environment checks, and explicit inadequate-evidence outcomes.
* Add first-class repeated-run collection with sequential
    `benchmatrix collect` execution, atomic provenance manifests, partial
    failure records, matrix/commit/environment validation, public
    `BenchmarkRunGroup` loading, and direct directory or manifest comparison.
* Add strict, discoverable `[tool.benchmatrix]` policy configuration for
    compatibility, evidence requirements, and default, metric, implementation,
    case, or exact-cell regression thresholds, with CLI override and JSON
    provenance reporting.
* Add strict, versioned `BenchmarkComparisonReport` decision records with
    deterministic JSON writing, typed loading, source and collection snapshots,
    policy and threshold provenance, compatibility and evidence diagnostics,
    CLI integration, and a golden version 1 compatibility fixture.
* Add resumable and retryable collection with manifest-command and target
    validation, original-working-directory reuse, collision-free recovery from
    partial files, bounded retry batches, retained failure history, retry
    diagnostics, and backward-compatible loading of version 1 run-group
    manifests.
* Add `benchmatrix policy show` and `benchmatrix policy validate` with explicit
    or discovered configuration, quiet CI validation, complete effective-policy
    inspection, and versioned text or JSON outcomes.
* Add deterministic Markdown comparison rendering through the Python API and
    CLI, plus direct append-only GitHub Actions step-summary delivery that can
    accompany canonical JSON output.

### Changed

* Harden result parsing for unique matrix cells, non-empty identifiers, strict
    numeric timing values, non-negative samples, positive work units, and
    validated run metadata.
* Declare the stable 1.x compatibility and latest-minor support policy, align
    the supported pytest floor at 8.4, and refresh package metadata around the
    complete collection and comparison workflow.
* Trim low-level constants and literal aliases from the stable package root,
    retaining primary workflow, policy, result, diagnostic, and provenance
    types, and remove private aliases from public annotations.
* Freeze the v1 Python, CLI, configuration, exit-status, exception, and
    serialized-document compatibility contracts, including explicit schema
    read-version windows and evolution rules.

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
