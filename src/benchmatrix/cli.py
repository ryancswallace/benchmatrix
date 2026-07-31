"""Command-line interface for measuring, collecting, and comparing benchmark runs."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, TextIO, TypeVar, cast

from . import __version__
from ._schema import POLICY_INSPECTION_KIND, POLICY_INSPECTION_SCHEMA_VERSION, PRODUCER
from .bench_collection import (
    RUN_GROUP_MANIFEST,
    BenchmarkRunGroup,
    _redirect_collection_command_stdout,
    collect_benchmark_runs,
    load_benchmark_run_group,
)
from .bench_compare import (
    BenchmarkComparison,
    BenchmarkEvidence,
    BenchmarkRunComparison,
    CompatibilityMode,
    EvidencePolicy,
    RegressionPolicy,
    RegressionThresholdScope,
    RunCompatibilityPolicy,
    compare_benchmark_run_groups,
)
from .bench_policy import BenchmarkPolicyConfig, default_benchmark_policy, load_benchmark_policy
from .bench_report import (
    BenchmarkComparisonReport,
    BenchmarkPolicyProvenance,
    BenchmarkThresholdProvenance,
    format_comparison_report_markdown,
)
from .bench_results import BenchmarkRun, load_benchmark_run
from .exceptions import BenchmarkCollectionError, BenchmarkJsonError, BenchmarkPolicyError

_EXIT_SUCCESS = 0
_EXIT_POLICY_FAILURE = 1
_EXIT_USAGE_ERROR = 2
_SelectorName = TypeVar("_SelectorName", bound=str)


def _add_collection_options(parser: argparse.ArgumentParser) -> None:
    """Add options shared by measure and collect."""
    parser.add_argument(
        "--runs",
        type=_positive_integer,
        default=None,
        metavar="COUNT",
        help="Successful-run target (default for new collections: 5; preserved when resuming).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        metavar="DIR",
        help="New or empty directory, or an existing collection directory when resuming.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue initial attempts that are missing from an existing collection.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Resume and append one attempt for each successful run still needed.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Collection summary format (default: text).",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the benchmatrix command-line parser."""
    parser = argparse.ArgumentParser(
        prog="benchmatrix",
        description="Measure repeatable Python benchmark matrices and detect regressions.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect repeated pytest-benchmark runs.",
        description=(
            "Execute one pytest command sequentially and save validated "
            + "benchmark JSON files in a manifest-backed group."
        ),
    )
    _add_collection_options(collect_parser)
    collect_parser.add_argument(
        "pytest_command",
        nargs=argparse.REMAINDER,
        metavar="...",
        help="Pytest command after '--'; optional when resuming because the manifest command is reused.",
    )

    measure_parser = subparsers.add_parser(
        "measure",
        help="Measure pytest benchmarks with safe defaults.",
        description=(
            "Run pytest benchmarks sequentially with quiet reporting and isolated "
            + "pytest addopts, then save validated JSON files in a manifest-backed group."
        ),
    )
    _add_collection_options(measure_parser)
    measure_parser.add_argument(
        "--inherit-pytest-addopts",
        action="store_true",
        help="Use configured and PYTEST_ADDOPTS options instead of isolating the benchmark run.",
    )
    measure_parser.add_argument(
        "pytest_arguments",
        nargs=argparse.REMAINDER,
        metavar="TARGET ...",
        help=(
            "One or more pytest targets, followed by optional pytest arguments after '--'; "
            + "targets are optional when resuming because the manifest command is reused."
        ),
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare a baseline run with a candidate run.",
        description=(
            "Compare matching implementation, case, and metric cells while checking run-environment compatibility."
        ),
    )
    compare_parser.add_argument(
        "baseline",
        type=Path,
        help="Baseline JSON file, run-group manifest, or collection directory.",
    )
    compare_parser.add_argument(
        "candidate",
        type=Path,
        help="Candidate JSON file, run-group manifest, or collection directory.",
    )
    compare_parser.add_argument(
        "--baseline-run",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help="Additional baseline file, manifest, or directory; repeat as needed.",
    )
    compare_parser.add_argument(
        "--candidate-run",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help="Additional candidate file, manifest, or directory; repeat as needed.",
    )
    compare_parser.add_argument(
        "--threshold",
        type=_percentage,
        default=None,
        metavar="PERCENT",
        help="Override the default regression threshold; selector-specific configured thresholds remain active.",
    )
    compare_parser.add_argument(
        "--compatibility",
        choices=("strict", "permissive", "off"),
        default=None,
        help="Override the configured run-environment compatibility mode.",
    )
    compare_parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="Output format (default: text).",
    )
    compare_parser.add_argument(
        "--summary",
        action="store_true",
        help="Omit per-cell evidence diagnostics from text output.",
    )
    compare_parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Append the Markdown report to the path in GITHUB_STEP_SUMMARY.",
    )
    compare_parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit 1 for regressions, inconclusive evidence, incomplete matrices, or blocked compatibility.",
    )
    compare_parser.add_argument(
        "--minimum-runs",
        type=_positive_integer,
        default=None,
        metavar="COUNT",
        help="Override the configured minimum successful runs per side.",
    )
    compare_parser.add_argument(
        "--minimum-samples",
        type=_non_negative_integer,
        default=None,
        metavar="COUNT",
        help="Override the configured minimum raw samples per file and cell.",
    )
    config_group = compare_parser.add_mutually_exclusive_group()
    config_group.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="Load [tool.benchmatrix] from this TOML file instead of discovering pyproject.toml.",
    )
    config_group.add_argument(
        "--no-config",
        action="store_true",
        help="Disable pyproject.toml discovery and use built-in policies plus CLI overrides.",
    )

    policy_parser = subparsers.add_parser(
        "policy",
        help="Inspect or validate benchmark policy configuration.",
        description="Resolve the same effective benchmark policy used by the compare command.",
    )
    policy_actions = policy_parser.add_subparsers(dest="policy_command", required=True)
    policy_show = policy_actions.add_parser(
        "show",
        help="Display the resolved effective policy.",
    )
    policy_validate = policy_actions.add_parser(
        "validate",
        help="Validate policy configuration without running benchmarks.",
    )
    for action_parser in (policy_show, policy_validate):
        policy_config = action_parser.add_mutually_exclusive_group()
        policy_config.add_argument(
            "--config",
            type=Path,
            metavar="FILE",
            help="Validate and use [tool.benchmatrix] from this explicit TOML file.",
        )
        policy_config.add_argument(
            "--no-config",
            action="store_true",
            help="Inspect built-in defaults without discovering pyproject.toml.",
        )
        action_parser.add_argument(
            "--search-from",
            type=Path,
            metavar="PATH",
            help="Discover the nearest pyproject.toml from this file or directory.",
        )
        action_parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format (default: text).",
        )
    policy_validate.add_argument(
        "--quiet",
        action="store_true",
        help="Emit no output when validation succeeds.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmatrix command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "collect":
        return _run_collect(args)
    if args.command == "measure":
        return _run_measure(args)
    if args.command == "compare":
        return _run_compare(args)
    if args.command == "policy":
        return _run_policy(args)

    parser.error(f"Unsupported command: {args.command!r}")
    return _EXIT_USAGE_ERROR


@dataclass(frozen=True, slots=True)
class _LoadedRunSide:
    """Resolved benchmark runs and collection provenance for one side."""

    runs: tuple[BenchmarkRun, ...]
    paths: tuple[Path, ...]
    groups: tuple[BenchmarkRunGroup, ...]

    @property
    def collections_complete(self) -> bool:
        """Return whether every manifest-backed collection is complete."""
        return all(group.is_complete for group in self.groups)


@dataclass(frozen=True, slots=True)
class _PolicyContext:
    """Configuration selection and CLI override provenance."""

    config: BenchmarkPolicyConfig
    selection: str
    cli_overrides: tuple[str, ...]


def _run_collect(
    args: argparse.Namespace,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the collect subcommand."""
    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr
    command = tuple(cast(list[str], args.pytest_command))
    if command[:1] == ("--",):
        command = command[1:]

    return _collect_and_display(args, command, stdout=output, stderr=error_output)


def _run_measure(
    args: argparse.Namespace,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the measure subcommand."""
    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr
    try:
        command = _measure_command(
            cast(list[str], args.pytest_arguments),
            resume=bool(args.resume or args.retry_failed),
            inherit_addopts=bool(args.inherit_pytest_addopts),
        )
    except BenchmarkCollectionError as exc:
        print(f"benchmatrix: error: {exc}", file=error_output)
        return _EXIT_USAGE_ERROR

    if bool(args.inherit_pytest_addopts):
        return _collect_and_display(args, command, stdout=output, stderr=error_output)

    pytest_addopts = os.environ.pop("PYTEST_ADDOPTS", None)
    try:
        return _collect_and_display(args, command, stdout=output, stderr=error_output)
    finally:
        if pytest_addopts is not None:
            os.environ["PYTEST_ADDOPTS"] = pytest_addopts


def _measure_command(
    arguments: Sequence[str],
    *,
    resume: bool,
    inherit_addopts: bool,
) -> tuple[str, ...]:
    """Build the managed pytest command used by measure."""
    raw = tuple(arguments)
    if "--" in raw:
        separator = raw.index("--")
        targets = raw[:separator]
        forwarded = raw[separator + 1 :]
    else:
        targets = raw
        forwarded = ()

    if not targets:
        if forwarded:
            raise BenchmarkCollectionError("At least one pytest target is required before '--'.")
        if resume:
            return ()
        raise BenchmarkCollectionError("At least one pytest target is required.")
    if any(target.startswith("-") for target in targets):
        raise BenchmarkCollectionError("Put pytest options after '--', following the pytest targets.")

    for argument in forwarded:
        if argument == "--benchmark-json" or argument.startswith("--benchmark-json="):
            raise BenchmarkCollectionError("Do not supply --benchmark-json; benchmatrix assigns one output per run.")
        if argument in {"--benchmark-disable", "--benchmark-skip"}:
            raise BenchmarkCollectionError(f"{argument} cannot be used with benchmatrix measure.")

    command = [sys.executable, "-m", "pytest", "-q", "--benchmark-quiet"]
    if not inherit_addopts:
        command.extend(("-o", "addopts="))
    command.extend(targets)
    command.extend(forwarded)
    return tuple(command)


def _collect_and_display(
    args: argparse.Namespace,
    command: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Collect benchmark runs and display their summary."""

    try:
        if args.format == "json":
            with _redirect_collection_command_stdout(stderr):
                group = collect_benchmark_runs(
                    command,
                    cast(Path, args.output),
                    run_count=cast(int | None, args.runs),
                    resume=bool(args.resume or args.retry_failed),
                    retry_failed=bool(args.retry_failed),
                )
        else:
            group = collect_benchmark_runs(
                command,
                cast(Path, args.output),
                run_count=cast(int | None, args.runs),
                resume=bool(args.resume or args.retry_failed),
                retry_failed=bool(args.retry_failed),
            )
    except (BenchmarkCollectionError, BenchmarkJsonError, OSError, TypeError, ValueError) as exc:
        print(f"benchmatrix: error: {exc}", file=stderr)
        return _EXIT_USAGE_ERROR

    if args.format == "json":
        _display_collection_json(group, stream=stdout)
    else:
        _display_collection_text(group, stream=stdout)
    return _EXIT_SUCCESS if group.is_complete else _EXIT_POLICY_FAILURE


def _run_policy(
    args: argparse.Namespace,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the policy inspection or validation subcommand."""
    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr
    try:
        context = _resolve_policy_context(args)
    except (BenchmarkPolicyError, OSError, TypeError, ValueError) as exc:
        if args.policy_command == "validate" and args.format == "json" and not bool(args.quiet):
            _display_policy_json(None, error=str(exc), stream=output)
        else:
            print(f"benchmatrix: error: {exc}", file=error_output)
        return _EXIT_USAGE_ERROR

    if args.policy_command == "validate":
        if bool(args.quiet):
            return _EXIT_SUCCESS
        if args.format == "json":
            _display_policy_json(context, error=None, stream=output)
        else:
            description = "built-in defaults" if context.config.source is None else str(context.config.source)
            print(f"Benchmark policy is valid: {description} ({context.selection}).", file=output)
        return _EXIT_SUCCESS

    if args.format == "json":
        _display_policy_json(context, error=None, stream=output)
    else:
        _display_policy_text(context, stream=output)
    return _EXIT_SUCCESS


def _run_compare(
    args: argparse.Namespace,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the compare subcommand."""
    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr

    if bool(args.summary) and args.format != "text":
        print("benchmatrix: error: --summary requires --format text.", file=error_output)
        return _EXIT_USAGE_ERROR

    try:
        policy_context = _resolve_policy_context(args)
        baseline_paths = (cast(Path, args.baseline), *cast(list[Path], args.baseline_run))
        candidate_paths = (cast(Path, args.candidate), *cast(list[Path], args.candidate_run))
        baseline_side = _load_run_side(baseline_paths)
        candidate_side = _load_run_side(candidate_paths)
        overlapping_sources = {path.resolve() for path in baseline_side.paths} & {
            path.resolve() for path in candidate_side.paths
        }
        if overlapping_sources:
            overlap = min(overlapping_sources, key=str)
            raise BenchmarkJsonError(f"Baseline and candidate run sources overlap: {overlap}")
        compatibility_policy, regression_policy, evidence_policy = _apply_cli_policy_overrides(
            policy_context.config,
            args,
        )
        comparison = compare_benchmark_run_groups(
            baseline_side.runs,
            candidate_side.runs,
            compatibility_policy=compatibility_policy,
            regression_policy=regression_policy,
            evidence_policy=evidence_policy,
        )
        report = _make_comparison_report(
            comparison,
            baseline_side=baseline_side,
            candidate_side=candidate_side,
            policy_context=policy_context,
        )
        if bool(args.github_summary):
            _append_github_summary(report)
    except (BenchmarkJsonError, BenchmarkPolicyError, OSError, TypeError, ValueError) as exc:
        print(f"benchmatrix: error: {exc}", file=error_output)
        return _EXIT_USAGE_ERROR

    if args.format == "json":
        _display_json(report, stream=output)
    elif args.format == "markdown":
        print(format_comparison_report_markdown(report), end="", file=output)
    else:
        _display_text(
            comparison,
            baseline_side=baseline_side,
            candidate_side=candidate_side,
            policy_context=policy_context,
            summary=bool(args.summary),
            stream=output,
        )

    overall_passed = comparison.passed and baseline_side.collections_complete and candidate_side.collections_complete
    if bool(args.fail_on_regression) and not overall_passed:
        return _EXIT_POLICY_FAILURE
    return _EXIT_SUCCESS


def _resolve_policy_context(args: argparse.Namespace) -> _PolicyContext:
    """Resolve configured policies and record how they were selected."""
    no_config = bool(getattr(args, "no_config", False))
    config_path = cast(Path | None, getattr(args, "config", None))
    search_from = cast(Path | None, getattr(args, "search_from", None))
    if no_config:
        config = default_benchmark_policy()
        selection = "disabled"
    elif config_path is not None:
        config = load_benchmark_policy(config_path)
        selection = "explicit"
    else:
        config = load_benchmark_policy(search_from=search_from)
        selection = "discovered" if config.is_configured else "defaults"

    overrides: list[str] = []
    if getattr(args, "compatibility", None) is not None:
        overrides.append("compatibility.mode")
    if getattr(args, "threshold", None) is not None:
        overrides.append("regression.default_threshold_percent")
    if getattr(args, "minimum_runs", None) is not None:
        overrides.append("evidence.minimum_runs")
    if getattr(args, "minimum_samples", None) is not None:
        overrides.append("evidence.minimum_samples_per_run")
    return _PolicyContext(config=config, selection=selection, cli_overrides=tuple(overrides))


def _apply_cli_policy_overrides(
    config: BenchmarkPolicyConfig,
    args: argparse.Namespace,
) -> tuple[RunCompatibilityPolicy, RegressionPolicy, EvidencePolicy]:
    """Apply scalar CLI overrides without discarding configured selectors."""
    compatibility = config.compatibility
    if args.compatibility is not None:
        compatibility = RunCompatibilityPolicy(mode=cast(CompatibilityMode, args.compatibility))

    regression = config.regression
    if args.threshold is not None:
        regression = replace(
            regression,
            default_threshold_percent=cast(float, args.threshold),
        )

    evidence = config.evidence
    evidence_updates: dict[str, object] = {}
    if args.minimum_runs is not None:
        evidence_updates["minimum_runs"] = cast(int, args.minimum_runs)
    if args.minimum_samples is not None:
        evidence_updates["minimum_samples_per_run"] = cast(int, args.minimum_samples)
    if evidence_updates:
        evidence = replace(evidence, **evidence_updates)
    return compatibility, regression, evidence


def _make_comparison_report(
    comparison: BenchmarkRunComparison,
    *,
    baseline_side: _LoadedRunSide,
    candidate_side: _LoadedRunSide,
    policy_context: _PolicyContext,
) -> BenchmarkComparisonReport:
    """Create the versioned portable report for one CLI comparison."""
    provenance = BenchmarkPolicyProvenance(
        selection=cast(
            Literal["defaults", "disabled", "discovered", "explicit"],
            policy_context.selection,
        ),
        configuration_file=(None if policy_context.config.source is None else str(policy_context.config.source)),
        configured_fields=tuple(sorted(policy_context.config.configured_fields)),
        cli_overrides=policy_context.cli_overrides,
    )
    threshold_provenance = tuple(
        _threshold_provenance(
            cell,
            policy_context=policy_context,
            regression_policy=comparison.regression_policy,
        )
        for cell in comparison.comparisons
    )
    return BenchmarkComparisonReport.from_comparison(
        comparison,
        baselines=baseline_side.paths,
        candidates=candidate_side.paths,
        policy_provenance=provenance,
        threshold_provenance=threshold_provenance,
        baseline_collections=baseline_side.groups,
        candidate_collections=candidate_side.groups,
    )


def _load_run_side(paths: Sequence[Path]) -> _LoadedRunSide:
    """Expand run files and collection sources for one comparison side."""
    runs: list[BenchmarkRun] = []
    resolved_paths: list[Path] = []
    groups: list[BenchmarkRunGroup] = []
    seen_sources: set[Path] = set()

    def append_run(run: BenchmarkRun, source: Path) -> None:
        """Append one uniquely sourced run."""
        canonical_source = source.resolve()
        if canonical_source in seen_sources:
            raise BenchmarkJsonError(f"Duplicate benchmark run source: {source}")
        seen_sources.add(canonical_source)
        runs.append(run)
        resolved_paths.append(source)

    for path in paths:
        if path.is_dir() or path.name == RUN_GROUP_MANIFEST:
            group = load_benchmark_run_group(path)
            groups.append(group)
            for run in group.runs:
                if run.source is None:
                    raise BenchmarkJsonError(f"Collected benchmark run has no source path: {path}")
                append_run(run, run.source)
        else:
            run = load_benchmark_run(path)
            append_run(run, path)
    if not runs:
        raise BenchmarkJsonError("Benchmark comparison source contains no successful runs.")
    return _LoadedRunSide(runs=tuple(runs), paths=tuple(resolved_paths), groups=tuple(groups))


def _percentage(value: str) -> float:
    """Parse a finite, non-negative percentage argument."""
    stripped = value.strip()
    if stripped.endswith("%"):
        stripped = stripped[:-1].strip()
    if not stripped:
        raise argparse.ArgumentTypeError("percentage must not be empty")

    try:
        percentage = float(stripped)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid percentage: {value!r}") from exc
    if not math.isfinite(percentage):
        raise argparse.ArgumentTypeError("percentage must be finite")
    if percentage < 0.0:
        raise argparse.ArgumentTypeError("percentage must not be negative")
    return percentage


def _positive_integer(value: str) -> int:
    """Parse a positive integer argument."""
    parsed = _integer(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("count must be positive")
    return parsed


def _non_negative_integer(value: str) -> int:
    """Parse a non-negative integer argument."""
    parsed = _integer(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("count must not be negative")
    return parsed


def _integer(value: str) -> int:
    """Parse an integer argument without accepting float syntax."""
    try:
        return int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}") from exc


def _display_text(
    comparison: BenchmarkRunComparison,
    *,
    baseline_side: _LoadedRunSide,
    candidate_side: _LoadedRunSide,
    policy_context: _PolicyContext,
    summary: bool,
    stream: TextIO,
) -> None:
    """Display a concise human-readable comparison."""
    _display_policy_context(policy_context, stream=stream)
    _display_collection_inputs("Baseline", baseline_side.groups, stream=stream)
    _display_collection_inputs("Candidate", candidate_side.groups, stream=stream)
    compatibility = comparison.compatibility
    compatibility_label = "compatible" if compatibility.is_compatible else "blocked"
    print(
        f"Runs: {len(comparison.baseline_runs)} baseline, {len(comparison.candidate_runs)} candidate",
        file=stream,
    )
    print(
        "Compatibility: "
        + f"{compatibility_label} "
        + f"({len(compatibility.blocking)} blocking, {len(compatibility.warnings)} warning)",
        file=stream,
    )
    print(f"Environment pairs checked: {compatibility.pairs_checked}", file=stream)
    for finding in compatibility.findings:
        pair = ""
        if finding.baseline_run is not None and finding.candidate_run is not None:
            pair = f" [{finding.baseline_run} vs {finding.candidate_run}]"
        print(
            f"  {finding.severity.upper()} {finding.field}{pair}: {finding.reason} "
            + f"(baseline={finding.baseline_value!r}, candidate={finding.candidate_value!r})",
            file=stream,
        )

    print("", file=stream)
    print("Implementation | Case | Metric | Result | Improvement | Threshold", file=stream)
    print("--- | --- | --- | --- | ---: | ---:", file=stream)
    for cell in comparison.comparisons:
        result = cell.regression if cell.status == "matched" else cell.status
        print(
            " | ".join(
                (
                    cell.implementation_name,
                    cell.case_name,
                    cell.metric_name,
                    result,
                    _format_percent(cell.improvement_percent),
                    _format_threshold(cell.threshold_percent),
                )
            ),
            file=stream,
        )
        if not summary:
            _display_evidence("baseline", cell.baseline_evidence, stream=stream)
            _display_evidence("candidate", cell.candidate_evidence, stream=stream)
            if cell.improvement_low_percent is not None and cell.improvement_high_percent is not None:
                print(
                    "    repeated effect range: "
                    + f"{cell.improvement_low_percent:+.2f}% to {cell.improvement_high_percent:+.2f}%",
                    file=stream,
                )
            if cell.reason is not None:
                print(f"    diagnostic: {cell.reason}", file=stream)

    print("", file=stream)
    print(
        "Summary: "
        + f"{len(comparison.improved)} improved, "
        + f"{len(comparison.unchanged)} unchanged, "
        + f"{len(comparison.regressed)} regressed, "
        + f"{len(comparison.not_comparable)} not comparable",
        file=stream,
    )
    print(f"Evidence: {len(comparison.inconclusive)} inconclusive", file=stream)
    overall_passed = comparison.passed and baseline_side.collections_complete and candidate_side.collections_complete
    print(f"Overall: {'PASS' if overall_passed else 'FAIL'}", file=stream)


def _display_json(
    report: BenchmarkComparisonReport,
    *,
    stream: TextIO,
) -> None:
    """Display a stable JSON comparison document."""
    json.dump(report.to_dict(), stream, allow_nan=False, indent=2, sort_keys=True)
    print("", file=stream)


def _append_github_summary(report: BenchmarkComparisonReport) -> None:
    """Append a Markdown report to the GitHub Actions step summary."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        raise ValueError("--github-summary requires GITHUB_STEP_SUMMARY to name a writable file.")
    destination = Path(summary_path)
    prefix = "\n" if destination.exists() and destination.stat().st_size else ""
    with destination.open("a", encoding="utf-8") as stream:
        _ = stream.write(prefix + format_comparison_report_markdown(report))


def _display_policy_json(
    context: _PolicyContext | None,
    *,
    error: str | None,
    stream: TextIO,
) -> None:
    """Display a versioned policy inspection or validation document."""
    json.dump(
        _policy_json(context, error=error),
        stream,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    print("", file=stream)


def _policy_json(
    context: _PolicyContext | None,
    *,
    error: str | None,
) -> dict[str, object]:
    """Return the stable policy inspection or validation document."""
    payload: dict[str, object] = {
        "producer": PRODUCER,
        "kind": POLICY_INSPECTION_KIND,
        "schema_version": POLICY_INSPECTION_SCHEMA_VERSION,
        "valid": context is not None,
        "error": error,
    }
    if context is None:
        return payload

    config = context.config
    regression = config.regression
    payload.update(
        {
            "selection": context.selection,
            "source": None if config.source is None else str(config.source),
            "configured": config.is_configured,
            "configured_fields": sorted(config.configured_fields),
            "compatibility": {
                "mode": config.compatibility.mode,
            },
            "evidence": {
                "minimum_runs": config.evidence.minimum_runs,
                "minimum_samples_per_run": config.evidence.minimum_samples_per_run,
                "require_rounds": config.evidence.require_rounds,
                "require_iterations": config.evidence.require_iterations,
                "maximum_cv": config.evidence.maximum_cv,
                "maximum_outlier_fraction": config.evidence.maximum_outlier_fraction,
            },
            "regression": {
                "default_threshold_percent": regression.default_threshold_percent,
                "by_metric": dict(regression.by_metric),
                "by_implementation": dict(regression.by_implementation),
                "by_case": dict(regression.by_case),
                "by_cell": [
                    {
                        "implementation": implementation,
                        "case": case,
                        "metric": metric,
                        "threshold_percent": threshold,
                    }
                    for (implementation, case, metric), threshold in sorted(regression.by_cell.items())
                ],
            },
        }
    )
    return payload


def _display_policy_text(context: _PolicyContext, *, stream: TextIO) -> None:
    """Display the complete effective benchmark policy."""
    config = context.config
    source = "built-in defaults" if config.source is None else str(config.source)
    print("Benchmark policy: valid", file=stream)
    print(f"Selection: {context.selection}", file=stream)
    print(f"Source: {source}", file=stream)
    configured_fields = ", ".join(sorted(config.configured_fields)) or "none"
    print(f"Configured fields: {configured_fields}", file=stream)
    print("", file=stream)
    print("Compatibility", file=stream)
    print(f"  mode: {config.compatibility.mode}", file=stream)
    print("", file=stream)
    print("Evidence", file=stream)
    print(f"  minimum_runs: {config.evidence.minimum_runs}", file=stream)
    print(f"  minimum_samples_per_run: {config.evidence.minimum_samples_per_run}", file=stream)
    print(f"  require_rounds: {str(config.evidence.require_rounds).lower()}", file=stream)
    print(f"  require_iterations: {str(config.evidence.require_iterations).lower()}", file=stream)
    print(f"  maximum_cv: {_format_optional(config.evidence.maximum_cv)}", file=stream)
    print(
        "  maximum_outlier_fraction: " + _format_optional(config.evidence.maximum_outlier_fraction),
        file=stream,
    )
    print("", file=stream)
    print("Regression", file=stream)
    print(f"  default_threshold_percent: {config.regression.default_threshold_percent:g}", file=stream)
    _display_policy_selectors("by_metric", config.regression.by_metric, stream=stream)
    _display_policy_selectors(
        "by_implementation",
        config.regression.by_implementation,
        stream=stream,
    )
    _display_policy_selectors("by_case", config.regression.by_case, stream=stream)
    if config.regression.by_cell:
        print("  by_cell:", file=stream)
        for (implementation, case, metric), threshold in sorted(config.regression.by_cell.items()):
            print(f"    {implementation}/{case}/{metric}: {threshold:g}", file=stream)
    else:
        print("  by_cell: none", file=stream)


def _display_policy_selectors(
    label: str,
    selectors: Mapping[_SelectorName, float],
    *,
    stream: TextIO,
) -> None:
    """Display one policy selector mapping."""
    if not selectors:
        print(f"  {label}: none", file=stream)
        return
    print(f"  {label}:", file=stream)
    for key, value in sorted(selectors.items()):
        print(f"    {key}: {value:g}", file=stream)


def _format_optional(value: float | None) -> str:
    """Format an optional policy number."""
    return "none" if value is None else f"{value:g}"


def _display_collection_text(group: BenchmarkRunGroup, *, stream: TextIO) -> None:
    """Display a human-readable collection summary."""
    print(
        f"Collection: {group.successful_count}/{group.requested_runs} succeeded, "
        + f"{group.failed_count} failed across {group.attempted_count} attempt(s)",
        file=stream,
    )
    print(
        f"Lifecycle: {group.pending_count} pending, "
        + f"{group.retry_count} retry attempt(s), "
        + f"{group.remaining_count} successful run(s) still needed",
        file=stream,
    )
    print(f"Manifest: {group.manifest_path}", file=stream)
    if group.commit is not None:
        print(f"Commit: {group.commit}", file=stream)
    if group.environment_fingerprint is not None:
        print(f"Environment: {group.environment_fingerprint}", file=stream)
    for record in group.records:
        suffix = ""
        if record.status == "failed":
            suffix = f": {record.error}"
        elif record.warnings:
            suffix = f": {len(record.warnings)} environment warning(s)"
        print(
            f"  run {record.index:03d}: {record.status} ({record.duration_seconds:.3f}s){suffix}",
            file=stream,
        )
    print(f"Overall: {'PASS' if group.is_complete else 'FAIL'}", file=stream)


def _display_collection_json(group: BenchmarkRunGroup, *, stream: TextIO) -> None:
    """Display a stable JSON collection summary."""
    json.dump(_collection_json(group), stream, allow_nan=False, indent=2, sort_keys=True)
    print("", file=stream)


def _display_collection_inputs(
    label: str,
    groups: Sequence[BenchmarkRunGroup],
    *,
    stream: TextIO,
) -> None:
    """Display collection completeness before comparison diagnostics."""
    for group in groups:
        state = "complete" if group.is_complete else "incomplete"
        print(
            f"{label} collection: {state}; "
            + f"{group.successful_count}/{group.requested_runs} succeeded; "
            + f"{group.attempted_count} attempts; {group.retry_count} retries; "
            + f"manifest={group.manifest_path}",
            file=stream,
        )


def _collection_json(group: BenchmarkRunGroup) -> dict[str, object]:
    """Return a JSON-safe collection summary."""
    return {
        "manifest": str(group.manifest_path),
        "created_at": group.created_at,
        "command": list(group.command),
        "cwd": str(group.cwd),
        "commit": group.commit,
        "environment_fingerprint": group.environment_fingerprint,
        "requested_runs": group.requested_runs,
        "attempted_runs": group.attempted_count,
        "successful_runs": group.successful_count,
        "failed_runs": group.failed_count,
        "pending_runs": group.pending_count,
        "remaining_runs": group.remaining_count,
        "retry_attempts": group.retry_count,
        "complete": group.is_complete,
        "expected_cells": [
            {
                "implementation_name": implementation_name,
                "case_name": case_name,
                "metric_name": metric_name,
            }
            for implementation_name, case_name, metric_name in group.expected_cells
        ],
        "runs": [
            {
                "index": record.index,
                "status": record.status,
                "path": str(record.path),
                "returncode": record.returncode,
                "started_at": record.started_at,
                "duration_seconds": record.duration_seconds,
                "error": record.error,
                "warnings": list(record.warnings),
                "commit": record.commit,
                "environment_fingerprint": record.environment_fingerprint,
            }
            for record in group.records
        ],
    }


def _display_policy_context(context: _PolicyContext, *, stream: TextIO) -> None:
    """Display selected configuration and CLI policy overrides."""
    description = "built-in defaults" if context.config.source is None else str(context.config.source)
    print(f"Policy: {description} ({context.selection})", file=stream)
    if context.cli_overrides:
        print(f"Policy CLI overrides: {', '.join(context.cli_overrides)}", file=stream)


def _threshold_provenance(
    cell: BenchmarkComparison,
    *,
    policy_context: _PolicyContext,
    regression_policy: RegressionPolicy,
) -> BenchmarkThresholdProvenance:
    """Return the rule and origin supplying one cell's threshold."""
    scope = regression_policy.threshold_scope_for(
        cell.implementation_name,
        cell.case_name,
        cell.metric_name,
    )
    field = _threshold_field(cell, scope=scope)
    if field in policy_context.cli_overrides:
        origin = "cli"
    elif field in policy_context.config.configured_fields:
        origin = "configuration"
    else:
        origin = "built_in"
    return BenchmarkThresholdProvenance(
        scope=scope,
        origin=cast(Literal["built_in", "configuration", "cli"], origin),
        field=field,
    )


def _threshold_field(cell: BenchmarkComparison, *, scope: RegressionThresholdScope) -> str:
    """Return the configured-field path for a threshold selector."""
    if scope == "cell":
        return "regression.by_cell." + f"{cell.implementation_name}.{cell.case_name}.{cell.metric_name}"
    if scope == "case":
        return f"regression.by_case.{cell.case_name}"
    if scope == "implementation":
        return f"regression.by_implementation.{cell.implementation_name}"
    if scope == "metric":
        return f"regression.by_metric.{cell.metric_name}"
    return "regression.default_threshold_percent"


def _display_evidence(
    label: str,
    evidence: BenchmarkEvidence | None,
    *,
    stream: TextIO,
) -> None:
    """Display one compact evidence diagnostic line."""
    if evidence is None:
        return
    rounds = ",".join("-" if value is None else str(value) for value in evidence.rounds)
    iterations = ",".join("-" if value is None else str(value) for value in evidence.iterations)
    sample_counts = ",".join(str(value) for value in evidence.sample_counts)
    outliers = "-" if evidence.outlier_count is None else str(evidence.outlier_count)
    adequacy = "adequate" if evidence.adequate else "inadequate"
    print(
        f"    {label} evidence: {adequacy}; "
        + f"runs={evidence.observed_run_count}/{evidence.provided_run_count}; "
        + f"rounds=[{rounds}]; iterations=[{iterations}]; "
        + f"sample_counts=[{sample_counts}]; samples={evidence.sample_count}; "
        + f"IQR={_format_number(evidence.iqr)}; "
        + f"CV={_format_percent_fraction(evidence.coefficient_of_variation)}; "
        + f"outliers={outliers}",
        file=stream,
    )


def _format_percent(value: float | None) -> str:
    """Format a percentage for text output."""
    return "-" if value is None else f"{value:+.2f}%"


def _format_threshold(value: float) -> str:
    """Format an unsigned policy threshold."""
    return f"{value:.2f}%"


def _format_number(value: float | None) -> str:
    """Format a compact diagnostic number."""
    return "-" if value is None else f"{value:.6g}"


def _format_percent_fraction(value: float | None) -> str:
    """Format a fractional diagnostic as a percentage."""
    return "-" if value is None else f"{value * 100.0:.2f}%"
