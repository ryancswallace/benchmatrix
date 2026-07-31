# benchmatrix documentation

![benchmatrix logo](assets/benchmatrix-logo.svg)

benchmatrix adds benchmark matrices, repeated-run collection, and regression
checks to pytest-benchmark. Define implementations and input cases once, then
measure every combination and compare a baseline with a candidate.

It checks that both sides measured the same matrix in compatible environments
and collected enough evidence before reporting a regression. Results can be
read in the terminal or saved as versioned JSON, Markdown, and GitHub Actions
summaries.

## What it adds

* **Matrix generation:** benchmark implementations across named input cases
    without hand-writing pytest parametrization.
* **Repeatable collection:** collect several runs into a validated manifest,
    with resume and retry support.
* **Trust checks:** report environment differences, missing cells, sample
    counts, variability, outliers, and inconclusive evidence.
* **Regression policy:** keep global or per-cell thresholds in
    `pyproject.toml` and use the same rules locally and in CI.
* **Portable reports:** emit human-readable text, strict versioned JSON,
    Markdown, or a GitHub Actions step summary.

## Install

```bash
uv add --dev benchmatrix
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

Measure a baseline and candidate on the same machine, then compare them:

```bash
uv run benchmatrix measure --runs 3 --output baseline \
    path/to/test_benchmarks.py
# Make the change you want to evaluate.
uv run benchmatrix measure --runs 3 --output candidate \
    path/to/test_benchmarks.py
uv run benchmatrix compare baseline candidate --fail-on-regression
```

Each output directory contains the individual pytest-benchmark JSON results and
a manifest recording the command, matrix, environment, and collection
lifecycle.

For a complete guided workflow, start with
[First benchmark](tutorials/first-benchmark.md). To see the commands run before
trying them, watch the [one-minute demo](demo/README.md).
