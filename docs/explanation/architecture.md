# Architecture

benchmatrix has two main responsibilities:

1. generate pytest benchmark matrices from implementations, cases, and metrics;
2. parse pytest-benchmark JSON rows that carry benchmatrix metadata.

pytest-benchmark remains responsible for measurement. benchmatrix does not
replace its calibration, timing, statistics, terminal reporting, or JSON export.

## Package boundaries

* `bench_harness.py` builds benchmark tests and invocation metadata.
* `bench_results.py` parses and displays saved benchmark results.
* `exceptions.py` contains package-specific exceptions.
* `_schema.py` is a private schema constant module shared by implementation
    code.
* `__init__.py` defines the public package exports.

## Design constraints

Metadata must stay strict-JSON-safe because it is serialized through
pytest-benchmark output. Benchmark targets are synchronous only so the measured
unit is one completed target call.

## Extension point

The stable extension point is the public API exported by `benchmatrix`. Private
module structure can change when implementation details are simplified.
