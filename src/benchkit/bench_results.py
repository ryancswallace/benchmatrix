"""Utilities for reading and displaying pytest-benchmark JSON output."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, cast

from . import _schema
from ._schema import MetricName
from .exceptions import BenchmarkJsonError

type _BenchmarkStats = Mapping[str, object]

_NANOSECONDS_PER_SECOND = 1_000_000_000.0
_MICROSECONDS_PER_SECOND = 1_000_000.0
_MILLISECONDS_PER_SECOND = 1_000.0


@dataclass(frozen=True, slots=True)
class ParsedBenchmarkRow:
    """Parsed result row from pytest-benchmark JSON output.

    Attributes:
        benchmark_name: Name assigned by pytest-benchmark to this benchmark.
        metric_name: Benchkit metric name from ``extra_info``.
        implementation_name: Implementation name from ``extra_info``.
        case_name: Case name from ``extra_info``.
        stats: Raw pytest-benchmark timing statistics.
        extra_info: Custom metadata from ``benchmark.extra_info``.
        derived: Derived metric-specific statistics computed from JSON output.
    """

    benchmark_name: str
    metric_name: MetricName
    implementation_name: str
    case_name: str
    stats: _BenchmarkStats
    extra_info: _BenchmarkStats
    derived: _BenchmarkStats


def load_benchmark_json(path: str | Path) -> list[ParsedBenchmarkRow]:
    """Load pytest-benchmark JSON output and derive metric-specific fields.

    Args:
        path: Path to a JSON file created with ``--benchmark-json``.

    Returns:
        Parsed benchmark rows with raw and derived statistics.

    Raises:
        BenchmarkJsonError: If the JSON does not have the expected
            pytest-benchmark and benchkit structure.
    """
    path_obj = Path(path)

    try:
        payload = json.loads(path_obj.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BenchmarkJsonError(f"Could not read benchmark JSON: {path_obj}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkJsonError(f"Invalid JSON in benchmark file: {path_obj}") from exc

    payload_mapping = _require_mapping(payload, path="root")
    benchmarks = _require_list(
        payload_mapping.get(_schema.JSON_KEY_BENCHMARKS),
        path=f"root.{_schema.JSON_KEY_BENCHMARKS}",
    )

    rows: list[ParsedBenchmarkRow] = []
    for index, benchmark_entry in enumerate(benchmarks):
        entry_path = f"root.{_schema.JSON_KEY_BENCHMARKS}[{index}]"
        entry = _require_mapping(benchmark_entry, path=entry_path)
        extra_info = _require_mapping(
            entry.get(_schema.JSON_KEY_EXTRA_INFO),
            path=f"{entry_path}.{_schema.JSON_KEY_EXTRA_INFO}",
        )
        _require_benchkit_schema(extra_info, path=f"{entry_path}.{_schema.JSON_KEY_EXTRA_INFO}")

        stats = _require_mapping(
            entry.get(_schema.JSON_KEY_STATS),
            path=f"{entry_path}.{_schema.JSON_KEY_STATS}",
        )

        metric_name = _require_metric_name(
            extra_info.get(_schema.KEY_METRIC_NAME),
            path=f"{entry_path}.{_schema.JSON_KEY_EXTRA_INFO}.{_schema.KEY_METRIC_NAME}",
        )
        data = _extract_benchmark_data(entry, stats, metric_name, path=entry_path)

        rows.append(
            ParsedBenchmarkRow(
                benchmark_name=_stringify_name(
                    entry.get(
                        _schema.JSON_KEY_NAME,
                        entry.get(_schema.JSON_KEY_FULLNAME, ""),
                    )
                ),
                metric_name=metric_name,
                implementation_name=_require_string(
                    extra_info.get(_schema.KEY_IMPLEMENTATION_NAME),
                    path=f"{entry_path}.{_schema.JSON_KEY_EXTRA_INFO}.{_schema.KEY_IMPLEMENTATION_NAME}",
                ),
                case_name=_require_string(
                    extra_info.get(_schema.KEY_CASE_NAME),
                    path=f"{entry_path}.{_schema.JSON_KEY_EXTRA_INFO}.{_schema.KEY_CASE_NAME}",
                ),
                stats=stats,
                extra_info=extra_info,
                derived=_derive_stats(metric_name, stats, extra_info, data),
            )
        )

    return rows


def display_benchmark_rows(
    rows: Iterable[ParsedBenchmarkRow],
    stream: TextIO | None = None,
) -> None:
    """Print concise summaries parsed from pytest-benchmark JSON output.

    Args:
        rows: Parsed benchmark rows.
        stream: Output stream. Defaults to ``sys.stdout``.
    """
    for row in rows:
        display_benchmark_row(row, stream=stream)


def display_benchmark_row(
    row: ParsedBenchmarkRow,
    stream: TextIO | None = None,
) -> None:
    """Print one parsed pytest-benchmark JSON benchmark row.

    Args:
        row: Parsed benchmark row to display.
        stream: Output stream. Defaults to ``sys.stdout``.
    """
    output = sys.stdout if stream is None else stream
    prefix = f"[{row.metric_name}] implementation={row.implementation_name} case={row.case_name}"

    if row.metric_name == _schema.METRIC_SINGLE_CALL_LATENCY:
        print(
            f"{prefix} mean={_format_seconds(row.stats.get(_schema.STAT_MEAN))} "
            f"median={_format_seconds(row.stats.get(_schema.STAT_MEDIAN))} "
            f"min={_format_seconds(row.stats.get(_schema.STAT_MIN))}",
            file=output,
        )
        return

    if row.metric_name == _schema.METRIC_BATCH_THROUGHPUT:
        print(
            f"{prefix} "
            f"throughput_mean="
            f"{_format_rate(row.derived.get(_schema.DERIVED_THROUGHPUT_MEAN))} "
            f"throughput_median="
            f"{_format_rate(row.derived.get(_schema.DERIVED_THROUGHPUT_MEDIAN))} "
            f"unit={row.derived.get(_schema.DERIVED_THROUGHPUT_UNIT_LABEL)}",
            file=output,
        )
        return

    if row.metric_name == _schema.METRIC_TAIL_LATENCY:
        print(
            f"{prefix} p50={_format_seconds(row.derived.get(_schema.DERIVED_P50))} "
            f"p95={_format_seconds(row.derived.get(_schema.DERIVED_P95))} "
            f"p99={_format_seconds(row.derived.get(_schema.DERIVED_P99))} "
            f"max={_format_seconds(row.derived.get(_schema.DERIVED_MAX))}",
            file=output,
        )
        return

    print(
        f"{prefix} mean={_format_seconds(row.stats.get(_schema.STAT_MEAN))}",
        file=output,
    )


def _require_benchkit_schema(
    extra_info: Mapping[str, object],
    *,
    path: str,
) -> None:
    """Validate benchkit producer and schema-version metadata."""
    producer = _require_string(
        extra_info.get(_schema.KEY_PRODUCER),
        path=f"{path}.{_schema.KEY_PRODUCER}",
    )
    if producer != _schema.PRODUCER:
        raise BenchmarkJsonError(f"Unsupported benchmark producer at {path}: {producer!r}.")

    schema_version = _require_int(
        extra_info.get(_schema.KEY_SCHEMA_VERSION),
        path=f"{path}.{_schema.KEY_SCHEMA_VERSION}",
    )
    if schema_version != _schema.SCHEMA_VERSION:
        raise BenchmarkJsonError(f"Unsupported benchkit schema version at {path}: {schema_version!r}.")


def _derive_stats(
    metric_name: MetricName,
    stats: Mapping[str, object],
    extra_info: Mapping[str, object],
    data: Sequence[float],
) -> _BenchmarkStats:
    """Derive metric-specific statistics from pytest-benchmark JSON fields."""
    if metric_name == _schema.METRIC_SINGLE_CALL_LATENCY:
        return _derive_latency_stats(stats)

    if metric_name == _schema.METRIC_BATCH_THROUGHPUT:
        return _derive_throughput_stats(stats, extra_info)

    if metric_name == _schema.METRIC_TAIL_LATENCY:
        return _derive_tail_stats(data)

    raise BenchmarkJsonError(f"Unsupported benchkit metric: {metric_name!r}")


def _derive_latency_stats(stats: Mapping[str, object]) -> _BenchmarkStats:
    """Derive latency fields from elapsed-time statistics."""
    return {
        _schema.DERIVED_LATENCY_MEAN: _require_float_stat(
            stats,
            _schema.STAT_MEAN,
        ),
        _schema.DERIVED_LATENCY_MEDIAN: _require_float_stat(
            stats,
            _schema.STAT_MEDIAN,
        ),
        _schema.DERIVED_LATENCY_MIN: _require_float_stat(
            stats,
            _schema.STAT_MIN,
        ),
    }


def _derive_throughput_stats(
    stats: Mapping[str, object],
    extra_info: Mapping[str, object],
) -> _BenchmarkStats:
    """Derive throughput fields from elapsed-time statistics."""
    mean_seconds = _require_float_stat(stats, _schema.STAT_MEAN)
    median_seconds = _require_float_stat(stats, _schema.STAT_MEDIAN)
    throughput_unit = _require_string(
        extra_info.get(_schema.KEY_THROUGHPUT_UNIT),
        path=f"extra_info.{_schema.KEY_THROUGHPUT_UNIT}",
    )

    if throughput_unit == _schema.THROUGHPUT_UNIT_WORK_UNITS_PER_SECOND:
        work_units = _require_float(
            extra_info.get(_schema.KEY_WORK_UNITS),
            path=f"extra_info.{_schema.KEY_WORK_UNITS}",
        )
        work_unit_name = _require_string(
            extra_info.get(_schema.KEY_WORK_UNIT_NAME),
            path=f"extra_info.{_schema.KEY_WORK_UNIT_NAME}",
        )
        return {
            _schema.DERIVED_THROUGHPUT_MEAN: _safe_divide(
                work_units,
                mean_seconds,
            ),
            _schema.DERIVED_THROUGHPUT_MEDIAN: _safe_divide(
                work_units,
                median_seconds,
            ),
            _schema.DERIVED_THROUGHPUT_UNIT_LABEL: f"{work_unit_name}/s",
        }

    if throughput_unit == _schema.THROUGHPUT_UNIT_CALLS_PER_SECOND:
        return {
            _schema.DERIVED_THROUGHPUT_MEAN: _safe_divide(1.0, mean_seconds),
            _schema.DERIVED_THROUGHPUT_MEDIAN: _safe_divide(1.0, median_seconds),
            _schema.DERIVED_THROUGHPUT_UNIT_LABEL: "calls/s",
        }

    raise BenchmarkJsonError(f"Unsupported throughput unit: {throughput_unit!r}")


def _derive_tail_stats(data: Sequence[float]) -> _BenchmarkStats:
    """Derive latency-percentile fields from raw benchmark samples."""
    return {
        _schema.DERIVED_P50: _percentile(data, _schema.PERCENTILE_50),
        _schema.DERIVED_P90: _percentile(data, _schema.PERCENTILE_90),
        _schema.DERIVED_P95: _percentile(data, _schema.PERCENTILE_95),
        _schema.DERIVED_P99: _percentile(data, _schema.PERCENTILE_99),
        _schema.DERIVED_MAX: max(data),
    }


def _extract_benchmark_data(
    entry: Mapping[str, object],
    stats: Mapping[str, object],
    metric_name: MetricName,
    *,
    path: str,
) -> list[float]:
    """Extract raw benchmark sample data from supported JSON locations."""
    raw_data = entry.get(_schema.JSON_KEY_DATA)

    if raw_data is None:
        raw_data = stats.get(_schema.JSON_KEY_DATA)

    if raw_data is None:
        data: list[float] = []
    else:
        data = _require_float_list(raw_data, path=f"{path}.{_schema.JSON_KEY_DATA}")

    if metric_name == _schema.METRIC_TAIL_LATENCY and not data:
        raise BenchmarkJsonError(
            f"{path} is a tail_latency benchmark but does not contain raw "
            "sample data under either the benchmark entry or stats mapping."
        )

    return data


def _percentile(values: Sequence[float], quantile: float) -> float:
    """Return a linearly interpolated percentile."""
    if not 0.0 <= quantile <= 1.0:
        raise BenchmarkJsonError("quantile must be between 0.0 and 1.0 inclusive.")

    if not values:
        raise BenchmarkJsonError("Cannot compute a percentile from an empty sequence.")

    data = sorted(values)

    if len(data) == 1:
        return data[0]

    position = (len(data) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return data[lower_index]

    upper_weight = position - lower_index
    lower_weight = 1.0 - upper_weight
    return data[lower_index] * lower_weight + data[upper_index] * upper_weight


def _safe_divide(numerator: float, denominator: float) -> float:
    """Divide floats and return NaN for a zero denominator."""
    if denominator == 0.0:
        return math.nan

    return numerator / denominator


def _format_seconds(value: object) -> str:
    """Format a seconds value using a human-readable unit."""
    numeric_value = _as_float(value)

    if numeric_value is None:
        return "nan"

    if numeric_value < 1.0 / _MICROSECONDS_PER_SECOND:
        return f"{numeric_value * _NANOSECONDS_PER_SECOND:,.2f} ns"

    if numeric_value < 1.0 / _MILLISECONDS_PER_SECOND:
        return f"{numeric_value * _MICROSECONDS_PER_SECOND:,.2f} us"

    if numeric_value < 1.0:
        return f"{numeric_value * _MILLISECONDS_PER_SECOND:,.2f} ms"

    return f"{numeric_value:,.3f} s"


def _format_rate(value: object) -> str:
    """Format a rate value using no decimal places."""
    numeric_value = _as_float(value)
    return "nan" if numeric_value is None else f"{numeric_value:,.0f}"


def _require_mapping(value: object, *, path: str) -> Mapping[str, object]:
    """Return a string-keyed mapping or raise a schema error."""
    if not isinstance(value, Mapping):
        raise BenchmarkJsonError(f"Expected mapping at {path}, got {type(value).__name__}.")

    for key in value:
        if not isinstance(key, str):
            raise BenchmarkJsonError(f"Expected string key in mapping at {path}, got {type(key).__name__}.")

    return cast(Mapping[str, object], value)


def _require_list(value: object, *, path: str) -> list[object]:
    """Return a list or raise a schema error."""
    if not isinstance(value, list):
        raise BenchmarkJsonError(f"Expected list at {path}, got {type(value).__name__}.")

    return value


def _require_float_list(value: object, *, path: str) -> list[float]:
    """Return a list of finite floats or raise a schema error."""
    values = _require_list(value, path=path)
    floats: list[float] = []

    for index, item in enumerate(values):
        floats.append(_require_float(item, path=f"{path}[{index}]"))

    return floats


def _require_metric_name(value: object, *, path: str) -> MetricName:
    """Return a supported metric name or raise a schema error."""
    if not isinstance(value, str):
        raise BenchmarkJsonError(f"Expected metric name string at {path}.")

    if value not in _schema.KNOWN_METRICS:
        raise BenchmarkJsonError(f"Unsupported benchkit metric at {path}: {value!r}.")

    return cast(MetricName, value)


def _require_string(value: object, *, path: str) -> str:
    """Return a string or raise a schema error."""
    if not isinstance(value, str):
        raise BenchmarkJsonError(f"Expected string at {path}, got {type(value).__name__}.")

    return value


def _require_int(value: object, *, path: str) -> int:
    """Return an integer or raise a schema error."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchmarkJsonError(f"Expected integer at {path}, got {type(value).__name__}.")

    return value


def _stringify_name(value: object) -> str:
    """Return a benchmark name string."""
    if isinstance(value, str):
        return value

    return str(value)


def _require_float_stat(stats: Mapping[str, object], key: str) -> float:
    """Return a required finite float from a stats mapping."""
    return _require_float(stats.get(key), path=f"stats.{key}")


def _require_float(value: object, *, path: str) -> float:
    """Return a finite float or raise a schema error."""
    numeric_value = _as_float(value)

    if numeric_value is None:
        raise BenchmarkJsonError(f"Expected finite numeric value at {path}.")

    return numeric_value


def _as_float(value: object) -> float | None:
    """Return a finite float or None."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    return result if math.isfinite(result) else None
