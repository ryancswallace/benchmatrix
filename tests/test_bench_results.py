"""Tests for pytest-benchmark JSON parsing and display helpers."""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import cast

import pytest

from benchkit import (
    BenchmarkJsonError,
    MetricName,
    ParsedBenchmarkRow,
    display_benchmark_row,
    display_benchmark_rows,
    load_benchmark_json,
)

pytestmark = pytest.mark.unit

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "benchmark_results"


def _extra_info(metric_name: str, **overrides: object) -> dict[str, object]:
    """Return a valid benchkit extra_info mapping."""
    extra_info: dict[str, object] = {
        "benchkit_producer": "benchkit",
        "benchkit_schema_version": 1,
        "metric_name": metric_name,
        "implementation_name": "impl",
        "case_name": "small",
        "case_fresh_inputs": False,
    }
    extra_info.update(overrides)
    return extra_info


def _benchmark_entry(
    metric_name: str,
    *,
    name: object = "test_module.py::test_benchmark[case]",
    extra_info: dict[str, object] | None = None,
    stats: dict[str, object] | None = None,
    data: list[object] | None = None,
) -> dict[str, object]:
    """Return a pytest-benchmark JSON entry."""
    entry: dict[str, object] = {
        "name": name,
        "extra_info": _extra_info(metric_name) if extra_info is None else extra_info,
        "stats": {"mean": 2.0, "median": 4.0, "min": 1.0} if stats is None else stats,
    }
    if data is not None:
        entry["data"] = data
    return entry


def _write_payload(tmp_path: Path, payload: object) -> Path:
    """Write a JSON payload and return its path."""
    path = tmp_path / "benchmark.json"
    _ = path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _load_entry(tmp_path: Path, entry: dict[str, object]) -> ParsedBenchmarkRow:
    """Load a single benchmark entry."""
    rows = load_benchmark_json(_write_payload(tmp_path, {"benchmarks": [entry]}))
    assert len(rows) == 1
    return rows[0]


def test_load_benchmark_json_reads_representative_fixture() -> None:
    rows = load_benchmark_json(FIXTURE_DIR / "mixed_metrics.json")

    assert [row.metric_name for row in rows] == ["single_call_latency", "batch_throughput", "tail_latency"]
    assert rows[0].derived == {"latency_mean": 0.001, "latency_median": 0.002, "latency_min": 0.0005}
    assert rows[1].derived["throughput_mean"] == 4.0
    assert rows[1].derived["throughput_median"] == 3.0
    assert rows[1].derived["throughput_unit_label"] == "rows/s"
    assert rows[2].derived["p95"] == pytest.approx(4.8)


def test_load_benchmark_json_rejects_invalid_fixture() -> None:
    with pytest.raises(BenchmarkJsonError, match="does not contain raw sample data"):
        _ = load_benchmark_json(FIXTURE_DIR / "invalid_tail_missing_data.json")


def test_load_benchmark_json_derives_latency_stats(tmp_path: Path) -> None:
    row = _load_entry(
        tmp_path,
        _benchmark_entry(
            "single_call_latency",
            stats={"mean": 0.001, "median": 0.002, "min": 0.0005},
        ),
    )

    assert row.benchmark_name == "test_module.py::test_benchmark[case]"
    assert row.metric_name == "single_call_latency"
    assert row.implementation_name == "impl"
    assert row.case_name == "small"
    assert row.derived == {
        "latency_mean": 0.001,
        "latency_median": 0.002,
        "latency_min": 0.0005,
    }


def test_load_benchmark_json_derives_call_throughput(tmp_path: Path) -> None:
    row = _load_entry(
        tmp_path,
        _benchmark_entry(
            "batch_throughput",
            extra_info=_extra_info("batch_throughput", throughput_unit="calls_per_second"),
            stats={"mean": 0.25, "median": 0.5, "min": 0.1},
        ),
    )

    assert row.derived["throughput_mean"] == 4.0
    assert row.derived["throughput_median"] == 2.0
    assert row.derived["throughput_unit_label"] == "calls/s"


def test_load_benchmark_json_derives_work_unit_throughput(tmp_path: Path) -> None:
    row = _load_entry(
        tmp_path,
        _benchmark_entry(
            "batch_throughput",
            name="test_module.py::test_benchmark[batch]",
            extra_info=_extra_info(
                "batch_throughput",
                throughput_unit="work_units_per_second",
                work_units=10.0,
                work_unit_name="rows",
            ),
            stats={"mean": 2.0, "median": 4.0, "min": 1.0},
        ),
    )

    assert row.benchmark_name == "test_module.py::test_benchmark[batch]"
    assert row.derived["throughput_mean"] == 5.0
    assert row.derived["throughput_median"] == 2.5
    assert row.derived["throughput_unit_label"] == "rows/s"


