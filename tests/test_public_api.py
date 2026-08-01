"""Tests for public package exports and exception hierarchy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import get_type_hints

import pytest

import benchmatrix

pytestmark = pytest.mark.unit


def test_public_api_exports_expected_names() -> None:
    expected_exports = {
        "__version__",
        "BenchmarkCase",
        "BenchmarkCollectionError",
        "BenchmarkCollectionSnapshot",
        "BenchmarkComparison",
        "BenchmarkComparisonReport",
        "BenchmarkConfig",
        "BenchmarkEvidence",
        "BenchmarkFixture",
        "BenchmarkHookContext",
        "BenchmarkInference",
        "BenchmarkInvocationRecord",
        "BenchmarkJsonError",
        "BenchmarkLifecycleHook",
        "BenchmarkPairedRunGroup",
        "BenchmarkPairedRunRecord",
        "BenchmarkPairedCollectionSnapshot",
        "BenchmarkPairSchedule",
        "BenchmarkPolicyConfig",
        "BenchmarkPolicyError",
        "BenchmarkPolicyProvenance",
        "BenchmarkRun",
        "BenchmarkRunComparison",
        "BenchmarkRunGroup",
        "BenchmarkRunPair",
        "BenchmarkRunRecord",
        "BenchmarkThresholdProvenance",
        "BenchmarkResultValidator",
        "BenchmatrixError",
        "EvidencePolicy",
        "InferencePolicy",
        "MetadataSerializationError",
        "MetricName",
        "ParsedBenchmarkRow",
        "PrecisionPlan",
        "PrecisionPolicy",
        "RegressionPolicy",
        "RunCompatibilityFinding",
        "RunCompatibilityPolicy",
        "RunCompatibilityReport",
        "TargetFunction",
        "benchmark_batch_throughput",
        "benchmark_single_call_latency",
        "benchmark_tail_latency",
        "balanced_cell_order",
        "balanced_order_cycle_length",
        "balanced_order_supercycle_length",
        "collect_paired_benchmark_runs",
        "compare_paired_benchmark_run_groups",
        "compare_benchmark_runs",
        "compare_benchmark_run_groups",
        "collect_benchmark_runs",
        "deep_copy",
        "default_benchmark_policy",
        "display_benchmark_row",
        "display_benchmark_rows",
        "format_comparison_report_markdown",
        "load_benchmark_json",
        "load_comparison_report",
        "load_benchmark_run",
        "load_benchmark_run_group",
        "load_paired_benchmark_run_group",
        "load_benchmark_policy",
        "make_benchmark_parameters",
        "make_benchmark_test",
        "make_paired_ab_ba_schedule",
        "plan_paired_precision",
        "run_benchmark_metric",
        "shallow_copy",
        "write_comparison_report",
        "write_comparison_report_markdown",
    }

    assert set(benchmatrix.__all__) == expected_exports

    for name in benchmatrix.__all__:
        assert hasattr(benchmatrix, name)


def test_package_root_excludes_low_level_constants_and_literal_aliases() -> None:
    excluded_exports = {
        "RUN_GROUP_MANIFEST",
        "BenchmarkCell",
        "CollectionRunStatus",
        "ComparisonDirection",
        "ComparisonStatus",
        "CompatibilityMode",
        "CompatibilitySeverity",
        "PolicySelection",
        "RegressionClassification",
        "RegressionThresholdScope",
        "ThresholdOrigin",
    }

    assert excluded_exports.isdisjoint(benchmatrix.__all__)
    for name in excluded_exports:
        assert not hasattr(benchmatrix, name)


def test_public_annotations_do_not_expose_private_aliases() -> None:
    row_annotations = get_type_hints(benchmatrix.ParsedBenchmarkRow)
    parameter_annotations = get_type_hints(benchmatrix.make_benchmark_parameters)

    assert row_annotations["stats"] == Mapping[str, object]
    assert row_annotations["extra_info"] == Mapping[str, object]
    assert row_annotations["derived"] == Mapping[str, object]
    assert parameter_annotations["return"] == list[object]


def test_package_version_is_resolved() -> None:
    assert benchmatrix.__version__
    assert "unknown" not in benchmatrix.__version__


def test_package_exceptions_share_base_class_and_value_error_behavior() -> None:
    assert issubclass(benchmatrix.MetadataSerializationError, benchmatrix.BenchmatrixError)
    assert issubclass(benchmatrix.MetadataSerializationError, ValueError)
    assert issubclass(benchmatrix.BenchmarkJsonError, benchmatrix.BenchmatrixError)
    assert issubclass(benchmatrix.BenchmarkJsonError, ValueError)
    assert issubclass(benchmatrix.BenchmarkCollectionError, benchmatrix.BenchmatrixError)
    assert issubclass(benchmatrix.BenchmarkCollectionError, RuntimeError)
    assert issubclass(benchmatrix.BenchmarkPolicyError, benchmatrix.BenchmatrixError)
    assert issubclass(benchmatrix.BenchmarkPolicyError, ValueError)
