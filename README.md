<!-- markdownlint-disable MD033 -->
<p align="center">
  <a href="https://ryancswallace.github.io/benchmatrix/">
    <img
      alt="benchmatrix"
      src="https://raw.githubusercontent.com/ryancswallace/benchmatrix/main/docs/assets/benchmatrix-logo.svg"
      width="760"
    >
  </a>

</p>
<!-- markdownlint-enable MD033 -->

[![PyPI](https://img.shields.io/pypi/v/benchmatrix.svg)](https://pypi.org/project/benchmatrix/)
[![Python](https://img.shields.io/pypi/pyversions/benchmatrix.svg)](https://pypi.org/project/benchmatrix/)
[![CI](https://github.com/ryancswallace/benchmatrix/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ryancswallace/benchmatrix/actions/workflows/ci.yml)
[![Documentation](https://github.com/ryancswallace/benchmatrix/actions/workflows/docs.yml/badge.svg?branch=main)](https://ryancswallace.github.io/benchmatrix/)
[![License](https://img.shields.io/pypi/l/benchmatrix.svg)](https://github.com/ryancswallace/benchmatrix/blob/main/LICENSE)

<!-- markdownlint-disable MD033 -->
<p align="center">
  <strong>
    Compare Python performance across implementations and inputs with fewer false alarms.
  </strong>
</p>
<!-- markdownlint-enable MD033 -->

benchmatrix adds **benchmark matrices, repeated-run collection, and regression
checks** to [pytest-benchmark](https://pytest-benchmark.readthedocs.io/). Define
your implementations and input cases once; benchmatrix measures every
combination and compares a baseline with a candidate.

Before reporting a regression, it checks that both sides ran in compatible
environments, measured the same matrix, and collected enough evidence. Weak or
conflicting results are marked inconclusive instead of being called regressions.

```bash
uv run benchmatrix measure --runs 5 --output baseline tests/test_benchmarks.py
# Make a change, then measure again.
uv run benchmatrix measure --runs 5 --output candidate tests/test_benchmarks.py
uv run benchmatrix compare baseline candidate --fail-on-regression
```

Results are available as readable terminal output, versioned JSON, Markdown,
and GitHub Actions summaries.

<!-- markdownlint-disable MD033 -->
<p align="center">
  <a href="https://ryancswallace.github.io/benchmatrix/demo/">
    <img
      alt="Preview of benchmatrix collecting and comparing repeated benchmark runs"
      src="https://raw.githubusercontent.com/ryancswallace/benchmatrix/main/docs/assets/basic-demo.png"
      width="360"
    >
  </a>
  <br>
  <a href="https://ryancswallace.github.io/benchmatrix/demo/">
    Watch the short demo in your browser
  </a>
</p>
<!-- markdownlint-enable MD033 -->

> [!TIP]
> **Read the [benchmatrix documentation](https://ryancswallace.github.io/benchmatrix/)**
> for the quickstart, usage guides, and API reference.

## Install

```bash
uv add --dev benchmatrix
```

or:

```bash
python -m pip install benchmatrix
```

## Quickstart

Create a benchmark matrix from callables in a pytest file:

```python
from benchmatrix import BenchmarkCase, make_benchmark_test

implementations = {
    "builtin": sum,
    "loop": lambda vs: sum(v for v in vs),
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

Keep ordinary correctness tests alongside the generated benchmark; timing a
wrong answer does not make it useful evidence.

Collect a baseline, make your change, and collect a candidate on the same
machine:

```bash
uv run benchmatrix measure --runs 5 --output baseline tests/test_sum_benchmark.py
# Make the change you want to evaluate.
uv run benchmatrix measure --runs 5 --output candidate tests/test_sum_benchmark.py
```

Compare the repeated runs and fail the command when the evidence shows a
regression:

```bash
uv run benchmatrix compare baseline candidate --threshold 5% --fail-on-regression
```

Each output directory contains the individual pytest-benchmark JSON files and
a manifest recording the command, matrix, environment, and collection
lifecycle. Resume an interrupted collection without overwriting earlier runs:

```bash
uv run benchmatrix measure --resume --output candidate
uv run benchmatrix measure --retry-failed --output candidate
```

The same run and comparison model is available from Python:

```python
from benchmatrix import load_benchmark_run_group

baseline = load_benchmark_run_group("baseline")
candidate = load_benchmark_run_group("candidate")
comparison = baseline.compare_to(candidate)

for cell in comparison.regressed:
    print(cell.implementation_name, cell.case_name, cell.metric_name)
```

## Metrics

benchmatrix supports three ways to measure each benchmark:

| Metric | Meaning | Better result |
| --- | --- | --- |
| Single-call latency | Time required to complete one function call | Lower |
| Batch throughput | Number of declared work units completed per second | Higher |
| Tail latency | The slower end of the timing distribution (e.g., 95th percentile) | Lower |

## Comparison policy

Keep project-wide comparison rules in `pyproject.toml`:

```toml
[tool.benchmatrix.evidence]
minimum_runs = 3

[tool.benchmatrix.regression]
default_threshold_percent = 5.0

[tool.benchmatrix.regression.by_metric]
tail_latency = 8.0
```

Thresholds can also target an
implementation, case, or exact matrix cell. A CLI option overrides only the
corresponding setting; it does not discard the more specific rules.

Inspect or validate the effective policy without running a benchmark:

```bash
uv run benchmatrix policy show
uv run benchmatrix policy validate --quiet
```

See [Configuration and automation](https://ryancswallace.github.io/benchmatrix/reference/configuration/)
for the full schema and precedence rules.

## Reports and CI

benchmatrix's text output is intended for human readers. Complementary machine-
readable, versioned JSON reports can be generated and loaded later
programmatically:

```bash
uv run benchmatrix compare baseline candidate --format json > comparison.json
```

```python
from benchmatrix import load_comparison_report

report = load_comparison_report("comparison.json")
print(report.schema_version, report.passed, len(report.regressed))
```

The same decision can be rendered as Markdown or appended to a GitHub Actions
step summary:

```bash
uv run benchmatrix compare baseline candidate --format markdown
uv run benchmatrix compare baseline candidate --github-summary
```

## Comparison checks

Before classifying a change, benchmatrix checks that both sides contain
compatible environments and matching matrix cells.

For repeated runs it also reports rounds, iterations, sample counts, IQR,
coefficient of variation, and outliers. If the evidence is too thin or the runs
disagree, the result is marked inconclusive rather than a regression.

## Where benchmatrix fits

When using benchmatrix, pytest-benchmark still handles timing, calibration,
statistics, terminal output, and JSON export. benchmatrix adds the **matrix,
collection, and comparison layer**.

If you only need to time one function or inspect one run, pytest-benchmark may
already be enough. benchmatrix is useful when you repeatedly compare the same
operation across implementations and inputs, need auditable regression rules,
or want portable reports without adopting a hosted benchmarking service.

benchmatrix supports synchronous Python callables; it is _not_ a load-testing
tool or a production latency monitor.

## Contributing and community

Questions, bug reports, and feature ideas are welcome in
[GitHub Issues](https://github.com/ryancswallace/benchmatrix/issues). See the
[contributing guide](https://github.com/ryancswallace/benchmatrix/blob/main/CONTRIBUTING.md)
to make a change, and use
[private vulnerability reporting](https://github.com/ryancswallace/benchmatrix/security/advisories/new)
for security concerns. Published changes are listed in the
[release history](https://github.com/ryancswallace/benchmatrix/releases).

## License

benchmatrix is distributed under the
[MIT License](https://github.com/ryancswallace/benchmatrix/blob/main/LICENSE).