def test_load_benchmark_json_handles_zero_second_throughput_as_nan(tmp_path: Path) -> None:
    row = _load_entry(
        tmp_path,
        _benchmark_entry(
            "batch_throughput",
            extra_info=_extra_info("batch_throughput", throughput_unit="calls_per_second"),
            stats={"mean": 0.0, "median": 0.0, "min": 0.0},
        ),
    )

    assert math.isnan(cast(float, row.derived["throughput_mean"]))
    assert math.isnan(cast(float, row.derived["throughput_median"]))


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ([1.0], {"p50": 1.0, "p90": 1.0, "p95": 1.0, "p99": 1.0, "max": 1.0}),
        ([1.0, 2.0, 3.0, 4.0, 5.0], {"p50": 3.0, "p90": 4.6, "p95": 4.8, "p99": 4.96, "max": 5.0}),
        ([5.0, 1.0, 3.0, 2.0, 4.0], {"p50": 3.0, "p90": 4.6, "p95": 4.8, "p99": 4.96, "max": 5.0}),
    ],
)
def test_load_benchmark_json_derives_tail_latency_percentiles(
    tmp_path: Path,
    data: list[float],
    expected: dict[str, float],
) -> None:
    row = _load_entry(tmp_path, _benchmark_entry("tail_latency", data=list(data)))

    for key, value in expected.items():
        assert row.derived[key] == pytest.approx(value)


def test_load_benchmark_json_reads_tail_latency_data_from_stats_mapping(tmp_path: Path) -> None:
    row = _load_entry(
        tmp_path,
        _benchmark_entry(
            "tail_latency",
            stats={"mean": 1.0, "median": 1.0, "min": 1.0, "data": [1.0, 2.0, 3.0]},
        ),
    )

    assert row.derived["p50"] == 2.0
    assert row.derived["max"] == 3.0


def test_load_benchmark_json_uses_fullname_fallback_and_stringifies_names(tmp_path: Path) -> None:
    entry = _benchmark_entry("single_call_latency")
    _ = entry.pop("name")
    entry["fullname"] = ["module", "test_name"]

    row = _load_entry(tmp_path, entry)

    assert row.benchmark_name == "['module', 'test_name']"


def test_load_benchmark_json_returns_multiple_rows(tmp_path: Path) -> None:
    payload = {
        "benchmarks": [
            _benchmark_entry("single_call_latency"),
            _benchmark_entry(
                "batch_throughput",
                extra_info=_extra_info("batch_throughput", throughput_unit="calls_per_second"),
            ),
        ]
    }

    rows = load_benchmark_json(_write_payload(tmp_path, payload))

    assert [row.metric_name for row in rows] == ["single_call_latency", "batch_throughput"]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            ParsedBenchmarkRow(
                benchmark_name="bench",
                metric_name="single_call_latency",
                implementation_name="impl",
                case_name="case",
                stats={"mean": 0.0000005, "median": 0.0005, "min": 0.5},
                extra_info={},
                derived={},
            ),
            "[single_call_latency] implementation=impl case=case mean=500.00 ns median=500.00 us min=500.00 ms",
        ),
        (
            ParsedBenchmarkRow(
                benchmark_name="bench",
                metric_name="batch_throughput",
                implementation_name="impl",
                case_name="case",
                stats={},
                extra_info={},
                derived={"throughput_mean": 1234.4, "throughput_median": 2000.0, "throughput_unit_label": "rows/s"},
            ),
            "[batch_throughput] implementation=impl case=case throughput_mean=1,234 "
            + "throughput_median=2,000 unit=rows/s",
        ),
        (
            ParsedBenchmarkRow(
                benchmark_name="bench",
                metric_name="tail_latency",
                implementation_name="impl",
                case_name="case",
                stats={},
                extra_info={},
                derived={"p50": 1.0, "p95": 2.0, "p99": 3.0, "max": 4.0},
            ),
            "[tail_latency] implementation=impl case=case p50=1.000 s p95=2.000 s p99=3.000 s max=4.000 s",
        ),
    ],
)
def test_display_benchmark_row_formats_supported_metrics(row: ParsedBenchmarkRow, expected: str) -> None:
    stream = io.StringIO()

    display_benchmark_row(row, stream=stream)

    assert stream.getvalue().strip() == expected


