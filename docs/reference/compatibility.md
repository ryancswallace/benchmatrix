# Compatibility

This page defines the support surface for benchmatrix. It should agree with
`pyproject.toml`, CI, nox, release notes, and the security policy.

## Supported Python versions

benchmatrix supports CPython 3.11 through 3.14. The package metadata declares:

```toml
requires-python = ">=3.11,<3.15"
```

The local nox matrix runs tests on every supported Python version:

```bash
make test-matrix
```

Normal pull request CI verifies every supported Python version on Ubuntu and
runs the test suite on macOS and Windows for the current default Python version.
The primary quality job uses the repository `.python-version`.
Run `make test-matrix` locally before changes that may affect Python-version
compatibility.

## Supported operating systems

The package is intended to be OS-independent Python code and is classified as
`Operating System :: OS Independent`.

Supported operating systems are:

* Linux;
* macOS;
* Windows.

Pull request CI runs the full supported-Python test matrix on Ubuntu and the
current-Python test suite on macOS and Windows. Linux is the primary continuously
verified platform. macOS and Windows are supported by design because benchmatrix
does not rely on platform-specific APIs, but regressions that only appear on
those systems may require a maintainer or contributor with access to the
affected platform to confirm and validate the fix.

## Supported architectures

benchmatrix is pure Python and does not ship compiled extensions. No
architecture-specific behavior is part of the public contract.

Supported architectures are any architecture where a supported CPython version
and the runtime dependencies can be installed, including common `x86_64` and
`aarch64` environments. Architecture-specific issues in pytest, pytest-benchmark,
or optional development tools are handled according to impact and reproducibility.

## Stable compatibility surfaces

The 1.x compatibility contract covers:

* names exported from the `benchmatrix` package root;
* documented constructors, call signatures, fields, properties, return values,
    accepted literal values, and exception hierarchies for those names;
* CLI commands, arguments, option meanings, defaults, output routing, and exit
    status meanings;
* the `[tool.benchmatrix]` configuration schema, discovery and precedence
    rules, and built-in policy defaults;
* benchmatrix metadata embedded in pytest-benchmark JSON, run-group manifests,
    comparison reports, and policy-inspection JSON.

Human-readable wording, whitespace, table layout, object representations,
exception message text, private modules, and private names are not stable
machine interfaces.

The compatibility rules are:

| Release | Allowed compatibility changes |
| --- | --- |
| Patch | Correct behavior within the documented contract, improve diagnostics, and reject input that was already invalid. |
| Minor | Add optional API, CLI, configuration, or document-schema capability while retaining every earlier 1.x contract. |
| Major | Remove, rename, reinterpret, or make incompatible changes to a stable surface. |

Urgent security or correctness fixes may require a narrower exception. Such an
exception must be prominent in the changelog and release notes.

## Public API stability

The stable public API is the set of names exported from `benchmatrix.__init__`
and documented in the generated API reference. Private modules and private names
are not stable extension points, including:

* modules whose names begin with `_`, such as `_schema.py`;
* functions, classes, constants, and attributes whose names begin with `_`;
* incidental implementation details not documented in user-facing docs.

Import stable names from the package root, for example
`from benchmatrix import BenchmarkRun`. Low-level manifest constants, tuple
aliases, and string-literal aliases are intentionally not re-exported from the
package root. Their concrete values may appear in public record fields and
serialized documents without making the aliases themselves stable import
locations.

Patch releases preserve documented public behavior except for urgent security
or correctness fixes. Minor releases add backward-compatible behavior and may
introduce deprecations. Incompatible changes to the stable public API require a
major release.

For exported functions and methods, parameter names, positional versus
keyword-only behavior, defaults, and return-value meaning are stable. A minor
release may add an optional keyword-only parameter. Removing or renaming a
parameter, adding a required argument, changing a default incompatibly, or
changing the meaning of a return value requires a major release.

For exported record and policy classes, documented constructor fields, field
order, properties, accepted values, and value semantics are stable. A minor
release may add a property or an optional field with a backward-compatible
default. Code should use named attributes rather than depend on object
representations, hash values, or implementation details of frozen and slotted
data classes.

`InferencePolicy` is the public configuration record for run-level uncertainty,
and `BenchmarkInference` is the per-cell result record. `BenchmarkComparison`
retains the earlier observed pairwise range fields and adds optional
`inference` and paired `precision` records; `BenchmarkRunComparison` retains its
earlier policy fields and identifies the independent or paired design plus the
effective inference and precision policies. Formal confidence bounds are
available only through the inference record.

