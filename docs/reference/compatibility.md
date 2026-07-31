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
runs a smoke compatibility check on macOS and Windows for the current default
Python version. The primary quality job uses the repository `.python-version`.
Run `make test-matrix` locally before changes that may affect Python-version
compatibility.

## Supported operating systems

The package is intended to be OS-independent Python code and is classified as
`Operating System :: OS Independent`.

Supported operating systems are:

* Linux;
* macOS;
* Windows.

Pull request CI runs the full supported-Python test matrix on Ubuntu and a
current-Python smoke test on macOS and Windows. Linux is the primary continuously
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

Documented literal values such as metric names, compatibility modes, comparison
statuses, regression classifications, and severity values retain their meaning
throughout 1.x. Minor releases may add a value to an open set; callers should
handle an unfamiliar value explicitly rather than assume exhaustive matching.

| Value domain | Values defined by 1.0 |
| --- | --- |
| Metrics | `single_call_latency`, `batch_throughput`, `tail_latency` |
| Collection status | `succeeded`, `failed` |
| Compatibility mode | `strict`, `permissive`, `off` |
| Compatibility severity | `blocking`, `warning` |
| Comparison direction | `lower_is_better`, `higher_is_better` |
| Comparison status | `matched`, `missing_baseline`, `missing_candidate`, `incompatible` |
| Regression classification | `improved`, `unchanged`, `regressed`, `inconclusive`, `not_comparable` |
| Threshold scope | `cell`, `case`, `implementation`, `metric`, `default` |
| Policy selection | `defaults`, `disabled`, `discovered`, `explicit` |
| Threshold origin | `built_in`, `configuration`, `cli` |

All package-specific exceptions inherit from `BenchmatrixError`. JSON and policy
validation exceptions also remain `ValueError` subclasses, while collection
execution failures remain `RuntimeError` subclasses. Exception classes and base
relationships are stable; exact message wording is not.

## CLI compatibility

`benchmatrix` and `python -m benchmatrix` are equivalent entry points. These
commands and options are stable in 1.x:

| Command | Arguments and options |
| --- | --- |
| `collect` | `--runs`, required `--output`, `--resume`, `--retry-failed`, `--format` with `text` or `json`, and the pytest command after `--` |
| `compare` | baseline and candidate sources, repeatable `--baseline-run` and `--candidate-run`, `--threshold`, `--compatibility` with `strict`, `permissive`, or `off`; `--format` with `text`, `json`, or `markdown`; `--github-summary`, `--fail-on-regression`, `--minimum-runs`, `--minimum-samples`, and mutually exclusive `--config` or `--no-config` |
| `policy show` | mutually exclusive `--config` or `--no-config`, `--search-from`, and `--format` with `text` or `json` |
| `policy validate` | the `policy show` options plus `--quiet` |

Collection defaults to five successful runs for a new group and text output.
Comparison defaults to text output and does not fail the process for a reported
regression unless `--fail-on-regression` is present. Policy commands default to
text output and normal configuration discovery. Adding an optional command or
option is allowed in a minor release; removing or renaming one, changing an
existing option's meaning or default incompatibly, or repurposing an exit code
requires a major release.

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
and policy JSON use the versioned schemas below. `collect --format json` is a
stable 1.x summary whose existing keys and meanings will not be removed or
changed; the manifest is the canonical archival record.

## Configuration compatibility

The `[tool.benchmatrix]` schema is strict. Unknown keys are errors so spelling
mistakes cannot silently weaken a gate.

| Table | Stable keys |
| --- | --- |
| `compatibility` | `mode` (`strict`, `permissive`, or `off`; default `permissive`) |
| `evidence` | `minimum_runs` (`2`), `minimum_samples_per_run` (`5`), `require_rounds` (`true`), `require_iterations` (`true`), `maximum_cv` (unset), `maximum_outlier_fraction` (unset) |
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

Adding an optional configuration key is allowed in a minor release. Removing or
renaming a key, changing its type or meaning, changing selector precedence, or
changing a built-in decision default incompatibly requires a major release.

## Serialized document compatibility

Every canonical JSON document identifies its benchmatrix producer and schema
version. Documents with a `kind` field must also be dispatched by kind:

| Document | Identity written by 1.0 | Versions read by 1.x |
| --- | --- | --- |
| Benchmark-row `extra_info` | `benchmatrix_producer = "benchmatrix"`, `benchmatrix_schema_version = 1` | `1` |
| Run-group manifest | `producer = "benchmatrix"`, `kind = "benchmark_run_group"`, `schema_version = 2` | `1`, `2` |
| Comparison report | `producer = "benchmatrix"`, `kind = "benchmark_comparison"`, `schema_version = 1` | `1` |
| Policy inspection or validation | `producer = "benchmatrix"`, `kind = "benchmark_policy"`, `schema_version = 1` | Consumer-dispatched; benchmatrix does not load this document |

The pytest-benchmark top-level JSON envelope belongs to pytest-benchmark.
benchmatrix stabilizes its own `extra_info` keys and validates the upstream
statistics and metadata needed to interpret them. Additional user metadata may
coexist in `extra_info`.

New run-group manifests use schema version 2. The loader continues to accept
schema version 1 manifests produced before resumable collection was added.
Version 2 preserves the same core fields but permits attempt records beyond the
successful-run target so failed retries remain auditable. Version 1 manifests
cannot contain those appended retry records.

Comparison reports currently use schema version 1. Report loading is strict:
unsupported versions and unknown, missing, or inconsistent fields raise
`BenchmarkJsonError` instead of being interpreted as the current contract.

Policy inspection and validation JSON uses document kind `benchmark_policy` and
schema version 1. Consumers should check its producer, kind, schema version, and
`valid` field before reading the effective policy or validation error.

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
