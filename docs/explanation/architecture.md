# Architecture

benchmatrix has four main responsibilities:

1. generate pytest benchmark matrices from implementations, cases, and metrics;
2. parse pytest-benchmark JSON rows that carry benchmatrix metadata;
3. collect repeated runs with durable provenance and failure records;
4. compare complete runs without losing missing or incompatible matrix cells.

pytest-benchmark remains responsible for measurement. benchmatrix does not
replace its calibration, timing, statistics, terminal reporting, or JSON export.

## Package boundaries

* `bench_harness.py` builds benchmark tests and invocation metadata.
* `bench_collection.py` runs independent and paired repeated collections and
    owns their strict, manifest-backed lifecycle contracts.
* `_collection_design.py` derives seeded Williams-style matrix-cell schedules;
    the harness consumes a collector-provided schedule row without exposing
    private collection state in benchmark metadata.
* `bench_results.py` parses and displays saved benchmark results.
* `bench_compare.py` checks all repeated-run environments, aligns complete
    benchmark matrices, reports evidence quality, and applies inference and
    regression policies.
* `bench_statistics.py` implements deterministic independent and paired
    run-level bootstrap intervals plus fixed-design paired precision planning,
    without adding a numerical runtime dependency.
* `bench_policy.py` translates strict `tool.benchmatrix` TOML into the same
    compatibility, evidence, inference, precision, and regression objects used
    by the Python API.
* `bench_report.py` snapshots comparison decisions, policy and threshold
    provenance, evidence diagnostics, sources, and collection lifecycle state
    in a strict, versioned JSON document.
* `cli.py` exposes managed pytest measurement, generic collection, and
    comparison through a dependency-free command-line interface with text and
    JSON output.
* `exceptions.py` contains package-specific exceptions.
* `_schema.py` is a private schema constant module shared by implementation
    code.
* `__init__.py` defines the public package exports.

## Design constraints

Metadata must stay strict-JSON-safe because it is serialized through
pytest-benchmark output. Benchmark targets are synchronous only so the measured
unit is one completed target call.

Comparison has three separate trust gates. Run compatibility checks whether all
environments are comparable; matrix compatibility checks whether individual
implementation, case, and metric cells have matching measurement context; and
evidence analysis checks independent-run coverage and nested round-observation
sufficiency. Regression classification happens only after all gates permit it.

One separately launched pytest process is the independent unit of inference.
The statistic for a process is mean latency, mean throughput, or p95 latency,
depending on the metric. Raw pytest-benchmark rounds stay nested within their
process: they calculate the process statistic and support within-run quality
diagnostics, but they do not increase the independent replicate count.

The formal estimand is the direction-aware percentage ratio between the median
per-run statistic on each side. For independent groups,
`bench_statistics.py` resamples complete baseline and candidate run statistics
separately. For an explicitly paired design, it resamples matched
baseline/candidate tuples and deletes complete pairs for the BCa jackknife.
Both designs recalculate the same estimand and form a deterministic BCa
bootstrap interval. A degenerate BCa acceleration is handled by an explicit
percentile-bootstrap fallback, not by changing the estimand or pooling raw
rounds.

The comparison engine defines a multiplicity family before classification. It
contains every environment-compatible matrix cell with matching measurement
context and finite positive run statistics on both sides; missing and
structurally incompatible cells are excluded. Evidence adequacy and the
eventual outcome do not shrink the family. Bonferroni adjustment raises each
cell's interval confidence to `1 - (1 - family confidence) / family size`,
providing conservative family-wise coverage across the matrix.

Classification combines statistical uncertainty with a practical threshold.
An interval entirely below the negative threshold is a regression, an interval
entirely above the positive threshold is an improvement, and an interval wholly
inside those boundaries is practical equivalence (`unchanged`). Every interval
crossing a boundary is `inconclusive`. This prevents failure to establish a
regression from being mislabeled as evidence of no meaningful change.

