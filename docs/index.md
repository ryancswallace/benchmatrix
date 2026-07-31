# benchmatrix documentation

![benchmatrix logo](assets/benchmatrix-logo.svg)

benchmatrix is a small layer on top of pytest-benchmark. It helps you define
repeatable benchmark matrices, attach strict JSON-safe metadata to benchmark
invocations, and parse pytest-benchmark JSON output into metric-aware result
objects.

Use this site by task type:

* **Tutorials** teach the first complete workflow from zero to a benchmark run.
* **How-to guides** solve focused tasks such as creating a benchmark matrix or
    parsing saved JSON results.
* **Reference** records exact APIs, compatibility commitments, and automation
    commands.
* **Explanation** describes architecture, policy, security posture, and design
    tradeoffs.
* **Maintainer runbooks** are operational checklists for releases, incidents,
    dependency updates, and repository administration.
* **Project** covers local development, contribution expectations, and changelog
    maintenance.

## Install

```bash
uv add benchmatrix
```

If the project does not use uv, install it with pip instead:

```bash
python -m pip install benchmatrix
```

## Quickstart

```python
from benchmatrix import BenchmarkCase, make_benchmark_test

implementations = {"builtin": sum}
cases = [BenchmarkCase.from_values("small", list(range(100)), work_units=100)]

test_sum_matrix = make_benchmark_test(implementations, cases)
```

Measure it three times with pytest-benchmark:

```bash
uv run benchmatrix measure --runs 3 --output benchmark-runs \
    path/to/test_benchmarks.py
```

The output directory contains the individual JSON results and a manifest that
records the pytest command and collection lifecycle.

For the full guided path, start with [First benchmark](tutorials/first-benchmark.md).
