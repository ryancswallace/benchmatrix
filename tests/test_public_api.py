"""Tests for public package exports and exception hierarchy."""

from __future__ import annotations

import benchkit


def test_public_api_exports_expected_names() -> None:
    expected_exports = {
        "__version__",
        "BenchmarkCase",
        "BenchmarkConfig",
        "BenchmarkInvocationRecord",
        "BenchmarkJsonError",
        "BenchkitError",
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
        "run_benchmark_metric",
        "shallow_copy",
    }

    assert set(benchkit.__all__) == expected_exports

    for name in benchkit.__all__:
        assert hasattr(benchkit, name)


def test_package_version_is_resolved() -> None:
    assert benchkit.__version__
    assert "unknown" not in benchkit.__version__


def test_package_exceptions_share_base_class_and_value_error_behavior() -> None:
    assert issubclass(benchkit.MetadataSerializationError, benchkit.BenchkitError)
    assert issubclass(benchkit.MetadataSerializationError, ValueError)
    assert issubclass(benchkit.BenchmarkJsonError, benchkit.BenchkitError)
    assert issubclass(benchkit.BenchmarkJsonError, ValueError)
