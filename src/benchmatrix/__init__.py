"""Public pytest-benchmark matrix and JSON results API."""

from importlib.metadata import PackageNotFoundError, version

from ._schema import MetricName
from .bench_collection import (
    BenchmarkRunGroup,
    BenchmarkRunRecord,
    collect_benchmark_runs,
    load_benchmark_run_group,
)
from .bench_compare import (
    BenchmarkComparison,
    BenchmarkEvidence,
    BenchmarkRunComparison,
    EvidencePolicy,
    RegressionPolicy,
    RunCompatibilityFinding,
    RunCompatibilityPolicy,
    RunCompatibilityReport,
    compare_benchmark_run_groups,
    compare_benchmark_runs,
)
from .bench_harness import (
    BenchmarkCase,
    BenchmarkConfig,
    BenchmarkFixture,
    BenchmarkHookContext,
    BenchmarkInvocationRecord,
    BenchmarkLifecycleHook,
    BenchmarkResultValidator,
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
from .bench_policy import BenchmarkPolicyConfig, default_benchmark_policy, load_benchmark_policy
from .bench_report import (
    BenchmarkCollectionSnapshot,
    BenchmarkComparisonReport,
    BenchmarkPolicyProvenance,
    BenchmarkThresholdProvenance,
    format_comparison_report_markdown,
    load_comparison_report,
    write_comparison_report,
    write_comparison_report_markdown,
)
from .bench_results import (
    BenchmarkRun,
    ParsedBenchmarkRow,
    display_benchmark_row,
    display_benchmark_rows,
    load_benchmark_json,
    load_benchmark_run,
)
from .exceptions import (
    BenchmarkCollectionError,
    BenchmarkJsonError,
    BenchmarkPolicyError,
    BenchmatrixError,
    MetadataSerializationError,
)

try:
    __version__ = version("benchmatrix")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "BenchmarkCase",
    "BenchmarkCollectionError",
    "BenchmarkCollectionSnapshot",
    "BenchmarkComparison",
    "BenchmarkComparisonReport",
    "BenchmarkConfig",
    "BenchmarkEvidence",
    "BenchmarkFixture",
    "BenchmarkHookContext",
    "BenchmarkInvocationRecord",
    "BenchmarkJsonError",
    "BenchmarkLifecycleHook",
    "BenchmarkPolicyConfig",
    "BenchmarkPolicyError",
    "BenchmarkPolicyProvenance",
    "BenchmarkResultValidator",
    "BenchmarkRun",
    "BenchmarkRunComparison",
    "BenchmarkRunGroup",
    "BenchmarkRunRecord",
    "BenchmarkThresholdProvenance",
    "BenchmatrixError",
    "EvidencePolicy",
    "MetadataSerializationError",
    "MetricName",
    "ParsedBenchmarkRow",
    "RegressionPolicy",
    "RunCompatibilityFinding",
    "RunCompatibilityPolicy",
    "RunCompatibilityReport",
    "TargetFunction",
    "__version__",
    "benchmark_batch_throughput",
    "benchmark_single_call_latency",
    "benchmark_tail_latency",
    "collect_benchmark_runs",
    "compare_benchmark_run_groups",
    "compare_benchmark_runs",
    "deep_copy",
    "default_benchmark_policy",
    "display_benchmark_row",
    "display_benchmark_rows",
    "format_comparison_report_markdown",
    "load_benchmark_json",
    "load_benchmark_policy",
    "load_benchmark_run",
    "load_benchmark_run_group",
    "load_comparison_report",
    "make_benchmark_parameters",
    "make_benchmark_test",
    "run_benchmark_metric",
    "shallow_copy",
    "write_comparison_report",
    "write_comparison_report_markdown",
]
