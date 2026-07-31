# Parse benchmark results

Use `load_benchmark_run` when the file represents a complete saved run. The
returned `BenchmarkRun` keeps both the matrix rows and top-level
pytest-benchmark metadata such as machine and commit information.

```python
from benchmatrix import load_benchmark_run

run = load_benchmark_run("benchmark.json")

print(run.implementations)
print(run.cases)
print(run.metrics)
print(run.metadata.get("machine_info"))
```

Use `load_benchmark_json` when existing code needs only a list of parsed rows:

```python
from benchmatrix import load_benchmark_json

rows = load_benchmark_json("benchmark.json")
```

Display a concise table:

```python
from benchmatrix import display_benchmark_rows

display_benchmark_rows(rows)
```

## Measure repeated runs

Use `measure` to run pytest sequentially and retain the complete collection
lifecycle:

```bash
benchmatrix measure --runs 5 --output candidate-runs \
    tests/test_benchmarks.py
```

`--runs` is the successful-run target. benchmatrix initially makes that many
attempts, runs pytest through the current Python interpreter, and assigns a
unique `--benchmark-json` path to each invocation. It suppresses pytest's
configured `addopts`, the `PYTEST_ADDOPTS` environment variable, and the normal
pytest-benchmark table so coverage or parallel-test settings do not affect the
measurement. Pass `--inherit-pytest-addopts` when those settings are required.
The output directory must be new or empty for a new collection so an existing
result cannot be overwritten accidentally.

Put advanced pytest arguments after `--`:

```bash
benchmatrix measure --runs 5 --output candidate-runs \
    tests/test_benchmarks.py -- -k small --benchmark-min-rounds=20
```

benchmatrix owns `--benchmark-json` and rejects options that disable benchmark
measurement.

Each collection contains numbered `run-001.json` files and an atomically
updated `benchmatrix-manifest.json`. The manifest records:

* the original command, working directory, creation time, and successful-run
    target;
* the expected implementation, case, and metric cells;
* the source commit and a SHA-256 environment fingerprint;
* every attempt's return code, duration, file, validation status, warnings, and
    failure reason.

Initial collection continues after a command or validation failure. A run becomes
evidence only if its command succeeds, its JSON parses, its matrix matches the
first successful run, its commit is unchanged, and its environment has no
blocking compatibility differences. Warning-level environment changes remain
visible in the manifest. `measure` exits `1` while the successful-run target is
not met and `2` if collection could not be initialized or resumed.

Resume a process that stopped before all initial attempts were recorded:

```bash
benchmatrix measure --resume --output candidate-runs
```

The saved managed pytest command and original working directory are reused. The
targets and pytest arguments may be repeated, but they must resolve to the exact
manifest command. Supplying `--runs` while resuming is also optional; when
supplied, it must equal the saved target. Successful files and recorded failures
are revalidated before another command runs.

Retry failed or rejected attempts:

```bash
benchmatrix measure --retry-failed --output candidate-runs
```

`--retry-failed` implies `--resume`. It first fills any initial attempts that
were never recorded, then appends one attempt for each successful run still
needed. A retry never replaces a failure record or its file. If a process left
an unrecorded partial JSON file, that file is preserved and the resumed attempt
uses a collision-free name. Each retry invocation is bounded; run the command
again if a retry also fails.

Use `collect` instead when pytest must be launched by another environment
manager, container, or custom command:

```bash
benchmatrix collect --runs 5 --output candidate-runs -- \
    custom-runner pytest tests/test_benchmarks.py
```

Load the collection in Python:

```python
from benchmatrix import load_benchmark_run_group

group = load_benchmark_run_group("candidate-runs")

print(group.successful_count, group.failed_count, group.is_complete)
print(group.pending_count, group.retry_count, group.remaining_count)
for failure in group.failed_records:
    print(failure.index, failure.error)
```

The loader accepts either the collection directory or its manifest path and
revalidates successful files against their recorded cells, commit, and
environment fingerprint. Version 1 manifests remain loadable. New collections
use manifest version 2, which permits appended retry attempts while retaining
the original successful-run target.

