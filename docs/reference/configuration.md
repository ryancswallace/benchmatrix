# Configuration and automation

## Benchmark comparison policy

Store project-wide comparison rules under `[tool.benchmatrix]` so local and CI
decisions use the same reviewed policy:

```toml
[tool.benchmatrix.compatibility]
mode = "permissive"

[tool.benchmatrix.evidence]
minimum_runs = 3
minimum_samples_per_run = 5
require_rounds = true
require_iterations = true
maximum_cv = 0.10
maximum_outlier_fraction = 0.05

[tool.benchmatrix.regression]
default_threshold_percent = 5.0

[tool.benchmatrix.regression.by_metric]
tail_latency = 8.0
batch_throughput = 4.0

[tool.benchmatrix.regression.by_implementation]
reference = 3.0

[tool.benchmatrix.regression.by_case]
large = 10.0

[[tool.benchmatrix.regression.by_cell]]
implementation = "reference"
case = "large"
metric = "tail_latency"
threshold_percent = 12.0
```

`benchmatrix compare` searches from the current directory upward and inspects
the nearest `pyproject.toml`. Discovery stops at that project boundary; it does
not inherit policy from a parent project when the nearest pyproject has no
`[tool.benchmatrix]` table. With no selected table, built-in defaults remain:

| Setting | Built-in default |
| --- | --- |
| Compatibility mode | `permissive` |
| Minimum runs per side | `2` |
| Minimum samples per run and cell | `5` |
| Require rounds and iterations | `true` |
| Maximum CV or outlier fraction | No limit |
| Default regression threshold | `5.0%` |

Threshold precedence is exact cell, case, implementation, metric, then the
default. Configuration rejects unknown benchmatrix keys, duplicate exact-cell
rules, unknown metrics, invalid policy values, and negative or non-finite
thresholds.

Select another TOML file explicitly or disable discovery:

```bash
benchmatrix compare baseline-runs candidate-runs \
    --config config/benchmark-policy.toml

benchmatrix compare baseline-runs candidate-runs --no-config
```

An explicit file uses the same `[tool.benchmatrix]` layout and must contain that
table. `--config` and `--no-config` are mutually exclusive.

CLI policy options take precedence only for the corresponding scalar:

* `--compatibility` overrides `compatibility.mode`;
* `--threshold` overrides `regression.default_threshold_percent`;
* `--minimum-runs` overrides `evidence.minimum_runs`;
* `--minimum-samples` overrides
    `evidence.minimum_samples_per_run`.

For example, `--threshold 7%` changes the default while retaining configured
metric, implementation, case, and exact-cell rules. JSON comparison output
includes the selected configuration path, configured fields, CLI overrides,
the effective regression policy, and each cell's threshold scope and origin.

Load the same policy through Python:

```python
from benchmatrix import load_benchmark_policy

config = load_benchmark_policy()

print(config.source)
print(config.compatibility)
print(config.evidence)
print(config.regression)
```

## Inspect and validate policy

Inspect the complete effective policy without running a benchmark:

```bash
benchmatrix policy show
```

The text output identifies whether configuration was discovered, explicitly
selected, disabled, or absent. It reports the source, configured fields,
compatibility mode, evidence requirements, default threshold, and every metric,
implementation, case, and exact-cell selector.

Use versioned JSON for automation:

```bash
benchmatrix policy show --format json
```

The document identifies itself with `producer = "benchmatrix"`,
`kind = "benchmark_policy"`, and `schema_version = 1`. It includes `valid`,
`selection`, `source`, `configured_fields`, and the complete effective
compatibility, evidence, and regression policy.

Validate configuration in CI without collecting or comparing runs:

```bash
benchmatrix policy validate
benchmatrix policy validate --config config/benchmark-policy.toml
benchmatrix policy validate --quiet
```

A valid policy exits `0`. Invalid TOML, schema keys, selector names, metrics, or
values exit `2`. `--quiet` suppresses successful output. JSON validation emits
a versioned document for both outcomes, including `valid = false` and the
validation error when invalid:

```bash
benchmatrix policy validate \
    --config config/benchmark-policy.toml \
    --format json
```

Both actions accept `--search-from PATH` to test discovery from another project
location and `--no-config` to inspect built-in defaults.

## Authoritative checks

Run the complete local validation suite with:

```bash
make check
```

It verifies the lockfile, Ruff, Markdown, Dockerfiles, GitHub Actions workflows,
repository workflow environment references, spelling, secret scanning, Bandit,
deptry, pip-audit, tests and coverage, minimum direct dependency versions,
basedpyright, documentation links, distribution metadata, and SBOM generation.

## Dependency groups

Python development dependencies are organized into focused dependency groups:
`test`, `lint`, `type`, `docs`, `security`, `release`, and `automation`. The
aggregate `dev` group includes all of them and remains the default local
development environment used by `make install`, CI, nox, and the devcontainer.

Use focused groups only when you intentionally need a smaller environment, for
example:

```bash
uv sync --locked --only-group docs
uv sync --locked --only-group security
```

## Documentation

Build the documentation site with:

```bash
make docs
```

Check links in the built site with:

```bash
make docs-linkcheck
```

`make docs-linkcheck` runs `mkdocs build --strict` and then checks the generated
site with LinkChecker. API pages under `reference/api/` are generated from
package docstrings during the build.

