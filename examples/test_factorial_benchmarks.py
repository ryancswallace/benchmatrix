"""Explicit benchmatrix matrix built on pytest-benchmark parametrization.

Run from the repository root with:

    mkdir -p examples/benchmark_results
    uv run pytest examples/test_factorial_benchmarks.py --no-cov \
        --benchmark-json examples/benchmark_results/factorial-benchmark.json
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from benchmatrix import (
    BenchmarkCase,
    BenchmarkConfig,
    BenchmarkFixture,
    MetricName,
    make_benchmark_parameters,
    run_benchmark_metric,
)


def factorial_iterative(n: int) -> int:
    """Return n! using a loop."""
    result = 1
    for value in range(2, n + 1):
        result *= value
    return result


def factorial_recursive(n: int) -> int:
    """Return n! using recursion."""
    if n < 2:
        return 1
    return n * factorial_recursive(n - 1)


IMPLEMENTATIONS: dict[str, Callable[[int], int]] = {
    "iterative": factorial_iterative,
    "recursive": factorial_recursive,
}

CASES = [
    BenchmarkCase.from_values("small", 10, work_units=9, work_unit_name="multiplications"),
    BenchmarkCase.from_values("medium", 75, work_units=74, work_unit_name="multiplications"),
]

CONFIG = BenchmarkConfig(
    pedantic_rounds=25,
    warmup_rounds=3,
    pedantic_iterations=1,
)


@pytest.mark.parametrize(
    ("metric_name", "implementation_name", "function", "case_name", "case"),
    make_benchmark_parameters(IMPLEMENTATIONS, CASES),
)
def test_factorial_benchmark_matrix(
    benchmark: BenchmarkFixture,
    metric_name: MetricName,
    implementation_name: str,
    function: Callable[[int], int],
    case_name: str,
    case: BenchmarkCase,
) -> None:
    """Run every supported benchmatrix metric for each implementation and case."""
    _ = run_benchmark_metric(
        benchmark,
        metric_name,
        implementation_name,
        function,
        case_name,
        case,
        config=CONFIG,
    )
