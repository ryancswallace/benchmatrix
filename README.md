<!-- markdownlint-disable MD033 -->
<p align="center">
  <a href="https://ryancswallace.github.io/benchmatrix/">
    <img
      alt="benchmatrix"
      src="docs/assets/benchmatrix-logo.svg"
      style="padding-bottom: 25px;"
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

**Benchmark matrices for Python projects that need performance data they can
trust, compare, and parse.**

<!-- markdownlint-disable MD033 -->
<p align="center">
  <a href="https://ryancswallace.github.io/benchmatrix/">
    <img
      alt="Open the benchmatrix documentation"
      src="https://img.shields.io/badge/Open%20the%20docs-benchmatrix%20documentation-0f766e?style=for-the-badge&logo=githubpages&logoColor=white"
    >
  </a>
</p>
<!-- markdownlint-enable MD033 -->

benchmatrix sits on top of
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/) and adds the layer
that benchmark suites usually grow by hand: implementation-by-case matrices,
strict JSON-safe metadata, metric-aware result parsing, and concise display of
saved benchmark runs.

| Build repeatable suites | Keep metrics honest | Parse saved runs |
| --- | --- | --- |
| Generate pytest benchmark tests across implementations, cases, and metric views. | Separate latency, throughput, and local distribution comparisons instead of mixing unlike numbers. | Load benchmatrix-tagged pytest-benchmark JSON rows into structured Python objects. |

## Quick Start

Create a benchmark matrix from ordinary synchronous callables in a pytest file:

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

Run it with pytest-benchmark and keep the machine-readable output:

```bash
uv run pytest tests/test_sum_benchmark.py --benchmark-json benchmark.json
```

Read the tagged rows back later:

```python
from benchmatrix import display_benchmark_rows, load_benchmark_json

rows = load_benchmark_json("benchmark.json")
display_benchmark_rows(rows)
```

## Why It Exists

pytest-benchmark owns timing, calibration, statistics, terminal reporting, and
JSON export. benchmatrix owns the repeatable structure around those timings.

| Need | benchmatrix gives you |
| --- | --- |
| Compare multiple implementations | One generated pytest benchmark matrix instead of repeated parametrization code. |
| Track what each timing means | JSON-safe invocation metadata with implementation, case, and metric identity. |
| Report different metric views | Single-call latency, logical-work throughput, and local tail-latency summaries. |
| Reuse benchmark output | Parsers and display helpers for pytest-benchmark JSON produced by benchmatrix tests. |

benchmatrix is intentionally narrow: it benchmarks synchronous Python callables.
It is not a load-testing framework, production latency monitor, or replacement
for pytest-benchmark.

## Interpreting Results

Benchmark output is environment-specific. Compare results only between runs from
controlled environments, and keep the pytest-benchmark JSON output with the
hardware, Python, dependency, and CI context that produced it.

Use metric names as part of every comparison:

* single-call latency compares one completed synchronous target call;
* batch throughput compares logical work per second when `work_units` is
    meaningful and consistent;
* tail-latency summaries describe local distribution shape for a benchmark run,
    not production service latency.

## Install

Install the released package with uv:

```bash
uv add benchmatrix
```

or with pip:

```bash
python -m pip install benchmatrix
```

For local development from this repository:

```bash
make ready
```

## Documentation

The documentation source lives under [`docs/`](docs/). The top-level Markdown
files are short project entry points; detailed guides, explanations, references,
and runbooks live in the MkDocs documentation.

| Start here | Use it for |
| --- | --- |
| [First benchmark](docs/tutorials/first-benchmark.md) | A complete first benchmark from test file to parsed JSON. |
| [Create a benchmark matrix](docs/how-to/create-benchmark-matrix.md) | Cases, work units, fresh inputs, and synchronous target wrappers. |
| [Parse benchmark results](docs/how-to/parse-results.md) | Loading and displaying benchmatrix-tagged pytest-benchmark JSON. |
| [Performance model](docs/explanation/performance.md) | What the metrics mean and what they do not prove. |
| [Development](docs/project/development.md) | Local setup, test commands, and repository layout. |
| [Compatibility](docs/reference/compatibility.md) | Supported Python versions, API stability, and support policy. |
| [Publishing](docs/explanation/publishing.md) | Release artifacts, draft releases, PyPI publishing, and verification. |
| [Configuration and automation](docs/reference/configuration.md) | Make targets, CI workflows, Docker checks, docs, and SBOM generation. |

The MkDocs site builds in strict mode and generates API reference pages from the
package docstrings.

## Project Links

* [Examples](examples/)
* [Contributing](CONTRIBUTING.md)
* [Changelog](CHANGELOG.md)
* [Security policy](SECURITY.md)
* [Release policy](RELEASING.md)
* [Code of conduct](CODE_OF_CONDUCT.md)
* [Citation metadata](CITATION.cff)

## License

benchmatrix is distributed under the [MIT License](LICENSE).