Resume through Python with the same collector:

```python
from benchmatrix import collect_benchmark_runs

group = collect_benchmark_runs(
    (),
    "candidate-runs",
    resume=True,
    retry_failed=True,
)
```

## Compare from the command line

Compare collection directories for a trust-aware local review or CI decision:

```bash
benchmatrix compare baseline-runs candidate-runs
```

Manifest paths and individual repeated files are also accepted:

```bash
benchmatrix compare baseline-1.json candidate-1.json \
    --baseline-run baseline-2.json \
    --candidate-run candidate-2.json
```

Apply a regression threshold and turn the result into a CI gate:

```bash
benchmatrix compare baseline-1.json candidate-1.json \
    --baseline-run baseline-2.json \
    --candidate-run candidate-2.json \
    --threshold 5% \
    --fail-on-regression
```

The first positional source is the primary run or collection for each side.
Repeat `--baseline-run` and `--candidate-run` for additional files or
collections. The command requires two successful runs per side and five raw
timing samples per file and cell by default. An incomplete collection makes an
opt-in `--fail-on-regression` gate fail even if its remaining evidence would
otherwise pass. Relax the evidence gates explicitly for exploratory
comparisons:

```bash
benchmatrix compare baseline.json candidate.json \
    --minimum-runs 1 \
    --minimum-samples 1
```

The command uses permissive run compatibility by default. Select another mode
explicitly when needed:

```bash
benchmatrix compare baseline-1.json candidate-1.json \
    --baseline-run baseline-2.json \
    --candidate-run candidate-2.json \
    --compatibility strict \
    --fail-on-regression
```

Use JSON output for downstream automation:

```bash
benchmatrix compare baseline-1.json candidate-1.json \
    --baseline-run baseline-2.json \
    --candidate-run candidate-2.json \
    --format json > comparison.json
```

The output is a first-class comparison report rather than an ad hoc CLI
payload. It includes `producer`, `kind`, and `schema_version` identifiers,
resolved baseline and candidate sources, effective policies, configuration and
threshold provenance, compatibility findings, repeated-run evidence, matrix
cell decisions, and collection lifecycle snapshots.

Load the report later without reopening the benchmark inputs:

```python
from benchmatrix import load_comparison_report

report = load_comparison_report("comparison.json")

print(report.schema_version, report.passed)
for cell in report.regressed:
    print(cell.implementation_name, cell.case_name, cell.metric_name)
```

Create and persist the same portable document from a comparison in Python:

```python
from benchmatrix import (
    BenchmarkComparisonReport,
    BenchmarkPolicyProvenance,
    BenchmarkThresholdProvenance,
    write_comparison_report,
)

report = BenchmarkComparisonReport.from_comparison(
    comparison,
    baselines=("baseline.json",),
    candidates=("candidate.json",),
    policy_provenance=BenchmarkPolicyProvenance(selection="defaults"),
    threshold_provenance=tuple(
        BenchmarkThresholdProvenance(
            scope=comparison.regression_policy.threshold_scope_for(
                cell.implementation_name,
                cell.case_name,
                cell.metric_name,
            ),
            origin="built_in",
            field="regression.default_threshold_percent",
        )
        for cell in comparison.comparisons
    ),
)
write_comparison_report(report, "comparison.json")
```

The example uses only the built-in default threshold. When selector policies
apply, supply their exact scope, origin, and field for each cell. The report
constructor verifies this provenance against the effective regression policy.

Version 1 is strict: unknown or missing fields, non-finite numbers, changed
derived summaries, and unsupported producer, kind, or schema identifiers raise
`BenchmarkJsonError`. Consumers should branch on `schema_version` rather than
assuming future versions have the same shape.

## Publish Markdown and CI summaries

Render the same typed comparison report as GitHub-flavored Markdown:

```bash
benchmatrix compare baseline-runs candidate-runs \
    --format markdown > comparison.md
```

