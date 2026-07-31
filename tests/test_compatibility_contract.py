"""Executable guards for the stable benchmatrix 1.x compatibility contract."""

from __future__ import annotations

import argparse
import dataclasses
import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import cast, get_args

import pytest

import benchmatrix
from benchmatrix import (
    EvidencePolicy,
    RegressionPolicy,
    RunCompatibilityPolicy,
    default_benchmark_policy,
)
from benchmatrix._schema import (
    BENCHMARK_SCHEMA_READ_VERSIONS,
    COMPARISON_REPORT_KIND,
    COMPARISON_REPORT_SCHEMA_READ_VERSIONS,
    COMPARISON_REPORT_SCHEMA_VERSION,
    POLICY_INSPECTION_KIND,
    POLICY_INSPECTION_SCHEMA_VERSION,
    PRODUCER,
    RUN_GROUP_KIND,
    RUN_GROUP_SCHEMA_READ_VERSIONS,
    RUN_GROUP_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from benchmatrix.bench_collection import CollectionRunStatus
from benchmatrix.bench_compare import (
    ComparisonDirection,
    ComparisonStatus,
    CompatibilityMode,
    CompatibilitySeverity,
    RegressionClassification,
    RegressionThresholdScope,
)
from benchmatrix.bench_report import PolicySelection, ThresholdOrigin
from benchmatrix.cli import build_parser

pytestmark = pytest.mark.unit

_STABLE_FUNCTION_SIGNATURES = {
    "benchmark_batch_throughput": (
        "(benchmark: 'BenchmarkFixture', implementation_name: 'str', "
        "function: 'TargetFunction', case_name: 'str', case: 'BenchmarkCase', "
        "*, config: 'BenchmarkConfig | None' = None, "
        "stream: 'TextIO | None' = None) -> 'BenchmarkInvocationRecord'"
    ),
    "benchmark_single_call_latency": (
        "(benchmark: 'BenchmarkFixture', implementation_name: 'str', "
        "function: 'TargetFunction', case_name: 'str', case: 'BenchmarkCase', "
        "*, config: 'BenchmarkConfig | None' = None, "
        "stream: 'TextIO | None' = None) -> 'BenchmarkInvocationRecord'"
    ),
    "benchmark_tail_latency": (
        "(benchmark: 'BenchmarkFixture', implementation_name: 'str', "
        "function: 'TargetFunction', case_name: 'str', case: 'BenchmarkCase', "
        "*, config: 'BenchmarkConfig | None' = None, "
        "stream: 'TextIO | None' = None) -> 'BenchmarkInvocationRecord'"
    ),
    "collect_benchmark_runs": (
        "(command: 'Sequence[str]', output_dir: 'str | Path', *, "
        "run_count: 'int | None' = None, resume: 'bool' = False, "
        "retry_failed: 'bool' = False) -> 'BenchmarkRunGroup'"
    ),
    "compare_benchmark_run_groups": (
        "(baselines: 'Sequence[BenchmarkRun]', candidates: 'Sequence[BenchmarkRun]', "
        "*, compatibility_policy: 'RunCompatibilityPolicy | None' = None, "
        "regression_policy: 'RegressionPolicy | None' = None, "
        "evidence_policy: 'EvidencePolicy | None' = None) -> 'BenchmarkRunComparison'"
    ),
    "compare_benchmark_runs": (
        "(baseline: 'BenchmarkRun', candidate: 'BenchmarkRun', *, "
        "compatibility_policy: 'RunCompatibilityPolicy | None' = None, "
        "regression_policy: 'RegressionPolicy | None' = None) -> 'BenchmarkRunComparison'"
    ),
    "deep_copy": "(value: 'object') -> 'object'",
    "default_benchmark_policy": "() -> 'BenchmarkPolicyConfig'",
    "display_benchmark_row": "(row: 'ParsedBenchmarkRow', stream: 'TextIO | None' = None) -> 'None'",
    "display_benchmark_rows": ("(rows: 'Iterable[ParsedBenchmarkRow]', stream: 'TextIO | None' = None) -> 'None'"),
    "format_comparison_report_markdown": "(report: 'BenchmarkComparisonReport') -> 'str'",
    "load_benchmark_json": "(path: 'str | Path') -> 'list[ParsedBenchmarkRow]'",
    "load_benchmark_policy": (
        "(path: 'str | Path | None' = None, *, search_from: 'str | Path | None' = None) -> 'BenchmarkPolicyConfig'"
    ),
    "load_benchmark_run": "(path: 'str | Path') -> 'BenchmarkRun'",
    "load_benchmark_run_group": "(path: 'str | Path') -> 'BenchmarkRunGroup'",
    "load_comparison_report": "(path: 'str | Path') -> 'BenchmarkComparisonReport'",
    "make_benchmark_parameters": (
        "(implementations: 'Mapping[str, TargetFunction]', "
        "cases: 'Mapping[str, BenchmarkCase] | Iterable[BenchmarkCase]', *, "
        "metrics: 'Iterable[MetricName] | None' = None) -> 'list[object]'"
    ),
    "make_benchmark_test": (
        "(implementations: 'Mapping[str, TargetFunction]', "
        "cases: 'Mapping[str, BenchmarkCase] | Iterable[BenchmarkCase]', *, "
        "metrics: 'Iterable[MetricName] | None' = None, "
        "config: 'BenchmarkConfig | None' = None) -> 'Callable[..., None]'"
    ),
    "run_benchmark_metric": (
        "(benchmark: 'BenchmarkFixture', metric_name: 'MetricName', "
        "implementation_name: 'str', function: 'TargetFunction', "
        "case_name: 'str', case: 'BenchmarkCase', *, "
        "config: 'BenchmarkConfig | None' = None, "
        "stream: 'TextIO | None' = None) -> 'BenchmarkInvocationRecord'"
    ),
    "shallow_copy": "(value: 'object') -> 'object'",
    "write_comparison_report": ("(report: 'BenchmarkComparisonReport', path: 'str | Path') -> 'None'"),
    "write_comparison_report_markdown": ("(report: 'BenchmarkComparisonReport', path: 'str | Path') -> 'None'"),
}

_STABLE_RECORD_FIELDS = {
    "BenchmarkCase": (
        "name",
        "make_args",
        "make_kwargs",
        "work_units",
        "work_unit_name",
        "fresh_inputs",
        "metadata",
    ),
    "BenchmarkCollectionSnapshot": (
        "manifest",
        "created_at",
        "command",
        "cwd",
        "commit",
        "environment_fingerprint",
        "requested_runs",
        "expected_cells",
        "records",
    ),
    "BenchmarkComparison": (
        "implementation_name",
        "case_name",
        "metric_name",
        "statistic",
        "direction",
        "status",
        "baseline_value",
        "candidate_value",
        "ratio",
        "percent_change",
        "improvement_percent",
        "regression",
        "threshold_percent",
        "unit",
        "baseline_evidence",
        "candidate_evidence",
        "improvement_low_percent",
        "improvement_high_percent",
        "reason",
    ),
    "BenchmarkComparisonReport": (
        "baselines",
        "candidates",
        "baseline_collections",
        "candidate_collections",
        "compatibility",
        "evidence_policy",
        "regression_policy",
        "policy_provenance",
        "comparisons",
        "threshold_provenance",
    ),
    "BenchmarkConfig": (
        "pedantic_rounds",
        "warmup_rounds",
        "pedantic_iterations",
        "stream_progress",
        "before_benchmark",
        "validate_result",
        "after_benchmark",
    ),
    "BenchmarkEvidence": (
        "provided_run_count",
        "observed_run_count",
        "rounds",
        "iterations",
        "sample_counts",
        "sample_count",
        "iqr",
        "coefficient_of_variation",
        "outlier_count",
        "outlier_fraction",
        "adequate",
        "issues",
    ),
    "BenchmarkHookContext": (
        "metric_name",
        "implementation_name",
        "case_name",
        "function",
        "case",
    ),
    "BenchmarkInvocationRecord": (
        "metric_name",
        "implementation_name",
        "case_name",
        "extra_info",
    ),
    "BenchmarkPolicyConfig": (
        "compatibility",
        "evidence",
        "regression",
        "source",
        "configured_fields",
    ),
    "BenchmarkPolicyProvenance": (
        "selection",
        "configuration_file",
        "configured_fields",
        "cli_overrides",
    ),
    "BenchmarkRun": ("rows", "metadata", "source"),
    "BenchmarkRunComparison": (
        "baseline",
        "candidate",
        "compatibility",
        "regression_policy",
        "comparisons",
        "baseline_runs",
        "candidate_runs",
        "evidence_policy",
    ),
    "BenchmarkRunGroup": (
        "runs",
        "records",
        "command",
        "created_at",
        "cwd",
        "commit",
        "environment_fingerprint",
        "expected_cells",
        "requested_runs",
        "manifest_path",
    ),
    "BenchmarkRunRecord": (
        "index",
        "status",
        "path",
        "returncode",
        "started_at",
        "duration_seconds",
        "error",
        "warnings",
        "commit",
        "environment_fingerprint",
    ),
    "BenchmarkThresholdProvenance": ("scope", "origin", "field"),
    "EvidencePolicy": (
        "minimum_runs",
        "minimum_samples_per_run",
        "require_rounds",
        "require_iterations",
        "maximum_cv",
        "maximum_outlier_fraction",
    ),
    "ParsedBenchmarkRow": (
        "benchmark_name",
        "metric_name",
        "implementation_name",
        "case_name",
        "stats",
        "extra_info",
        "derived",
        "samples",
    ),
    "RegressionPolicy": (
        "default_threshold_percent",
        "by_metric",
        "by_implementation",
        "by_case",
        "by_cell",
    ),
    "RunCompatibilityFinding": (
        "field",
        "baseline_value",
        "candidate_value",
        "severity",
        "reason",
        "baseline_run",
        "candidate_run",
    ),
    "RunCompatibilityPolicy": ("mode",),
    "RunCompatibilityReport": ("policy", "findings", "pairs_checked"),
}

_CLI_SURFACE = {
    "benchmatrix": ((("-h", "--help"), ("--version",)), ()),
    "benchmatrix collect": (
        (
            ("-h", "--help"),
            ("--runs",),
            ("--output",),
            ("--resume",),
            ("--retry-failed",),
            ("--format",),
        ),
        ("pytest_command",),
    ),
    "benchmatrix measure": (
        (
            ("-h", "--help"),
            ("--runs",),
            ("--output",),
            ("--resume",),
            ("--retry-failed",),
            ("--format",),
            ("--inherit-pytest-addopts",),
        ),
        ("pytest_arguments",),
    ),
    "benchmatrix compare": (
        (
            ("-h", "--help"),
            ("--baseline-run",),
            ("--candidate-run",),
            ("--threshold",),
            ("--compatibility",),
            ("--format",),
            ("--summary",),
            ("--github-summary",),
            ("--fail-on-regression",),
            ("--minimum-runs",),
            ("--minimum-samples",),
            ("--config",),
            ("--no-config",),
        ),
        ("baseline", "candidate"),
    ),
    "benchmatrix policy": ((("-h", "--help"),), ()),
    "benchmatrix policy show": (
        (
            ("-h", "--help"),
            ("--config",),
            ("--no-config",),
            ("--search-from",),
            ("--format",),
        ),
        (),
    ),
    "benchmatrix policy validate": (
        (
            ("-h", "--help"),
            ("--config",),
            ("--no-config",),
            ("--search-from",),
            ("--format",),
            ("--quiet",),
        ),
        (),
    ),
}

_CLI_CHOICES = {
    "benchmatrix": {},
    "benchmatrix collect": {"format": ("text", "json")},
    "benchmatrix measure": {"format": ("text", "json")},
    "benchmatrix compare": {
        "compatibility": ("strict", "permissive", "off"),
        "format": ("text", "json", "markdown"),
    },
    "benchmatrix policy": {},
    "benchmatrix policy show": {"format": ("text", "json")},
    "benchmatrix policy validate": {"format": ("text", "json")},
}


def _parser_actions(parser: argparse.ArgumentParser) -> tuple[argparse.Action, ...]:
    """Return argparse actions without spreading private access through tests."""
    return tuple(cast(list[argparse.Action], parser._actions))


def _child_parsers(parser: argparse.ArgumentParser) -> Mapping[str, argparse.ArgumentParser]:
    """Return one parser's named subcommands."""
    for action in _parser_actions(parser):
        choices: object = action.choices
        if (
            isinstance(choices, dict)
            and choices
            and all(isinstance(value, argparse.ArgumentParser) for value in choices.values())
        ):
            return cast(dict[str, argparse.ArgumentParser], choices)
    return {}


def _cli_surface(
    parser: argparse.ArgumentParser,
    *,
    path: str = "benchmatrix",
) -> dict[str, tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]]:
    """Return the recursive command, option, and positional surface."""
    children = _child_parsers(parser)
    options = tuple(tuple(action.option_strings) for action in _parser_actions(parser) if action.option_strings)
    positionals = tuple(
        action.dest
        for action in _parser_actions(parser)
        if not action.option_strings and action.dest not in {"command", "policy_command"}
    )
    result = {path: (options, positionals)}
    for name, child in children.items():
        result.update(_cli_surface(child, path=f"{path} {name}"))
    return result


