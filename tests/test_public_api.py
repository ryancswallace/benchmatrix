"""Tests for public package exports and exception hierarchy."""

from __future__ import annotations

import pytest

import benchmatrix

pytestmark = pytest.mark.unit


def test_public_api_exports_expected_names() -> None:
    expected_exports = {
        "__version__",
        "BenchmarkCase",
        "BenchmarkConfig",
        "BenchmarkFixture",
        "BenchmarkInvocationRecord",
        "BenchmarkJsonError",
        "BenchmatrixError",
        "MetadataSerializationError",
        "MetricName",
        "ParsedBenchmarkRow",
        "TargetFunction",
        "benchmark_batch_throughput",
        "benchmark_single_call_latency",
        "benchmark_tail_latency",
        "deep_copy",
        "display_benchmark_row",
        "display_benchmark_rows",
        "load_benchmark_json",
        "make_benchmark_parameters",
        "make_benchmark_test",
        "run_benchmark_metric",
        "shallow_copy",
    }

    assert set(benchmatrix.__all__) == expected_exports

    for name in benchmatrix.__all__:
        assert hasattr(benchmatrix, name)


def test_package_version_is_resolved() -> None:
    assert benchmatrix.__version__
    assert "unknown" not in benchmatrix.__version__


def test_package_exceptions_share_base_class_and_value_error_behavior() -> None:
    assert issubclass(benchmatrix.MetadataSerializationError, benchmatrix.BenchmatrixError)
    assert issubclass(benchmatrix.MetadataSerializationError, ValueError)
    assert issubclass(benchmatrix.BenchmarkJsonError, benchmatrix.BenchmatrixError)
    assert issubclass(benchmatrix.BenchmarkJsonError, ValueError)