`BenchmarkPairedRunGroup`, `BenchmarkRunPair`, and the paired record and
schedule classes expose the manifest-backed AB/BA lifecycle. Use
`collect_paired_benchmark_runs` and `load_paired_benchmark_run_group` to create
or restore it; use its complete-pair views or
`compare_paired_benchmark_run_groups` for paired inference. Pairing is explicit
and positional in the comparison function; optional fixed stratum labels carry
AB/BA orientation into design-preserving resampling. `PrecisionPolicy`,
`PrecisionPlan`, and `plan_paired_precision` describe the optional fresh-design
planning contract, including evidence-minimum and pair-count-multiple
constraints; they do not define power or sequential stopping.

Documented literal values such as metric names, compatibility modes, comparison
statuses, regression classifications, and severity values retain their meaning
throughout 1.x. Minor releases may add a value to an open set; callers should
handle an unfamiliar value explicitly rather than assume exhaustive matching.

| Value domain | Values defined by 1.x |
| --- | --- |
| Metrics | `single_call_latency`, `batch_throughput`, `tail_latency` |
| Collection status | `succeeded`, `failed` |
| Paired variant | `baseline`, `candidate` |
| Paired order | `AB`, `BA` |
| Compatibility mode | `strict`, `permissive`, `off` |
| Compatibility severity | `blocking`, `warning` |
| Comparison direction | `lower_is_better`, `higher_is_better` |
| Comparison design | `independent`, `paired` |
| Comparison status | `matched`, `missing_baseline`, `missing_candidate`, `incompatible` |
| Regression classification | `improved`, `unchanged`, `regressed`, `inconclusive`, `not_comparable` |
| Threshold scope | `cell`, `case`, `implementation`, `metric`, `default` |
| Inference method | `bca_bootstrap`, `legacy_consistency` |
| Effective interval method | `bca_bootstrap`, `percentile_bootstrap` |
| Multiplicity correction | `bonferroni`, `none` |
| Precision method | `paired_log_ratio_t` |
| Policy selection | `defaults`, `disabled`, `discovered`, `explicit` |
| Threshold origin | `built_in`, `configuration`, `cli` |

All package-specific exceptions inherit from `BenchmatrixError`. JSON and policy
validation exceptions also remain `ValueError` subclasses, while collection
execution failures remain `RuntimeError` subclasses. Exception classes and base
relationships are stable; exact message wording is not.

## CLI compatibility

`benchmatrix` and `python -m benchmatrix` are equivalent entry points. The root
command supports `--version`. These commands and options are stable in 1.x:

| Command | Arguments and options |
| --- | --- |
| `collect` | `--runs`, required `--output`, `--resume`, `--retry-failed`, `--format` with `text` or `json`, and the pytest command after `--` |
| `collect-paired` | `--pairs`, required `--output`, `--random-seed`, `--baseline-cwd`, `--candidate-cwd`, `--resume`, `--retry-failed`, `--format` with `text` or `json`, and baseline/candidate commands after `--` separated by `:::` |
| `measure` | one or more pytest targets, the collection options, `--inherit-pytest-addopts`, and optional pytest arguments after `--` |
| `compare` | baseline and candidate sources for an independent design, or one paired collection source with `--paired`; repeatable `--baseline-run` and `--candidate-run`, `--threshold`, `--compatibility` with `strict`, `permissive`, or `off`; `--format` with `text`, `json`, or `markdown`; text-only `--summary`; `--github-summary`, `--fail-on-regression`, `--minimum-runs`, `--minimum-samples`, `--inference-method`, `--confidence-level`, `--bootstrap-resamples`, `--random-seed`, `--multiplicity`, `--precision-target`, and mutually exclusive `--config` or `--no-config` |
| `policy show` | mutually exclusive `--config` or `--no-config`, `--search-from`, and `--format` with `text` or `json` |
| `policy validate` | the `policy show` options plus `--quiet` |

Independent measurement and collection default to five successful runs for a
new group and text output. Paired collection without an explicit target learns
the matrix and selects the smallest complete AB/BA-by-order-row supercycle with
at least five pairs. Measurement invokes pytest through the running Python
interpreter, uses quiet pytest and benchmark output, and ignores configured
pytest `addopts` unless `--inherit-pytest-addopts` is supplied.
Comparison defaults to text output and does not fail the process for a reported
regression unless `--fail-on-regression` is present. Policy commands default to
text output and normal configuration discovery. Adding an optional command or
option is allowed in a minor release; removing or renaming one, changing an
existing option's meaning or default incompatibly, or repurposing an exit code
requires a major release.

