"""Property-based tests for benchmark metadata and result parsing."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from benchmatrix import BenchmarkCase, load_benchmark_json

_JSON_SCALARS = st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text()
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(min_size=1, max_size=12), children, max_size=5)
    ),
    max_leaves=20,
)
_METADATA = st.dictionaries(st.text(min_size=1, max_size=12), _JSON_VALUES, max_size=8)
_TAIL_SAMPLES = st.lists(
    st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=30,
)


def _tail_payload(samples: list[float]) -> dict[str, object]:
    """Return a tail-latency payload using the provided samples."""
    return {
        "benchmarks": [
            {
                "name": "tests/test_properties.py::test_tail_latency",
                "extra_info": {
                    "benchmatrix_producer": "benchmatrix",
                    "benchmatrix_schema_version": 1,
                    "metric_name": "tail_latency",
                    "implementation_name": "impl",
                    "case_name": "case",
                    "case_fresh_inputs": False,
                },
                "stats": {"mean": samples[0], "median": samples[0], "min": min(samples)},
                "data": samples,
            }
        ]
    }


def _write_json(path: Path, payload: object) -> None:
    """Write JSON to a path."""
    _ = path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.property
@settings(max_examples=100)
@given(metadata=_METADATA)
def test_json_safe_metadata_round_trips_through_benchmark_case(metadata: dict[str, object]) -> None:
    case = BenchmarkCase("property", metadata=metadata)

    assert case.metadata == metadata
    _ = json.dumps(case.metadata, allow_nan=False)


@pytest.mark.property
@settings(max_examples=100)
@given(samples=_TAIL_SAMPLES)
def test_tail_latency_percentiles_are_order_invariant_and_bounded(samples: list[float]) -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        path = tmp_path / "tail.json"
        reversed_path = tmp_path / "tail-reversed.json"
        _write_json(path, _tail_payload(samples))
        _write_json(reversed_path, _tail_payload(list(reversed(samples))))

        row = load_benchmark_json(path)[0]
        reversed_row = load_benchmark_json(reversed_path)[0]

    lower_bound = min(samples)
    upper_bound = max(samples)
    tolerance = max(1e-12, abs(upper_bound) * 1e-12)

    for key in ("p50", "p90", "p95", "p99"):
        value = row.derived[key]
        assert isinstance(value, float)
        assert math.isfinite(value)
        assert lower_bound - tolerance <= value <= upper_bound + tolerance
        assert value == pytest.approx(reversed_row.derived[key])

    assert row.derived["max"] == upper_bound
