"""Public pytest-benchmark matrix and JSON results API."""

from importlib.metadata import PackageNotFoundError, version

from ._schema import MetricName
from .bench_harness import (
    BenchmarkCase,
    BenchmarkConfig,
    BenchmarkFixture,
    BenchmarkInvocationRecord,
    TargetFunction,
    benchmark_batch_throughput,
    benchmark_single_call_latency,
    benchmark_tail_latency,
    deep_copy,
    make_benchmark_parameters,
    make_benchmark_test,
    run_benchmark_metric,
    shallow_copy,
)
from .bench_results import (
    ParsedBenchmarkRow,
    display_benchmark_row,
    display_benchmark_rows,
    load_benchmark_json,
)
from .exceptions import BenchkitError, BenchmarkJsonError, MetadataSerializationError

try:
    __version__ = version("benchkit")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "__version__",
    "BenchmarkCase",
    "BenchmarkConfig",
    "BenchmarkFixture",
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
    "make_benchmark_test",
    "run_benchmark_metric",
    "shallow_copy",
]
