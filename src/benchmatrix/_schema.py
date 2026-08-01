"""Private schema for benchmatrix metadata embedded in pytest-benchmark output."""

from __future__ import annotations

from typing import Literal, TypeAlias

MetricName: TypeAlias = Literal[
    "single_call_latency",
    "batch_throughput",
    "tail_latency",
]

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

PRODUCER = "benchmatrix"
SCHEMA_VERSION = 1
BENCHMARK_SCHEMA_READ_VERSIONS = frozenset({1})
RUN_GROUP_KIND = "benchmark_run_group"
RUN_GROUP_SCHEMA_VERSION = 2
RUN_GROUP_SCHEMA_READ_VERSIONS = frozenset({1, 2})
PAIRED_RUN_GROUP_KIND = "benchmark_paired_run_group"
PAIRED_RUN_GROUP_SCHEMA_VERSION = 1
PAIRED_RUN_GROUP_SCHEMA_READ_VERSIONS = frozenset({1})
COMPARISON_REPORT_KIND = "benchmark_comparison"
COMPARISON_REPORT_SCHEMA_VERSION = 3
COMPARISON_REPORT_SCHEMA_READ_VERSIONS = frozenset({1, 2, 3})
POLICY_INSPECTION_KIND = "benchmark_policy"
POLICY_INSPECTION_SCHEMA_VERSION = 3

METRIC_SINGLE_CALL_LATENCY: MetricName = "single_call_latency"
METRIC_BATCH_THROUGHPUT: MetricName = "batch_throughput"
METRIC_TAIL_LATENCY: MetricName = "tail_latency"

DEFAULT_METRICS: tuple[MetricName, ...] = (
    METRIC_SINGLE_CALL_LATENCY,
    METRIC_BATCH_THROUGHPUT,
    METRIC_TAIL_LATENCY,
)

KNOWN_METRICS: frozenset[str] = frozenset(DEFAULT_METRICS)

KEY_PRODUCER = "benchmatrix_producer"
KEY_SCHEMA_VERSION = "benchmatrix_schema_version"
KEY_METRIC_NAME = "metric_name"
KEY_IMPLEMENTATION_NAME = "implementation_name"
KEY_CASE_NAME = "case_name"
KEY_CASE_FRESH_INPUTS = "case_fresh_inputs"
KEY_WORK_UNITS = "work_units"
KEY_WORK_UNIT_NAME = "work_unit_name"
KEY_THROUGHPUT_UNIT = "throughput_unit"
KEY_TAIL_LATENCY_NOTE = "tail_latency_note"
KEY_TAIL_PERCENTILES = "tail_percentiles"

THROUGHPUT_UNIT_CALLS_PER_SECOND = "calls_per_second"
THROUGHPUT_UNIT_WORK_UNITS_PER_SECOND = "work_units_per_second"

PERCENTILE_50 = 0.50
PERCENTILE_90 = 0.90
PERCENTILE_95 = 0.95
PERCENTILE_99 = 0.99

TAIL_PERCENTILES: tuple[float, ...] = (
    PERCENTILE_50,
    PERCENTILE_90,
    PERCENTILE_95,
    PERCENTILE_99,
)

JSON_KEY_BENCHMARKS = "benchmarks"
JSON_KEY_STATS = "stats"
JSON_KEY_EXTRA_INFO = "extra_info"
JSON_KEY_DATA = "data"
JSON_KEY_NAME = "name"
JSON_KEY_FULLNAME = "fullname"
JSON_KEY_DATETIME = "datetime"
JSON_KEY_VERSION = "version"
JSON_KEY_MACHINE_INFO = "machine_info"
JSON_KEY_COMMIT_INFO = "commit_info"

STAT_MEAN = "mean"
STAT_MEDIAN = "median"
STAT_MIN = "min"

DERIVED_LATENCY_MEAN = "latency_mean"
DERIVED_LATENCY_MEDIAN = "latency_median"
DERIVED_LATENCY_MIN = "latency_min"
DERIVED_THROUGHPUT_MEAN = "throughput_mean"
DERIVED_THROUGHPUT_MEDIAN = "throughput_median"
DERIVED_THROUGHPUT_UNIT_LABEL = "throughput_unit_label"
DERIVED_P50 = "p50"
DERIVED_P90 = "p90"
DERIVED_P95 = "p95"
DERIVED_P99 = "p99"
DERIVED_MAX = "max"
