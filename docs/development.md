# Development

Use this page for local setup, focused checks, and the test layout. For the full
automation map, see [Configuration and automation](reference/configuration.md).

## Setup

```bash
make ready
make hooks-install
```

Use uv for Python dependency management. Outside the devcontainer, install
Node.js and npm so Markdown, spelling, and Dockerfile checks can run.

## Daily loop

```bash
make format
make check
```

Use focused commands while iterating:

```bash
make test
make lint
make typecheck
make docs
make workflow-lint
```

`make check` is the authoritative local validation command. It checks the uv
lockfile, Ruff, Markdown, Dockerfiles, GitHub Actions workflows, spelling,
secrets, Bandit, deptry, pip-audit, tests and coverage, minimum dependency
versions, basedpyright, documentation links, built distributions, and CycloneDX
SBOM generation.

## Testing

The default test command runs unit, property-based, integration, and packaging
smoke tests with branch coverage enabled:

```bash
make test
```

Useful focused runs:

```bash
uv run pytest -m unit
uv run pytest -m property
uv run pytest -m integration
uv run pytest -m "integration and slow"
uv run pytest -m "not slow"
```

Markers:

* `unit`: fast isolated tests for package behavior.
* `property`: Hypothesis-based tests for invariants and generated inputs.
* `integration`: tests that exercise installed packages or third-party runtime integrations.
* `slow`: slower subprocess or packaging tests.
* `numpy`: tests that require NumPy and are skipped if NumPy is unavailable.

Representative pytest-benchmark JSON fixtures live under
`tests/fixtures/benchmark_results/`. Prefer fixtures when a parser scenario is
easier to understand as JSON than as a large inline dictionary.

## Multi-version checks

Run the supported interpreter matrix before changes that may vary by Python
version:

```bash
make test-matrix
```

Nox uses uv-backed environments and locked dependencies. Useful sessions:

```bash
uv run nox -s tests-3.11
uv run nox --tags quality
uv run nox --tags docs
uv run nox -s release
```

## Documentation loop

Edit files under `docs/`, then run:

```bash
make docs
```

API reference pages are generated from docstrings, so update package docstrings
when public behavior changes.

## Working locations

* `src/benchmatrix/`: package implementation.
* `tests/`: unit, property, integration, and smoke tests.
* `tests/fixtures/benchmark_results/`: parser contract fixtures.
* `examples/`: runnable benchmark examples.
* `docs/`: MkDocs documentation source.
* `reports/`, `site/`, `dist/`, `.nox/`: generated local artifacts that should not be committed.