def _cli_choices(
    parser: argparse.ArgumentParser,
    *,
    path: str = "benchmatrix",
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Return the recursive finite-choice option contract."""
    choices = {
        action.dest: tuple(cast(tuple[str, ...], action.choices))
        for action in _parser_actions(parser)
        if action.option_strings and isinstance(action.choices, tuple)
    }
    result = {path: choices}
    for name, child in _child_parsers(parser).items():
        result.update(_cli_choices(child, path=f"{path} {name}"))
    return result


def test_stable_function_signatures_match_v1_contract() -> None:
    actual = {name: str(inspect.signature(getattr(benchmatrix, name))) for name in _STABLE_FUNCTION_SIGNATURES}

    assert actual == _STABLE_FUNCTION_SIGNATURES


def test_stable_record_fields_match_v1_contract() -> None:
    actual = {
        name: tuple(field.name for field in dataclasses.fields(getattr(benchmatrix, name)))
        for name in _STABLE_RECORD_FIELDS
    }

    assert actual == _STABLE_RECORD_FIELDS


def test_cli_commands_options_and_positionals_match_v1_contract() -> None:
    assert _cli_surface(build_parser()) == _CLI_SURFACE
    assert _cli_choices(build_parser()) == _CLI_CHOICES


def test_cli_defaults_and_choices_match_v1_contract() -> None:
    parser = build_parser()
    collect = parser.parse_args(["collect", "--output", "runs", "--", "pytest"])
    measure = parser.parse_args(["measure", "--output", "runs", "benchmarks.py"])
    compare = parser.parse_args(["compare", "baseline.json", "candidate.json"])
    policy_show = parser.parse_args(["policy", "show"])
    policy_validate = parser.parse_args(["policy", "validate"])

    assert collect.runs is None
    assert collect.output == Path("runs")
    assert collect.resume is False
    assert collect.retry_failed is False
    assert collect.format == "text"
    assert collect.pytest_command == ["--", "pytest"]

    assert measure.runs is None
    assert measure.output == Path("runs")
    assert measure.resume is False
    assert measure.retry_failed is False
    assert measure.format == "text"
    assert measure.inherit_pytest_addopts is False
    assert measure.pytest_arguments == ["benchmarks.py"]

    assert compare.baseline == Path("baseline.json")
    assert compare.candidate == Path("candidate.json")
    assert compare.baseline_run == []
    assert compare.candidate_run == []
    assert compare.threshold is None
    assert compare.compatibility is None
    assert compare.format == "text"
    assert compare.summary is False
    assert compare.github_summary is False
    assert compare.fail_on_regression is False
    assert compare.minimum_runs is None
    assert compare.minimum_samples is None
    assert compare.config is None
    assert compare.no_config is False

    assert policy_show.config is None
    assert policy_show.no_config is False
    assert policy_show.search_from is None
    assert policy_show.format == "text"
    assert policy_validate.quiet is False


def test_cli_usage_errors_write_stderr_and_exit_two(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        _ = build_parser().parse_args([])

    output = capsys.readouterr()
    assert raised.value.code == 2
    assert output.out == ""
    assert "required: command" in output.err


def test_policy_defaults_metrics_and_precedence_match_v1_contract() -> None:
    config = default_benchmark_policy()
    policy = RegressionPolicy(
        default_threshold_percent=10.0,
        by_metric={"single_call_latency": 8.0},
        by_implementation={"impl": 6.0},
        by_case={"case": 4.0},
        by_cell={("impl", "exact", "single_call_latency"): 2.0},
    )

    assert get_args(benchmatrix.MetricName) == (
        "single_call_latency",
        "batch_throughput",
        "tail_latency",
    )
    assert config.compatibility == RunCompatibilityPolicy(mode="permissive")
    assert config.evidence == EvidencePolicy(
        minimum_runs=2,
        minimum_samples_per_run=5,
        require_rounds=True,
        require_iterations=True,
        maximum_cv=None,
        maximum_outlier_fraction=None,
    )
    assert config.regression == RegressionPolicy(default_threshold_percent=5.0)
    assert policy.threshold_scope_for("impl", "exact", "single_call_latency") == "cell"
    assert policy.threshold_scope_for("impl", "case", "single_call_latency") == "case"
    assert policy.threshold_scope_for("impl", "other", "single_call_latency") == "implementation"
    assert policy.threshold_scope_for("other", "other", "single_call_latency") == "metric"
    assert policy.threshold_scope_for("other", "other", "tail_latency") == "default"


def test_stable_literal_value_domains_match_v1_contract() -> None:
    assert get_args(CollectionRunStatus) == ("succeeded", "failed")
    assert get_args(ComparisonDirection) == ("lower_is_better", "higher_is_better")
    assert get_args(ComparisonStatus) == (
        "matched",
        "missing_baseline",
        "missing_candidate",
        "incompatible",
    )
    assert get_args(CompatibilityMode) == ("strict", "permissive", "off")
    assert get_args(CompatibilitySeverity) == ("blocking", "warning")
    assert get_args(RegressionClassification) == (
        "improved",
        "unchanged",
        "regressed",
        "inconclusive",
        "not_comparable",
    )
    assert get_args(RegressionThresholdScope) == (
        "cell",
        "case",
        "implementation",
        "metric",
        "default",
    )
    assert get_args(PolicySelection) == ("defaults", "disabled", "discovered", "explicit")
    assert get_args(ThresholdOrigin) == ("built_in", "configuration", "cli")


def test_document_identities_and_read_windows_match_v1_contract() -> None:
    assert PRODUCER == "benchmatrix"
    assert SCHEMA_VERSION == 1
    assert {1} == BENCHMARK_SCHEMA_READ_VERSIONS
    assert RUN_GROUP_KIND == "benchmark_run_group"
    assert RUN_GROUP_SCHEMA_VERSION == 2
    assert {1, 2} == RUN_GROUP_SCHEMA_READ_VERSIONS
    assert COMPARISON_REPORT_KIND == "benchmark_comparison"
    assert COMPARISON_REPORT_SCHEMA_VERSION == 1
    assert {1} == COMPARISON_REPORT_SCHEMA_READ_VERSIONS
    assert POLICY_INSPECTION_KIND == "benchmark_policy"
    assert POLICY_INSPECTION_SCHEMA_VERSION == 1
