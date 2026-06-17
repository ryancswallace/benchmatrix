"""Shared private schema constants for benchkit metadata and results."""

from __future__ import annotations

from typing import Literal

type MetricName = Literal[
    "single_call_latency",
    "batch_throughput",
    "tail_latency",
]

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

PRODUCER = "benchkit"
SCHEMA_VERSION = 1

METRIC_SINGLE_CALL_LATENCY: MetricName = "single_call_latency"
METRIC_BATCH_THROUGHPUT: MetricName = "batch_throughput"
METRIC_TAIL_LATENCY: MetricName = "tail_latency"

DEFAULT_METRICS: tuple[MetricName, ...] = (
    METRIC_SINGLE_CALL_LATENCY,
    METRIC_BATCH_THROUGHPUT,
    METRIC_TAIL_LATENCY,
)

KNOWN_METRICS: frozenset[str] = frozenset(DEFAULT_METRICS)

KEY_PRODUCER = "benchkit_producer"
KEY_SCHEMA_VERSION = "benchkit_schema_version"
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
