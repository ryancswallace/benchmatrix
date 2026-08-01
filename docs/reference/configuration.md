# Configuration and automation

## Benchmark comparison policy

Store project-wide comparison rules under `[tool.benchmatrix]` so local and CI
decisions use the same reviewed policy:

```toml
[tool.benchmatrix.compatibility]
mode = "permissive"

[tool.benchmatrix.evidence]
minimum_runs = 5
minimum_samples_per_run = 5
minimum_rounds_per_run = 5
require_rounds = true
require_iterations = true
require_raw_samples_for_inference = true
minimum_tail_samples_per_run = 100
require_tail_iterations_one = true
maximum_cv = 0.10
maximum_outlier_fraction = 0.05

[tool.benchmatrix.inference]
method = "bca_bootstrap"
confidence_level = 0.95
resamples = 50000
random_seed = 0
multiplicity = "bonferroni"

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
| Minimum independent runs per side | `5` |
| Minimum round-duration observations per run and cell | `5` |
| Minimum reported rounds per run and cell | `5` |
| Require rounds and iterations | `true` |
| Require retained raw round-duration observations | `true` |
| Minimum tail-latency observations per run | `100` |
| Require one iteration per tail-latency round | `true` |
| Maximum CV or outlier fraction | No limit |
| Inference method | `bca_bootstrap` |
| Family confidence level | `0.95` |
| Bootstrap resamples | `50000` |
| Bootstrap policy seed | `0` |
| Matrix multiplicity correction | `bonferroni` |
| Paired precision target | Disabled |
| Default regression threshold | `5.0%` |

Threshold precedence is exact cell, case, implementation, metric, then the
default. Configuration rejects unknown benchmatrix keys, duplicate exact-cell
rules, unknown metrics, invalid policy values, fewer than 1,000 bootstrap
resamples, negative random seeds, and invalid or non-finite numeric values.

One separately launched pytest process is one independent run. Increasing
`minimum_samples_per_run` or `minimum_rounds_per_run` strengthens each run's
within-process estimate but does not increase the independent run count. CV and
outlier limits apply to every run separately; pooled diagnostics remain
descriptive report fields.

For tail latency, the effective observation minimum is the greater of
`minimum_samples_per_run` and `minimum_tail_samples_per_run`. With
`require_tail_iterations_one = true`, a p95 based on per-round averages of
multiple calls is inadequate for inference.

`bca_bootstrap` is the default formal run-level method. It uses a deterministic
cell-specific seed derived from `random_seed`; degenerate BCa adjustments are
reported as `percentile_bootstrap` fallbacks. `bonferroni` controls the
family-wise error rate across structurally comparable matrix cells. Set
`multiplicity = "none"` only for an exploratory per-cell interval without
matrix-wide control.

`legacy_consistency` is an explicit migration mode. It uses the schema version
1 observed pairwise-range decision rule and produces no formal confidence
interval. It is not a statistical test.

### Paired precision planning

Precision planning is disabled unless a positive target is configured:

```toml
[tool.benchmatrix.precision]
target_half_width_percent = 2.0
```

This policy is valid only for an explicitly paired comparison. Independent
comparison rejects an enabled precision policy rather than silently applying a
paired-variance assumption. Use `collect-paired` to create explicit matched
blocks and `compare PAIRED_DIR --paired` to retain that design. Ordinary
two-source CLI comparisons remain independent. The equivalent Python path uses
`collect_paired_benchmark_runs` and `BenchmarkPairedRunGroup.compare`.

For every structurally comparable paired cell, the planner uses pooled
within-AB/BA-stratum residual variability from signed paired log ratios and the
same nominal confidence and multiplicity family as inference. It treats
`s / sqrt(n)` as the standard error of a mean signed paired-log-ratio proxy,
converts the target to `log1p(target / 100)`, and finds the smallest fixed pair
count whose two-sided Student-t proxy width meets that multiplicative target.
The proxy differs from the formal ratio-of-marginal-medians estimand and does
not guarantee the requested paired BCa width or an absolute percentage-point
half-width around a nonzero effect.

The reported `required_pairs` is no lower than the active evidence minimum and
is rounded to the complete AB/BA-by-matrix-order design multiple;
`unconstrained_required_pairs` retains the raw statistical calculation. Pilot
variance uncertainty is not modeled with an assurance bound, so small-pilot
plans remain explicitly provisional. Zero within-stratum variability produces
an issue rather than a zero-width certainty claim.

The resulting pair count applies to a fresh future confirmatory collection
whose size is fixed in advance. The reported difference from the pilot count
is descriptive arithmetic only; it is not a recommendation to append runs to
the pilot. Precision planning is not power analysis, does not promise a
conclusive classification, and must not be used to collect until an interval
crosses a desired boundary.

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
    `evidence.minimum_samples_per_run`;
* `--inference-method` overrides `inference.method`;
* `--confidence-level` overrides `inference.confidence_level` with a fraction
    strictly between zero and one;
* `--bootstrap-resamples` overrides `inference.resamples`;
* `--random-seed` overrides `inference.random_seed`;
* `--multiplicity` overrides `inference.multiplicity`;
* `--precision-target` overrides `precision.target_half_width_percent` and
    requires an explicitly paired design.

For example, `--threshold 7%` changes the default while retaining configured
metric, implementation, case, and exact-cell rules. JSON comparison output
includes the selected configuration path, configured fields, CLI overrides,
the effective regression policy, and each cell's threshold scope and origin.

Override inference controls for one exploratory comparison without changing
the committed policy:

```bash
benchmatrix compare baseline-runs candidate-runs \
    --confidence-level 0.99 \
    --bootstrap-resamples 100000 \
    --random-seed 20260801 \
    --multiplicity none
```

The final option removes matrix-wide control, so output identifies the result
as exploratory. A single-run migration comparison must select the legacy rule
explicitly; lowering the evidence count alone does not make one run sufficient
for bootstrap inference:

```bash
benchmatrix compare baseline.json candidate.json \
    --minimum-runs 1 \
    --minimum-samples 0 \
    --inference-method legacy_consistency
```

Load the same policy through Python:

```python
from benchmatrix import load_benchmark_policy

config = load_benchmark_policy()

print(config.source)
print(config.compatibility)
print(config.evidence)
print(config.inference)
print(config.precision)
print(config.regression)
```

## Inspect and validate policy

Inspect the complete effective policy without running a benchmark:

```bash
benchmatrix policy show
```

The text output identifies whether configuration was discovered, explicitly
selected, disabled, or absent. It reports the source, configured fields,
compatibility mode, evidence requirements, inference controls, default
threshold, and every metric, implementation, case, and exact-cell selector.

Use versioned JSON for automation:

```bash
benchmatrix policy show --format json
```

The document identifies itself with `producer = "benchmatrix"`,
`kind = "benchmark_policy"`, and `schema_version = 3`. It includes `valid`,
`selection`, `source`, `configured_fields`, and the complete effective
compatibility, evidence, inference, precision, and regression policy.

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
