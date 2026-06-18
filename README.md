# benchmatrix

`benchmatrix` is a small matrix and results layer for
[`pytest-benchmark`](https://pytest-benchmark.readthedocs.io/). It helps define
repeatable benchmark suites across multiple implementations, input cases, and
metric views, then parse the JSON produced by pytest-benchmark into structured,
metric-aware results.

pytest-benchmark remains the measurement engine. It performs calibration,
timing, statistics, reporting, and JSON export. benchmatrix adds:

* implementation-by-case-by-metric pytest parameter matrices;
* strict JSON-safe metadata identifying each benchmark invocation;
* conventions for single-call latency, logical-work throughput, and local
  latency-distribution comparisons;
* parsing and concise display of benchmatrix-tagged pytest-benchmark JSON output.

benchmatrix is intended for synchronous Python callables. It is not a replacement
for pytest-benchmark, a load-testing tool, or a production latency monitor.
In particular, its tail-latency metric summarizes local pytest-benchmark
samples; it does not measure service p95/p99 latency under concurrent load.

## Basic usage

Define implementations and cases, then assign the generated pytest function to
a module-level `test_*` name:

```python
from benchmatrix import BenchmarkCase, make_benchmark_test

implementations = {
    "builtin": sum,
    "loop": lambda values: sum(value for value in values),
}
cases = [
    BenchmarkCase.from_values(
        "small",
        list(range(100)),
        work_units=100,
        work_unit_name="items",
    ),
]

test_sum_matrix = make_benchmark_test(implementations, cases)
```

Run it through pytest-benchmark and save machine-readable results:

```bash
uv run pytest path/to/test_benchmarks.py --benchmark-json benchmark.json
```

Parse benchmatrix-tagged rows separately:

```python
from benchmatrix import display_benchmark_rows, load_benchmark_json

display_benchmark_rows(load_benchmark_json("benchmark.json"))
```

## Development setup

From the root of the repository, open a terminal and run:

```bash
make ready
```

The environment is ready if the command passes.

Outside the devcontainer, install Node.js 22.18 or newer with npm; `make check` uses npm to run the CSpell spell checker.

Development uses Python 3.14 by default via `.python-version`. The package supports Python 3.11 through 3.14.

## Working locations

* `notebooks/` for demos
* `src/benchmatrix/` for the package implementation
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

## Examples

`examples/test_factorial_benchmarks_simplified.py` shows the generated-test API.
`examples/test_factorial_benchmarks.py` shows the equivalent explicit pytest
parametrization. Both compare iterative and recursive factorial implementations
across every supported metric.
