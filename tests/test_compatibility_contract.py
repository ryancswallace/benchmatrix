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
    InferencePolicy,
    RegressionPolicy,
    RunCompatibilityPolicy,
    default_benchmark_policy,
)
from benchmatrix._schema import (
    BENCHMARK_SCHEMA_READ_VERSIONS,
    COMPARISON_REPORT_KIND,
    COMPARISON_REPORT_SCHEMA_READ_VERSIONS,
    COMPARISON_REPORT_SCHEMA_VERSION,
    PAIRED_RUN_GROUP_KIND,
    PAIRED_RUN_GROUP_SCHEMA_READ_VERSIONS,
    PAIRED_RUN_GROUP_SCHEMA_VERSION,
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
    InferenceMethod,
    IntervalMethod,
    MultiplicityCorrection,
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
    "collect_paired_benchmark_runs": (
        "(baseline_command: 'Sequence[str]', candidate_command: 'Sequence[str]', "
        "output_dir: 'str | Path', *, pair_count: 'int | None' = None, "
        "random_seed: 'int | None' = None, baseline_cwd: 'str | Path | None' = None, "
        "candidate_cwd: 'str | Path | None' = None, resume: 'bool' = False, "
        "retry_failed: 'bool' = False) -> 'BenchmarkPairedRunGroup'"
    ),
    "compare_benchmark_run_groups": (
        "(baselines: 'Sequence[BenchmarkRun]', candidates: 'Sequence[BenchmarkRun]', "
        "*, compatibility_policy: 'RunCompatibilityPolicy | None' = None, "
        "regression_policy: 'RegressionPolicy | None' = None, "
        "evidence_policy: 'EvidencePolicy | None' = None, "
        "inference_policy: 'InferencePolicy | None' = None, "
        "precision_policy: 'PrecisionPolicy | None' = None) -> 'BenchmarkRunComparison'"
    ),
    "compare_benchmark_runs": (
        "(baseline: 'BenchmarkRun', candidate: 'BenchmarkRun', *, "
        "compatibility_policy: 'RunCompatibilityPolicy | None' = None, "
        "regression_policy: 'RegressionPolicy | None' = None, "
        "inference_policy: 'InferencePolicy | None' = None, "
        "precision_policy: 'PrecisionPolicy | None' = None) -> 'BenchmarkRunComparison'"
    ),
    "compare_paired_benchmark_run_groups": (
        "(baselines: 'Sequence[BenchmarkRun]', candidates: 'Sequence[BenchmarkRun]', "
        "*, pair_strata: 'Sequence[str] | None' = None, "
        "precision_pair_count_multiple: 'int' = 2, "
        "compatibility_policy: 'RunCompatibilityPolicy | None' = None, "
        "regression_policy: 'RegressionPolicy | None' = None, "
        "evidence_policy: 'EvidencePolicy | None' = None, "
        "inference_policy: 'InferencePolicy | None' = None, "
        "precision_policy: 'PrecisionPolicy | None' = None) -> 'BenchmarkRunComparison'"
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
    "load_paired_benchmark_run_group": "(path: 'str | Path') -> 'BenchmarkPairedRunGroup'",
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
    "balanced_cell_order": (
        "(cells: 'Sequence[tuple[str, str, MetricName]]', *, order_index: 'int', "
        "random_seed: 'int' = 0) -> 'tuple[tuple[str, str, MetricName], ...]'"
    ),
    "balanced_order_cycle_length": "(cell_count: 'int') -> 'int'",
    "balanced_order_supercycle_length": "(cell_count: 'int') -> 'int'",
    "make_paired_ab_ba_schedule": (
        "(pair_count: 'int', *, random_seed: 'int' = 0, "
        "cell_count: 'int | None' = None) -> 'tuple[BenchmarkPairSchedule, ...]'"
    ),
    "plan_paired_precision": (
        "(baseline_values: 'Sequence[float]', candidate_values: 'Sequence[float]', *, "
        "lower_is_better: 'bool', target_half_width_percent: 'float', "
        "confidence_level: 'float' = 0.95, family_size: 'int' = 1, "
        "multiplicity: 'MultiplicityCorrection' = 'bonferroni', "
        "strata: 'Sequence[str] | None' = None, minimum_pairs: 'int' = 2, "
        "pair_count_multiple: 'int' = 2) -> 'PrecisionPlan'"
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
    "BenchmarkPairedCollectionSnapshot": (
        "manifest",
        "created_at",
        "baseline_command",
        "candidate_command",
        "baseline_cwd",
        "candidate_cwd",
        "baseline_commit",
        "candidate_commit",
        "baseline_environment_fingerprint",
        "candidate_environment_fingerprint",
        "requested_pairs",
        "random_seed",
        "expected_cells",
        "records",
        "automatic_pairs",
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
        "inference",
        "precision",
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
        "inference_policy",
        "design",
        "precision_policy",
        "paired_collections",
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
        "run_iqrs",
        "run_coefficients_of_variation",
        "run_outlier_counts",
        "run_outlier_fractions",
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
        "inference",
        "precision",
    ),
    "BenchmarkPolicyProvenance": (
        "selection",
        "configuration_file",
        "configured_fields",
        "cli_overrides",
    ),
    "BenchmarkPairedRunGroup": (
        "runs",
        "records",
        "baseline_command",
        "candidate_command",
        "created_at",
        "baseline_cwd",
        "candidate_cwd",
        "baseline_commit",
        "candidate_commit",
        "baseline_environment_fingerprint",
        "candidate_environment_fingerprint",
        "expected_cells",
        "requested_pairs",
        "random_seed",
        "manifest_path",
        "automatic_pairs",
    ),
    "BenchmarkPairedRunRecord": (
        "index",
        "pair_index",
        "block_attempt",
        "variant",
        "pair_order",
        "order_position",
        "cell_order_index",
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
    "BenchmarkPairSchedule": ("pair_index", "pair_order", "cell_order_index"),
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
        "inference_policy",
        "design",
        "precision_policy",
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
    "BenchmarkRunPair": (
        "pair_index",
        "block_attempt",
        "pair_order",
        "cell_order",
        "baseline",
        "candidate",
        "baseline_record",
        "candidate_record",
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
        "minimum_rounds_per_run",
        "require_rounds",
        "require_iterations",
        "require_raw_samples_for_inference",
        "minimum_tail_samples_per_run",
        "require_tail_iterations_one",
        "maximum_cv",
        "maximum_outlier_fraction",
    ),
    "BenchmarkInference": (
        "method",
        "estimand",
        "design",
        "confidence_level",
        "adjusted_confidence_level",
        "multiplicity",
        "family_size",
        "resamples",
        "random_seed",
        "estimate_percent",
        "confidence_low_percent",
        "confidence_high_percent",
        "warnings",
        "issues",
        "pair_count",
        "strata_count",
    ),
    "InferencePolicy": (
        "method",
        "confidence_level",
        "resamples",
        "random_seed",
        "multiplicity",
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
    "PrecisionPlan": (
        "method",
        "pilot_pairs",
        "target_half_width_percent",
        "confidence_level",
        "adjusted_confidence_level",
        "multiplicity",
        "family_size",
        "pilot_log_ratio_standard_deviation",
        "critical_value",
        "required_pairs",
        "additional_pairs",
        "assumptions",
        "minimum_pairs",
        "pair_count_multiple",
        "unconstrained_required_pairs",
        "strata_count",
        "warnings",
        "issues",
    ),
    "PrecisionPolicy": ("target_half_width_percent",),
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
    "benchmatrix collect-paired": (
        (
            ("-h", "--help"),
            ("--pairs",),
            ("--output",),
            ("--random-seed",),
            ("--baseline-cwd",),
            ("--candidate-cwd",),
            ("--resume",),
            ("--retry-failed",),
            ("--format",),
        ),
        ("paired_commands",),
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
            ("--paired",),
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
            ("--inference-method",),
            ("--confidence-level",),
            ("--bootstrap-resamples",),
            ("--random-seed",),
            ("--multiplicity",),
            ("--precision-target",),
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
    "benchmatrix collect-paired": {"format": ("text", "json")},
    "benchmatrix measure": {"format": ("text", "json")},
    "benchmatrix compare": {
        "compatibility": ("strict", "permissive", "off"),
        "format": ("text", "json", "markdown"),
        "inference_method": ("bca_bootstrap", "legacy_consistency"),
        "multiplicity": ("bonferroni", "none"),
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
    collect_paired = parser.parse_args(["collect-paired", "--output", "pairs", "--", "baseline", ":::", "candidate"])
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

    assert collect_paired.pairs is None
    assert collect_paired.output == Path("pairs")
    assert collect_paired.random_seed is None
    assert collect_paired.baseline_cwd is None
    assert collect_paired.candidate_cwd is None
    assert collect_paired.resume is False
    assert collect_paired.retry_failed is False
    assert collect_paired.format == "text"
    assert collect_paired.paired_commands == ["--", "baseline", ":::", "candidate"]

    assert measure.runs is None
    assert measure.output == Path("runs")
    assert measure.resume is False
    assert measure.retry_failed is False
    assert measure.format == "text"
    assert measure.inherit_pytest_addopts is False
    assert measure.pytest_arguments == ["benchmarks.py"]

    assert compare.baseline == Path("baseline.json")
    assert compare.candidate == Path("candidate.json")
    assert compare.paired is False
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
    assert compare.inference_method is None
    assert compare.confidence_level is None
    assert compare.bootstrap_resamples is None
    assert compare.random_seed is None
    assert compare.multiplicity is None
    assert compare.precision_target is None
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
        minimum_runs=5,
        minimum_samples_per_run=5,
        minimum_rounds_per_run=5,
        require_rounds=True,
        require_iterations=True,
        require_raw_samples_for_inference=True,
        minimum_tail_samples_per_run=100,
        require_tail_iterations_one=True,
        maximum_cv=None,
        maximum_outlier_fraction=None,
    )
    assert config.inference == InferencePolicy(
        method="bca_bootstrap",
        confidence_level=0.95,
        resamples=50_000,
        random_seed=0,
        multiplicity="bonferroni",
    )
    assert config.precision == benchmatrix.PrecisionPolicy()
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
    assert get_args(InferenceMethod) == ("bca_bootstrap", "legacy_consistency")
    assert get_args(IntervalMethod) == ("bca_bootstrap", "percentile_bootstrap")
    assert get_args(MultiplicityCorrection) == ("bonferroni", "none")
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
    assert PAIRED_RUN_GROUP_KIND == "benchmark_paired_run_group"
    assert PAIRED_RUN_GROUP_SCHEMA_VERSION == 1
    assert {1} == PAIRED_RUN_GROUP_SCHEMA_READ_VERSIONS
    assert COMPARISON_REPORT_KIND == "benchmark_comparison"
    assert COMPARISON_REPORT_SCHEMA_VERSION == 3
    assert {1, 2, 3} == COMPARISON_REPORT_SCHEMA_READ_VERSIONS
    assert POLICY_INSPECTION_KIND == "benchmark_policy"
    assert POLICY_INSPECTION_SCHEMA_VERSION == 3
