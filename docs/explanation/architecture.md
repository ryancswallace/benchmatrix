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
* `bench_collection.py` runs sequential repeated collections and owns their
    strict, manifest-backed lifecycle.
* `bench_results.py` parses and displays saved benchmark results.
* `bench_compare.py` checks all repeated-run environments, aligns complete
    benchmark matrices, reports evidence quality, and applies regression
    policies.
* `bench_policy.py` translates strict `tool.benchmatrix` TOML into the same
    compatibility, evidence, and regression objects used by the Python API.
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
evidence analysis checks repeated-run coverage and raw sample sufficiency.
Regression classification happens only after all gates permit it. Repeated
effects must also agree beyond the policy threshold before a change is
conclusive.

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

Policy configuration is an adapter, not a second decision engine. CLI overrides
replace individual configured scalar values, while selector mappings and the
comparison engine's precedence rules remain owned by `RegressionPolicy`.

Comparison reports are portable decision records, not instructions to rerun an
analysis. Loading a report reconstructs its typed policy, evidence, environment
findings, matrix cells, and collection snapshots without reopening the original
benchmark files. The loader rejects unknown schema versions, unknown fields,
and inconsistent derived summaries so consumers never silently reinterpret a
newer contract as version 1.

JSON comparison reports remain the canonical machine contract. Text, Markdown,
and GitHub Actions step summaries are renderings of the same
`BenchmarkComparisonReport`; they do not recompute policy or regression
decisions. Policy inspection likewise resolves the same `BenchmarkPolicyConfig`
used by comparison, allowing CI validation without creating a parallel parser.

## Extension point

The stable extension point is the public API exported by `benchmatrix`. Private
module structure can change when implementation details are simplified.