MkDocs is configured to treat documentation warnings as failures. Navigation
entries, local links, anchors, and generated API reference pages must stay in
sync with the source tree. The local development server also watches
`src/benchmatrix/` so docstring changes can refresh generated reference pages.

Spelling checks include regular repository files and hidden GitHub configuration
under `.github/`, so issue templates, workflow names, and pull request template
text stay covered by the same `make spellcheck` target.

## Repository settings

Repository settings that can be managed as code are declared in `.github/settings.yml`.
The file is intended for the GitHub Settings app and covers repository metadata,
merge strategy defaults, vulnerability alert settings, and `main` branch
protection. External setup that still requires a service UI is tracked in the
external repository setup runbook.

## GitHub Actions workflows

The repository uses focused workflows that call the same Make targets used
locally:

* `.github/workflows/ci.yml` runs quality checks, supported-Python tests,
    coverage and JUnit report artifact upload, minimum-dependency tests,
    packaging smoke checks, SBOM generation, and scheduled dependency audits.
* `.github/workflows/docs.yml` builds docs, checks generated-site links, uploads
    the link-check report, and deploys the MkDocs site from `main` through GitHub
    Pages.
* `.github/workflows/draft-release.yml` validates release metadata when a `v*`
    tag is pushed, extracts release notes from `CHANGELOG.md`, builds and
    verifies release assets, and creates or updates the draft GitHub Release
    with the package source distribution, wheel, and SBOM attached; it also
    supports manual dispatch for retrying an existing tag.
* `.github/workflows/release.yml` downloads the package assets reviewed on the
    published GitHub Release, validates and attests those exact files, stores
    them as Actions artifacts, publishes the distributions to PyPI through
    Trusted Publishing, and verifies installation after publication.
* `.github/workflows/release-verify.yml` manually re-runs post-release
    installation verification from PyPI.
* `.github/workflows/docker.yml` builds and scans the runtime image and internal
    test stage. It publishes only the runtime image, and only after a reviewed
    `v*` GitHub Release is published.
* `.github/workflows/workflow-lint.yml` runs actionlint and zizmor for workflow
    configuration changes, using `.github/zizmor.yml` for project-specific audit
    policy.
* `.github/workflows/labeler.yml` applies pull request labels from
    `.github/labeler.yml` without checking out untrusted pull request code.
* `.github/workflows/codeql.yml`, `.github/workflows/dependency-review.yml`,
    and `.github/workflows/scorecard.yml` provide GitHub-native security and
    supply-chain checks.

Standalone SBOM and artifact-attestation workflows are intentionally not added:
`make build`, CI packaging, and the draft-release workflow already generate
SBOMs, while release publication adds provenance without an extra scheduler.
Release drafting is limited to a
small tag-triggered workflow so the deployment action remains publishing the
reviewed GitHub Release.

## Pull request labels

Pull request labels are applied automatically by GitHub Actions:

* `.github/labeler.yml` maps changed files and branch names to labels.
* `.github/workflows/labeler.yml` runs `actions/labeler` on pull requests.
* `.github/labels.yml` documents the repository's recommended label set for
    maintainers.

Labels are not synced automatically. Create or update labels manually in GitHub
when the recommended label set changes.

## Dependabot

Dependency version update automation is configured in `.github/dependabot.yml`.
It runs weekly, uses conservative pull request limits, and covers the ecosystems
that have manifests in this repository:

* `uv` for `pyproject.toml` and `uv.lock`;
* `npm` for Markdown and spelling tooling in `package.json`;
* `pre-commit` for hook revisions in `.pre-commit-config.yaml`;
* `github-actions` for workflow actions under `.github/workflows/`;
* `docker` for the runtime Docker image and devcontainer base images;
* `devcontainers` for devcontainer features.

Dependabot pull requests should be labeled with `dependencies` and
`maintenance`, plus a more specific label such as `github-actions`,
`automation`, or `dev-environment` where applicable.

## Multi-version automation

Run tests against the minimum direct dependency set on the oldest supported
Python version with:

```bash
make test-min-deps
```

Run the nox matrix with:

```bash
make test-matrix
```

Useful focused sessions:

```bash
uv run nox -s tests-3.11
uv run nox --tags quality
uv run nox --tags docs
uv run nox -s release
```

## Docker images

Build and smoke-test the runtime image locally with:

```bash
make docker-build
make docker-smoke
```

Build and run the test image locally with:

```bash
make docker-test
```

Run all local Docker checks with:

```bash
make docker-check
```

Scan locally built images for critical vulnerabilities with:

```bash
make docker-scan
```

`make check` runs Dockerfile linting but does not build Docker images, so normal
local validation does not require a Docker daemon. The devcontainer includes the
Docker-outside-of-Docker feature so contributors can run `make docker-check`
after rebuilding the devcontainer. The Docker workflow builds and scans both
stages in GitHub Actions, then publishes the runtime stage for releases.

## Generated artifacts

* `dist/` contains built distributions and generated SBOMs.
* `reports/` contains local test, coverage, and link-check reports.
* `site/` contains the local MkDocs output.
* `.nox/` contains local nox environments.

These directories are local artifacts and should not be committed.
