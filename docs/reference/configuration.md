# Configuration and automation

## Authoritative checks

Run the complete local validation suite with:

```bash
make check
```

It verifies the lockfile, Ruff, Markdown, GitHub Actions workflows, spelling,
secret scanning, Bandit, deptry, pip-audit, tests and coverage, minimum direct
dependency versions, basedpyright, documentation links, distribution metadata,
and SBOM generation.

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
* `.github/workflows/release.yml` builds release artifacts, attests them, and
  publishes to PyPI through Trusted Publishing.
* `.github/workflows/release-verify.yml` verifies post-release installation from
  PyPI after a GitHub Release is published.
* `.github/workflows/workflow-lint.yml` runs actionlint and zizmor for workflow
  configuration changes, using `.github/zizmor.yml` for project-specific audit
  policy.
* `.github/workflows/codeql.yml`, `.github/workflows/dependency-review.yml`,
  and `.github/workflows/scorecard.yml` provide GitHub-native security and
  supply-chain checks.

Standalone SBOM and artifact-attestation workflows are intentionally not added:
`make build`, CI packaging, and the release workflow already generate SBOMs and
release provenance without an extra scheduler. Release drafting is also left out
until the project has enough release volume to justify another automation path.

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
* `docker` for the devcontainer base image;
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

## Generated artifacts

* `dist/` contains built distributions and generated SBOMs.
* `reports/` contains local test, coverage, and link-check reports.
* `site/` contains the local MkDocs output.
* `.nox/` contains local nox environments.

These directories are local artifacts and should not be committed.
