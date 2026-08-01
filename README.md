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

benchmatrix adds **benchmark matrices, repeated-run collection, paired
experiments, and regression checks** to
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/). Define your
implementations and input cases once; benchmatrix measures every combination
and compares a baseline with a candidate.

Before reporting a regression, it checks that both sides ran in compatible
environments, measured the same matrix, and collected enough independent runs.
It then calculates a run-level confidence interval and separates meaningful
changes, practical equivalence, and inconclusive results.

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
    Watch benchmatrix catch an intentional regression (1 minute)
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

For a drift-resistant experiment, collect adjacent matched blocks with
`collect-paired`. Baseline-first (`AB`) and candidate-first (`BA`) blocks
alternate, and both members of a pair use the same balanced matrix-cell order.
Separate the two commands with `:::` after the usual `--` delimiter:

```bash
uv run benchmatrix collect-paired \
    --random-seed 20260801 \
    --output paired-runs \
    --baseline-cwd ../project-baseline \
    --candidate-cwd . \
    -- \
    uv run pytest --benchmark-only tests/test_sum_benchmark.py \
    ::: \
    uv run pytest --benchmark-only tests/test_sum_benchmark.py

uv run benchmatrix compare paired-runs --paired --precision-target 2%
```

The equivalent Python API is:

```python
from benchmatrix import collect_paired_benchmark_runs

pytest_command = (
    "uv",
    "run",
    "pytest",
    "--benchmark-only",
    "tests/test_sum_benchmark.py",
)
paired = collect_paired_benchmark_runs(
    pytest_command,
    pytest_command,
    "paired-runs",
    random_seed=20260801,
    baseline_cwd="../project-baseline",
    candidate_cwd=".",
)
comparison = paired.compare()
```

A pair contributes to inference only when both adjacent commands succeed in
the same block attempt. Resume and retry preserve every earlier record but
replace an incomplete block with a fresh two-command attempt. Use
`collect-paired --resume` after an interruption and
`collect-paired --retry-failed` for one new full-block attempt per incomplete
pair. Ordinary `measure`, `collect`, and two-source `compare` workflows remain
independent; `compare PAIRED_DIR --paired` is the explicit paired path.
When `--pairs`/`pair_count` is omitted, benchmatrix learns the matrix from the
first accepted command and chooses the smallest target of at least five pairs
that completes the joint AB/BA-by-cell-order supercycle. An explicit target is
useful for exploratory pilots, but manifest-backed formal comparison requires
a complete joint supercycle.

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
minimum_runs = 5

[tool.benchmatrix.inference]
method = "bca_bootstrap"
confidence_level = 0.95
resamples = 50000
random_seed = 0
multiplicity = "bonferroni"

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
compatible environments, matching matrix cells, and five independent process
runs by default. Raw pytest-benchmark rounds are nested observations used for
each run's statistic and diagnostics; they are not counted as independent
replicates of a code change.

The formal estimand is the direction-aware percentage ratio between the median
per-run statistic on each side. benchmatrix resamples complete process-run
statistics, calculates a deterministic BCa bootstrap interval, and falls back
to a clearly reported percentile-bootstrap interval when the BCa adjustment is
degenerate. Bonferroni adjustment controls the family-wise error rate across
the structurally comparable cells in the matrix by default.

Independent comparisons resample each side separately. Explicit paired
comparisons resample matched baseline/candidate tuples, preserving within-pair
dependence while leaving the estimand unchanged. Pairing is never guessed from
filenames, timestamps, or collection proximity. Manifest-backed paired
comparisons stratify resampling by the recorded AB/BA orientation, so every
bootstrap sample preserves the fixed orientation counts. The bootstrap does
not force each resample to preserve its exact matrix-order-row composition;
the collected supercycle crosses every row with both orientations before
formal comparison is allowed.

An optional `PrecisionPolicy` uses paired pilot log-ratio variability to
estimate the pair count for a **fresh, fixed-size future collection** at a
requested multiplicative log-ratio width proxy. This planning approximation is not
power analysis or a sequential stopping rule. It applies Student-t scaling to
a within-orientation mean signed paired-log-ratio proxy; that proxy is not the formal
ratio-of-marginal-medians estimand used by paired BCa inference, so the planned
count does not guarantee the requested BCa interval width. Plans never recommend
fewer pairs than the active evidence policy permits and round up to the paired
collection's complete design supercycle. Their
`additional_pairs` value is only the arithmetic difference from the pilot
size; it is not permission to append runs to the pilot and reuse those outcomes
as confirmatory evidence.

A cell is `regressed` or `improved` only when its complete adjusted interval is
beyond the configured practical threshold. It is `unchanged` only when the
complete interval is inside the practical-equivalence region. An interval that
crosses either boundary is `inconclusive`; failure to prove a regression is not
treated as proof of equivalence.

Evidence output includes per-run rounds, iterations, observation counts, IQR,
coefficient of variation, and outlier diagnostics. Tail-latency inference
requires 100 round-duration observations and one target iteration per round by
default.

A single run remains useful for descriptive comparison, but cannot produce the
default run-level interval and is therefore inconclusive. The explicit
`legacy_consistency` inference method preserves the earlier observed pairwise
range rule for migration and exploratory use; it is non-inferential.

## benchmatrix's positioning

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
