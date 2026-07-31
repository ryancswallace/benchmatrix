<!-- markdownlint-disable MD033 -->
<p align="center">
  <a href="https://ryancswallace.github.io/benchmatrix/">
    <img
      alt="benchmatrix"
      src="docs/assets/benchmatrix-logo.svg"
      width="760"
    >
  </a>

</p>
<!-- markdownlint-enable MD033 -->

[![CI](https://github.com/ryancswallace/benchmatrix/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ryancswallace/benchmatrix/actions/workflows/ci.yml)
[![Documentation](https://github.com/ryancswallace/benchmatrix/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/ryancswallace/benchmatrix/actions/workflows/docs.yml)
[![Docker](https://github.com/ryancswallace/benchmatrix/actions/workflows/docker.yml/badge.svg?branch=main)](https://github.com/ryancswallace/benchmatrix/actions/workflows/docker.yml)
[![CodeQL](https://github.com/ryancswallace/benchmatrix/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/ryancswallace/benchmatrix/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://github.com/ryancswallace/benchmatrix/actions/workflows/scorecard.yml/badge.svg?branch=main)](https://github.com/ryancswallace/benchmatrix/actions/workflows/scorecard.yml)
[![Workflow lint](https://github.com/ryancswallace/benchmatrix/actions/workflows/workflow-lint.yml/badge.svg?branch=main)](https://github.com/ryancswallace/benchmatrix/actions/workflows/workflow-lint.yml)
[![Python 3.11-3.14](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB?logo=python&logoColor=white)](https://github.com/ryancswallace/benchmatrix/blob/main/pyproject.toml)
[![Typed with basedpyright](https://img.shields.io/badge/types-basedpyright-2f6fdd)](https://github.com/DetachHead/basedpyright)
[![Linted with Ruff](https://img.shields.io/badge/lint-Ruff-46a2f1)](https://docs.astral.sh/ruff/)
[![Coverage gate: 95%](https://img.shields.io/badge/coverage%20gate-%E2%89%A595%25-2e7d32)](https://github.com/ryancswallace/benchmatrix/blob/main/pyproject.toml)
[![SBOM: CycloneDX 1.6](https://img.shields.io/badge/SBOM-CycloneDX%201.6-6f42c1)](https://cyclonedx.org/)

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
benchmatrix measure --runs 5 --output baseline tests/test_benchmarks.py
# Make a change, then measure again.
benchmatrix measure --runs 5 --output candidate tests/test_benchmarks.py
benchmatrix compare baseline candidate --fail-on-regression
```

Results are available as readable terminal output, versioned JSON, Markdown,
and GitHub Actions summaries.

> [!TIP]
> **Read the [benchmatrix documentation](https://ryancswallace.github.io/benchmatrix/)**
> for the quickstart, usage guides, and API reference.

## Install

```bash
uv add benchmatrix
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

Run it with pytest-benchmark:

```bash
uv run pytest tests/test_sum_benchmark.py --benchmark-json benchmark.json
```

The result is normal pytest-benchmark JSON enhanced with benchmatrix metadata.
Load and compare it with a baseline to check for regressions:

```python
from benchmatrix import load_benchmark_run

baseline = load_benchmark_run("baseline.json")
candidate = load_benchmark_run("benchmark.json")
comparison = baseline.compare_to(candidate)

for cell in comparison.regressed:
    print(cell.implementation_name, cell.case_name, cell.metric_name)
```

For regression decisions, collect several runs instead of relying on one noisy
percentage:

```bash
benchmatrix measure --runs 5 --output benchmark-runs tests/test_sum_benchmark.py
```

The output directory contains numbered JSON files and a
`benchmatrix-manifest.json`.

Interrupted and failed collections can continue without overwriting earlier
attempts:

```bash
benchmatrix measure --resume --output benchmark-runs
benchmatrix measure --retry-failed --output benchmark-runs
```

Compare a baseline collection with a candidate:

```bash
benchmatrix compare baseline-runs candidate-runs \
    --threshold 5% \
    --fail-on-regression
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
benchmatrix policy show
benchmatrix policy validate --quiet
```

See [Configuration and automation](docs/reference/configuration.md) for the full
schema and precedence rules.

## Reports and CI

benchmatrix's text output is intended for human readers. Complementary machine-
readable, versioned JSON reports can be generated and loaded later
programmatically:

```bash
benchmatrix compare baseline-runs candidate-runs --format json > comparison.json
```

```python
from benchmatrix import load_comparison_report

report = load_comparison_report("comparison.json")
print(report.schema_version, report.passed, len(report.regressed))
```

The same decision can be rendered as Markdown or appended to a GitHub Actions
step summary:

```bash
benchmatrix compare baseline-runs candidate-runs --format markdown
benchmatrix compare baseline-runs candidate-runs --github-summary
```

## Comparison checks

Before classifying a change, benchmatrix checks that both sides contain
compatible environments and matching matrix cells.

For repeated runs it also reports rounds, iterations, sample counts, IQR,
coefficient of variation, and outliers. If the evidence is too thin or the runs
disagree, the result is marked inconclusive rather than a regression.

## Design goals and non-goals

When using benchmatrix, pytest-benchmark still handles timing, calibration,
statistics, terminal output, and JSON export. benchmatrix adds the **matrix,
collection, and comparison layer**.

benchmatrix supports synchronous Python callables; it is _not_ a load-testing
tool or a production latency monitor.

## License

benchmatrix is distributed under the [MIT License](LICENSE).
