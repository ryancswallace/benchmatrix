# benchmatrix documentation

![benchmatrix logo](assets/benchmatrix-logo.svg)

benchmatrix adds benchmark matrices, repeated-run collection, paired
experiments, and regression checks to pytest-benchmark. Define implementations
and input cases once, then measure every combination and compare a baseline
with a candidate.

It checks that both sides measured the same matrix in compatible environments,
then uses independent process runs to calculate matrix-wide-adjusted confidence
intervals. Results can be read in the terminal or saved as versioned JSON,
Markdown, and GitHub Actions summaries.

## What it adds

* **Matrix generation:** benchmark implementations across named input cases
    without hand-writing pytest parametrization.
* **Repeatable collection:** collect several runs into a validated manifest,
    with resume and retry support.
* **Paired experimental design:** alternate atomic AB/BA blocks, balance matrix
    cell order, preserve matched dependence in BCa inference, and plan a fresh
    fixed-size follow-up experiment from paired pilot precision.
* **Trust checks:** report environment differences, missing cells, per-run
    observations, variability, outliers, confidence intervals, and
    inconclusive evidence.
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
uv run benchmatrix measure --runs 5 --output baseline \
    path/to/test_benchmarks.py
# Make the change you want to evaluate.
uv run benchmatrix measure --runs 5 --output candidate \
    path/to/test_benchmarks.py
uv run benchmatrix compare baseline candidate --fail-on-regression
```

Each output directory contains the individual pytest-benchmark JSON results and
a manifest recording the command, matrix, environment, and collection
lifecycle.

For a complete guided workflow, start with
[First benchmark](tutorials/first-benchmark.md). To see the commands run before
trying them, watch the [one-minute demo](demo/README.md).