The report includes the overall and comparison decisions, source and collection
lifecycle details, result counts, every matrix cell, effective thresholds and
their provenance, environment findings, repeated-run evidence diagnostics, and
the effective policy.

Render or write Markdown through Python:

```python
from benchmatrix import (
    format_comparison_report_markdown,
    load_comparison_report,
    write_comparison_report_markdown,
)

report = load_comparison_report("comparison.json")
print(format_comparison_report_markdown(report))
write_comparison_report_markdown(report, "comparison.md")
```

In GitHub Actions, append Markdown directly to the job's step summary:

```yaml
- name: Compare benchmark runs
  run: |
    benchmatrix compare baseline-runs candidate-runs \
      --github-summary \
      --fail-on-regression
```

`--github-summary` uses the `GITHUB_STEP_SUMMARY` path supplied by GitHub
Actions. It can be combined with any stdout format, so automation may retain
canonical JSON while publishing Markdown:

```bash
benchmatrix compare baseline-runs candidate-runs \
    --format json \
    --github-summary > comparison.json
```

The summary is appended rather than replacing content from earlier commands.
Outside GitHub Actions, requesting it without `GITHUB_STEP_SUMMARY` exits `2`
with a diagnostic.

Comparison policy can be committed in `pyproject.toml` instead of repeated in
every invocation. See
[Configuration and automation](../reference/configuration.md#benchmark-comparison-policy)
for the schema, discovery rules, CLI precedence, and exact-cell examples.

The command has these exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Comparison completed, or the policy passed when gating was requested. |
| `1` | `--fail-on-regression` was requested and the result regressed, was inconclusive, was incomplete, or was not comparable. |
| `2` | Arguments or benchmark input were invalid. |

Without `--fail-on-regression`, a completed comparison exits `0` even when its
reported overall result is `FAIL`. This makes exploratory use convenient while
keeping CI gating explicit. The equivalent module entry point is
`python -m benchmatrix`.

## Inspect trust diagnostics

Text and JSON output report evidence separately for each side of every matrix
cell:

* files provided and files containing the cell;
* rounds and iterations reported by every file;
* per-file and total raw timing sample counts;
* pooled sample IQR and coefficient of variation (CV);
* pooled Tukey outliers and outlier fraction;
* environment compatibility across all files;
* concrete reasons evidence is inadequate.

IQR, CV, and outliers describe raw elapsed-time samples in seconds. They expose
noise and skew; they are not regression percentages. Configure optional
`EvidencePolicy.maximum_cv` or `maximum_outlier_fraction` limits when those
quality diagnostics should block a decision.

For repeated inputs, benchmatrix compares the median per-run metric value on
each side. An improvement or regression is conclusive only when every
baseline/candidate pairing crosses the configured threshold in the same
direction. Conflicting pairwise effects are `inconclusive`, even when the two
medians differ by more than the threshold.

Use the repeated-run API directly when working in Python:

```python
from benchmatrix import compare_benchmark_run_groups, load_benchmark_run

baselines = (
    load_benchmark_run("baseline-1.json"),
    load_benchmark_run("baseline-2.json"),
)
candidates = (
    load_benchmark_run("candidate-1.json"),
    load_benchmark_run("candidate-2.json"),
)

comparison = compare_benchmark_run_groups(baselines, candidates)

for cell in comparison.comparisons:
    print(
        cell.regression,
        cell.baseline_evidence,
        cell.candidate_evidence,
        cell.improvement_low_percent,
        cell.improvement_high_percent,
    )
```

Manifest-backed groups provide a convenience method over the same engine:

```python
from benchmatrix import load_benchmark_run_group

baseline = load_benchmark_run_group("baseline-runs")
candidate = load_benchmark_run_group("candidate-runs")
comparison = baseline.compare_to(candidate)
```

## Compare two matrix runs

Load a controlled baseline and candidate, then compare them across the union of
their matrix cells:

```python
from benchmatrix import load_benchmark_run

baseline = load_benchmark_run("baseline.json")
candidate = load_benchmark_run("candidate.json")
comparison = baseline.compare_to(candidate)

for cell in comparison.comparisons:
    print(
        cell.implementation_name,
        cell.case_name,
        cell.metric_name,
        cell.status,
        cell.regression,
        cell.improvement_percent,
    )
```

Each matrix cell is identified by implementation, case, and metric. The engine
uses these primary statistics:

| Metric | Statistic | Better direction |
| --- | --- | --- |
| `single_call_latency` | mean latency | lower |
| `batch_throughput` | mean throughput | higher |
| `tail_latency` | p95 latency | lower |

`ratio` and `percent_change` express the candidate relative to the baseline.
`improvement_percent` adjusts for metric direction, so a positive value always
means the candidate improved.

The comparison does not silently discard matrix differences:

* `matched` cells contain comparable values;
* `missing_baseline` and `missing_candidate` identify incomplete matrices;
* `incompatible` identifies changed case metadata, changed throughput units, or
    invalid derived values.

Treat incompatible results as a request to fix the benchmark inputs or
environment, not as a performance change.

## Check run compatibility

Comparisons inspect pytest-benchmark's top-level environment metadata before
classifying regressions. The default permissive policy blocks material changes
to the OS, architecture, Python implementation or major/minor version, CPU
word size, and CPU identity. It reports lower-risk differences such as Python
patch version, compiler, OS release, CPU count or flags, pytest-benchmark
version, and supplied dependency metadata as warnings.

```python
comparison = baseline.compare_to(candidate)

for finding in comparison.compatibility.blocking:
    print("BLOCKING", finding.field, finding.reason)

for finding in comparison.compatibility.warnings:
    print("WARNING", finding.field, finding.reason)
```

Choose strict mode when missing metadata and every tracked difference should
block comparison:

```python
from benchmatrix import RunCompatibilityPolicy

comparison = baseline.compare_to(
    candidate,
    compatibility_policy=RunCompatibilityPolicy(mode="strict"),
)
```

Strict mode requires the tracked pytest-benchmark environment fields. Optional
top-level `dependencies` metadata is compared when present but is not required.
Use `mode="off"` only when environment compatibility is enforced elsewhere.
Cells remain aligned when the environment is blocked, but their regression
classification is `not_comparable`.

## Classify regressions

The default regression threshold is 5%. A change must exceed the threshold to
be classified as `improved` or `regressed`; changes on the boundary are
`unchanged`. Thresholds use the direction-aware `improvement_percent`, so the
same policy works for lower-is-better latency and higher-is-better throughput.

```python
from benchmatrix import RegressionPolicy

policy = RegressionPolicy(
    default_threshold_percent=5.0,
    by_metric={"tail_latency": 8.0},
    by_implementation={"reference": 3.0},
    by_case={"large": 10.0},
    by_cell={
        ("reference", "large", "tail_latency"): 12.0,
    },
)

comparison = baseline.compare_to(candidate, regression_policy=policy)

if not comparison.passed:
    for cell in comparison.regressed:
        print(cell.implementation_name, cell.case_name, cell.metric_name)
```

Threshold precedence is exact cell, case, implementation, metric, then the
default. The aggregate `passed` property is true only when:

* the run environments are compatible;
* every matrix cell is present and compatible;
* every matrix cell has adequate and internally consistent evidence;
* no cell exceeds its regression threshold.

## Handle invalid or mixed files

pytest-benchmark JSON may contain rows that were not generated by benchmatrix.
The parser requires every row in a loaded run to carry valid benchmatrix
metadata, so unrelated benchmark data does not silently acquire benchmatrix
semantics.

If parsing fails, treat the exception as a contract problem with the input file:

* confirm the file came from pytest-benchmark JSON export;
* confirm the benchmark was generated by benchmatrix;
* check that matrix identifiers are non-empty and each matrix cell is unique;
* keep timing fields as finite JSON numbers rather than strings or booleans;
* preserve the original JSON as a fixture when adding parser tests.

## Use result fixtures in tests

Representative JSON fixtures belong under `tests/fixtures/benchmark_results/`.
Prefer fixtures when the JSON shape matters more than a small inline dictionary.
