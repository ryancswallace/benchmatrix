# benchkit

## Development setup

From the root of the repository, open a terminal and run:

```bash
make ready
```

The environment is ready if the command passes.

Outside the devcontainer, install Node.js 22.18 or newer with npm; `make check` uses npm to run the CSpell spell checker.

## Working locations

* `notebooks/` for demos
* `src/benchkit/` for the package implementation
* `tests/` for tests
* `data/` for provided dummy test data

## Useful commands

```bash
make install
make test
make lint
make spellcheck
make check
make format
make clean
```

## Testing

The test suite uses pytest and pytest-cov. The default test command runs unit, property-based, integration, and packaging smoke tests:

```bash
make test
```

Coverage is configured in `pyproject.toml` with branch coverage enabled and a minimum total coverage threshold. The default pytest run prints missing lines and fails if coverage drops below the configured threshold.

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
* `property`: Hypothesis-based tests for invariants and broader generated inputs.
* `integration`: tests that exercise third-party runtime integrations or installed-package behavior.
* `slow`: slower subprocess or packaging tests.
* `numpy`: tests that require NumPy and are skipped if NumPy is unavailable.

Representative pytest-benchmark JSON fixtures live under `tests/fixtures/benchmark_results/`. Use these for parser contract tests when a scenario is easier to understand as a JSON artifact than as a large inline dictionary.
