"""Factorial pytest-benchmark matrix using benchmatrix's generated-test API.

Run from the repository root with:

    uv run pytest examples/test_factorial_benchmarks_simplified.py --no-cov \
        --benchmark-json examples/benchmark_results/factorial-benchmark-simple.json
"""

from __future__ import annotations

from collections.abc import Callable

from benchmatrix import BenchmarkCase, BenchmarkConfig, make_benchmark_test


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
    BenchmarkCase.from_values(
        "small",
        10,
        work_units=9,
        work_unit_name="multiplications",
    ),
    BenchmarkCase.from_values(
        "medium",
        75,
        work_units=74,
        work_unit_name="multiplications",
    ),
]

CONFIG = BenchmarkConfig(
    pedantic_rounds=25,
    warmup_rounds=3,
    pedantic_iterations=1,
)

test_factorial_benchmark_matrix = make_benchmark_test(
    IMPLEMENTATIONS,
    CASES,
    config=CONFIG,
)