Collection and analysis remain separate. The collector accepts only successful,
schema-valid, matrix-stable, commit-stable, environment-compatible files as
evidence. Its manifest still records rejected attempts so missing evidence has
an auditable cause. The comparison engine consumes the accepted
`BenchmarkRun` values and treats collection completeness as an additional CLI
gate.

Managed measurement is a CLI adapter, not a second collector. It constructs an
isolated pytest command and passes it to the same collection lifecycle used by
custom commands, so retry, resume, validation, and manifest behavior cannot
diverge.

Collection completeness is a successful-run target, not an attempt limit.
Resuming fills initial attempt slots missing after an interruption. Retrying
appends a bounded set of attempts and never rewrites prior records, so transient
and persistent failures remain distinguishable. Every resume reloads and
revalidates the manifest, successful files, command, target, and original
working directory before execution.

Paired collection has a stricter atomic-block lifecycle. A scheduled pair is an
adjacent AB or BA two-command attempt, and only two successes from that same
attempt enter `complete_pairs`. Orphan successes remain in the manifest and
loaded `runs` for audit, but are absent from the paired baseline and candidate
views. Resume replaces a partially persisted block with a fresh block; retry
does the same for another incomplete pair. The schedule alternates AB/BA
orientation and gives both members the same seeded balanced matrix-order row.
Across its joint supercycle, every order row occurs under both orientations.
Automatic target sizing begins after the first accepted command reveals the
matrix. Pair identity, command order, cell order, target basis, and every retry
survive serialization and revalidation.

Policy configuration is an adapter, not a second decision engine. CLI overrides
replace individual configured scalar values, while selector mappings and the
comparison engine's precedence rules remain owned by `RegressionPolicy`.

Comparison reports are portable decision records, not instructions to rerun an
analysis. Schema version 2 introduced the estimand, confidence bounds, nominal
and adjusted confidence levels, multiplicity family, resample count, derived
cell seed, and effective interval method. The current schema version 3 adds the
comparison design, pair counts, paired collection provenance, precision policy,
and per-cell precision plans. The loader strictly accepts report schema
versions 1, 2, and 3; version 1 remains identified as legacy and
non-inferential when upgraded to the current typed model.

JSON comparison reports remain the canonical machine contract. Text, Markdown,
and GitHub Actions step summaries are renderings of the same
`BenchmarkComparisonReport`; they do not recompute policy or regression
decisions. Policy inspection likewise resolves the same `BenchmarkPolicyConfig`
used by comparison, allowing CI validation without creating a parallel parser.

## Extension point

The stable extension point is the public API exported by `benchmatrix`. Private
module structure can change when implementation details are simplified.

## Experimental-design boundary

Paired design is explicit in `BenchmarkPairedRunGroup` and
`compare_paired_benchmark_run_groups`; ordinary run groups remain independent.
The comparison engine never constructs pairs from filenames, timestamps, or
sequence proximity. This keeps independent historical collections from
silently acquiring a stronger dependence assumption.

Manifest-backed paired inference carries recorded AB/BA orientation into a
stratified pair bootstrap, preserving each fixed orientation count. A low-level
paired call may omit strata only with an explicit exchangeability warning.

`PrecisionPolicy` may attach a within-stratum paired log-ratio Student-t
planning proxy to each cell. The proxy models the multiplicative width of a
mean signed paired log ratio, not the ratio-of-marginal-medians estimand used by
paired BCa inference; it does not guarantee a future BCa interval width. The
resulting `required_pairs` respects the evidence minimum and complete design
multiple and describes a fresh future fixed-size collection. It is not
statistical power, a guarantee of a conclusive decision, or a sequential rule.
The reported arithmetic difference from the pilot is not authorization to
append data to an analyzed pilot and then treat the combination as a
confirmatory experiment specified in advance.

The CLI preserves the same boundary. `collect` and `measure` create independent
groups, while `collect-paired` records explicit AB/BA blocks and
`compare --paired` consumes only their complete matched pairs. Paired loading,
retry, comparison, and precision planning are also available through the
Python API.