Comparison uses deterministic run-level BCa intervals, 95% family confidence,
50,000 resamples, seed zero, and Bonferroni multiplicity by default. A single
run cannot produce that interval and is `inconclusive`, even when
`--minimum-runs 1` relaxes the evidence count.
`--inference-method legacy_consistency` selects the earlier non-inferential
rule explicitly.
`--multiplicity none` is an exploratory per-cell analysis without matrix-wide
error control.

Successful text, JSON, and Markdown content is written to standard output.
Diagnostics and usage errors are written to standard error. JSON modes do not
mix progress or diagnostic prose into standard output. `--github-summary`
appends Markdown to `GITHUB_STEP_SUMMARY` and does not replace the selected
standard-output format.

| Command outcome | Exit status |
| --- | --- |
| Successful operation or passing requested gate | `0` |
| Incomplete collection, or a requested comparison gate that regressed, was inconclusive, was incomplete, or was not comparable | `1` |
| Invalid arguments, configuration, environment, or input data | `2` |

Without `--fail-on-regression`, a completed comparison exits `0` even when the
report's `passed` field is false. Human-readable text and Markdown layout may
improve within 1.x and must not be parsed as a machine protocol. Comparison JSON
and policy JSON use the versioned schemas below. `measure --format json` and
`collect --format json` share a stable 1.x summary whose existing keys and
meanings will not be removed or changed; the manifest is the canonical archival
record.

## Configuration compatibility

The `[tool.benchmatrix]` schema is strict. Unknown keys are errors so spelling
mistakes cannot silently weaken a gate.

| Table | Stable keys |
| --- | --- |
| `compatibility` | `mode` (`strict`, `permissive`, or `off`; default `permissive`) |
| `evidence` | `minimum_runs` (`5`), `minimum_samples_per_run` (`5`), `minimum_rounds_per_run` (`5`), `require_rounds` (`true`), `require_iterations` (`true`), `require_raw_samples_for_inference` (`true`), `minimum_tail_samples_per_run` (`100`), `require_tail_iterations_one` (`true`), `maximum_cv` (unset), `maximum_outlier_fraction` (unset) |
| `inference` | `method` (`bca_bootstrap`), `confidence_level` (`0.95`), `resamples` (`50000`), `random_seed` (`0`), `multiplicity` (`bonferroni`) |
| `precision` | `target_half_width_percent` (unset by default; paired design only) |
| `regression` | `default_threshold_percent` (`5.0`), `by_metric`, `by_implementation`, `by_case`, and `by_cell` |
| Each `by_cell` entry | `implementation`, `case`, `metric`, and `threshold_percent` |

Metric selectors are `single_call_latency`, `batch_throughput`, and
`tail_latency`. Implementation and case selectors are non-empty strings.
Thresholds are finite, non-negative percentages.

Policy selection and precedence are stable:

1. `--no-config` disables discovery; `--config` selects an explicit file;
   otherwise the nearest `pyproject.toml` is selected.
2. Discovery stops at the nearest project file even if it has no
   `[tool.benchmatrix]` table.
3. CLI scalar overrides replace only their corresponding configured scalar and
   retain all selector mappings.
4. Regression thresholds resolve from exact cell, case, implementation, metric,
   then the default.
5. Values not configured come from the built-in defaults in the table above.

The stronger evidence defaults and interval-based decision rule are a
statistical-correctness exception to the usual 1.x decision-default stability.
They prevent two-run or single-run evidence from being presented as a
calibrated statistical conclusion. Use `method = "legacy_consistency"` only for
an explicit, non-inferential migration comparison.

Adding an optional configuration key is allowed in a minor release. Removing or
renaming a key, changing its type or meaning, changing selector precedence, or
changing a built-in decision default incompatibly requires a major release.

## Serialized document compatibility

Every canonical JSON document identifies its benchmatrix producer and schema
version. Documents with a `kind` field must also be dispatched by kind:

| Document | Current writer identity | Versions read by 1.x |
| --- | --- | --- |
| Benchmark-row `extra_info` | `benchmatrix_producer = "benchmatrix"`, `benchmatrix_schema_version = 1` | `1` |
| Run-group manifest | `producer = "benchmatrix"`, `kind = "benchmark_run_group"`, `schema_version = 2` | `1`, `2` |
| Paired run-group manifest | `producer = "benchmatrix"`, `kind = "benchmark_paired_run_group"`, `schema_version = 1` | `1` |
| Comparison report | `producer = "benchmatrix"`, `kind = "benchmark_comparison"`, `schema_version = 3` | `1`, `2`, `3` |
| Policy inspection or validation | `producer = "benchmatrix"`, `kind = "benchmark_policy"`, `schema_version = 3` | Consumer-dispatched; benchmatrix does not load this document |

