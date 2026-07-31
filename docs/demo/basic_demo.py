import os

from benchmatrix import BenchmarkCase, make_benchmark_test


def builtin_sum(values: list[int]) -> int:
    return sum(values)


def loop_sum(values: list[int]) -> int:
    result = 0
    for value in values:
        result += value

    if os.environ.get("BENCHMATRIX_DEMO_SLOWDOWN"):
        # busy work to simulate a slow implementation
        for index in range(0, len(values), 8):
            result += values[index]
            result -= values[index]

    return result


implementations = {
    "builtin": builtin_sum,
    "loop": loop_sum,
}

cases = [
    BenchmarkCase.from_values("small", list(range(10_000))),
    BenchmarkCase.from_values("large", list(range(100_000))),
]

test_demo_matrix = make_benchmark_test(
    implementations,
    cases,
    metrics=("single_call_latency",),
)