def test_display_benchmark_row_falls_back_for_unknown_metric() -> None:
    row = ParsedBenchmarkRow(
        benchmark_name="bench",
        metric_name=cast(MetricName, cast(object, "future_metric")),
        implementation_name="impl",
        case_name="case",
        stats={"mean": 2.0},
        extra_info={},
        derived={},
    )
    stream = io.StringIO()

    display_benchmark_row(row, stream=stream)

    assert stream.getvalue().strip() == "[future_metric] implementation=impl case=case mean=2.000 s"


def test_display_benchmark_rows_prints_each_row(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [
        ParsedBenchmarkRow(
            benchmark_name="bench-a",
            metric_name="single_call_latency",
            implementation_name="impl-a",
            case_name="case-a",
            stats={"mean": 1.0, "median": 1.0, "min": 1.0},
            extra_info={},
            derived={},
        ),
        ParsedBenchmarkRow(
            benchmark_name="bench-b",
            metric_name="single_call_latency",
            implementation_name="impl-b",
            case_name="case-b",
            stats={"mean": object(), "median": None, "min": "bad"},
            extra_info={},
            derived={},
        ),
    ]

    display_benchmark_rows(rows)

    output = capsys.readouterr().out
    assert "[single_call_latency] implementation=impl-a case=case-a mean=1.000 s" in output
    assert "[single_call_latency] implementation=impl-b case=case-b mean=nan median=nan min=nan" in output


def test_load_benchmark_json_wraps_file_errors(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkJsonError, match="Could not read benchmark JSON"):
        _ = load_benchmark_json(tmp_path / "missing.json")


def test_load_benchmark_json_wraps_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    _ = path.write_text("{not json", encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match="Invalid JSON"):
        _ = load_benchmark_json(path)


INVALID_PAYLOAD_CASES: list[tuple[object, str]] = [
    ([], "Expected mapping at root"),
    ({}, "Expected list at root.benchmarks"),
    ({"benchmarks": {}}, "Expected list at root.benchmarks"),
    ({"benchmarks": [None]}, "Expected mapping at root.benchmarks\\[0\\]"),
    ({"benchmarks": [{"extra_info": {}, "stats": {}}]}, "Expected string at root.benchmarks\\[0\\].extra_info"),
    (
        {
            "benchmarks": [
                _benchmark_entry(
                    "single_call_latency",
                    extra_info={
                        "benchkit_producer": "other",
                        "benchkit_schema_version": 1,
                        "metric_name": "single_call_latency",
                        "implementation_name": "impl",
                        "case_name": "case",
                    },
                )
            ]
        },
        "Unsupported benchmark producer",
    ),
    (
        {
            "benchmarks": [
                _benchmark_entry(
                    "single_call_latency",
                    extra_info={
                        "benchkit_producer": "benchkit",
                        "benchkit_schema_version": 2,
                        "metric_name": "single_call_latency",
                        "implementation_name": "impl",
                        "case_name": "case",
                    },
                )
            ]
        },
        "Unsupported benchkit schema version",
    ),
    (
        {
            "benchmarks": [
                _benchmark_entry(
                    "unknown",
                    extra_info=_extra_info("unknown"),
                )
            ]
        },
        "Unsupported benchkit metric",
    ),
    (
        {
            "benchmarks": [
                _benchmark_entry(
                    "single_call_latency",
                    stats={"mean": "bad", "median": 1.0, "min": 1.0},
                )
            ]
        },
        "Expected finite numeric value at stats.mean",
    ),
    (
        {
            "benchmarks": [
                _benchmark_entry(
                    "batch_throughput",
                    extra_info=_extra_info("batch_throughput", throughput_unit="unknown"),
                )
            ]
        },
        "Unsupported throughput unit",
    ),
    (
        {
            "benchmarks": [
                _benchmark_entry(
                    "batch_throughput",
                    extra_info=_extra_info("batch_throughput", throughput_unit="work_units_per_second"),
                )
            ]
        },
        "Expected finite numeric value at extra_info.work_units",
    ),
    (
        {
            "benchmarks": [
                _benchmark_entry(
                    "tail_latency",
                )
            ]
        },
        "does not contain raw sample data",
    ),
    (
        {
            "benchmarks": [
                _benchmark_entry(
                    "tail_latency",
                    data=[1.0, "bad"],
                )
            ]
        },
        "Expected finite numeric value at root.benchmarks\\[0\\].data\\[1\\]",
    ),
]


@pytest.mark.parametrize(("payload", "message"), INVALID_PAYLOAD_CASES)
def test_load_benchmark_json_rejects_invalid_structures(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    path = _write_payload(tmp_path, payload)

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_benchmark_json(path)