The pytest-benchmark top-level JSON envelope belongs to pytest-benchmark.
benchmatrix stabilizes its own `extra_info` keys and validates the upstream
statistics and metadata needed to interpret them. Additional user metadata may
coexist in `extra_info`.

New run-group manifests use schema version 2. The loader continues to accept
schema version 1 manifests produced before resumable collection was added.
Version 2 preserves the same core fields but permits attempt records beyond the
successful-run target so failed retries remain auditable. Version 1 manifests
cannot contain those appended retry records.

Paired manifests have their own schema version 1 and document kind. They record
both commands and working directories, the deterministic seed, whether the
pair target was automatic, the resolved target, variant-specific commit and
environment anchors, the crossed AB/BA and matrix-order schedule, block-attempt
identity, and every command outcome. A complete inference pair consists only of
two successes from one atomic block; the loader retains but never stitches
orphan successes.

Comparison report schema version 2 added the effective inference policy,
per-cell estimand and confidence bounds, nominal and adjusted confidence
levels, family size, multiplicity method, resample count, deterministic seed,
fallback method, warnings, and issues. The current schema version 3 adds the
comparison design, paired collection snapshots, per-cell pair and resampling-
stratum counts, the effective precision policy, constrained and unconstrained
precision pair counts, and their minimum/multiple provenance. The existing
`improvement_low_percent` and `improvement_high_percent` fields remain a
descriptive observed effect range; they are not confidence bounds.

Report loading is strict for versions 1, 2, and 3: unsupported versions and
unknown, missing, or inconsistent fields raise `BenchmarkJsonError`. A version
1 report retains its historical classification and is loaded as an explicit
legacy, non-inferential result. Writing an earlier typed report emits the
current version 3 shape; loading does not recompute historical decisions.

Policy inspection and validation JSON uses document kind `benchmark_policy`
and schema version 3. Version 2 added the inference policy and stronger
evidence fields; version 3 adds the precision policy. Consumers should check
its producer, kind, schema version, and `valid` field before reading the
effective policy or validation error.

Writers emit one current version per document kind. Loaders in benchmatrix 1.x
continue to read every schema version emitted by a 1.x release, plus the
grandfathered version 1 run-group manifest. Dropping one of those read versions
requires a benchmatrix major release.

Adding, removing, renaming, or changing the type, requirement status, enum
domain, or meaning of a serialized field requires a document schema-version
increment.
Fixing validation to enforce the existing schema does not. A new document
schema may ship in a minor benchmatrix release when the same release retains
all earlier 1.x readers. Existing schema versions are never reinterpreted
incompatibly.

## Supported release branches

The active support branch is `main`.

The project does not currently maintain long-lived release branches. Security and
compatibility fixes are normally released from `main` in the next patch or minor
release. Temporary release branches may be created for an active release or
security fix, but they are not a standing support channel unless announced in the
release notes.

## Security-fix policy

Security fixes are provided for the latest minor line in the current major
series. Users must run its latest patch to receive fixes. Older minor lines and
previous major series do not receive routine backports or long-term support.

A backport to an older release may be considered when all of the following are
true:

* the issue is high impact for installed users;
* a safe, minimal patch can be prepared without carrying substantial branch
    maintenance cost;
* the affected release still has meaningful user adoption;
* the maintainer has capacity to validate and publish the backport.

See `SECURITY.md` and the security-report runbook for reporting and disclosure
steps.

## Deprecation policy

Deprecations are used for documented public API or behavior when users need a
migration path. Private implementation details do not require deprecation.

Deprecated public API normally remains available until the next major release
unless removal is needed for security or correctness.

Each deprecation should include:

* the replacement or migration path;
* a changelog entry;
* removal timing when known;
* tests that preserve the deprecated behavior until removal.

## Runtime scope

benchmatrix is intended for synchronous Python callables. Async functions,
concurrent service load tests, and production latency monitoring are outside the
current scope.

## pytest-benchmark

pytest-benchmark remains the timing engine. benchmatrix relies on its fixture,
statistics, and JSON output format, then layers metadata and parsing conventions
on top.
