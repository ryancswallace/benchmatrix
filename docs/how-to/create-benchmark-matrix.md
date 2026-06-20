# Create a benchmark matrix

Use a benchmark matrix when the same operation should be compared across
multiple implementations, inputs, or metric views.

## Compare implementations

```python
from benchmatrix import BenchmarkCase, make_benchmark_test

implementations = {
    "builtin": sum,
    "generator": lambda values: sum(value for value in values),
}

cases = [BenchmarkCase.from_values("small", list(range(100)))]

test_sum_matrix = make_benchmark_test(implementations, cases)
```

## Add work units for throughput

Use work units when one target call performs more than one logical operation.

```python
BenchmarkCase.from_values(
    "one-hundred-items",
    list(range(100)),
    work_units=100,
    work_unit_name="items",
)
```

The work-unit count must describe completed work for one target call and must be
comparable across implementations.

## Protect mutated inputs

If a target mutates its inputs, ask benchmatrix to rebuild inputs outside the
timed target body:

```python
BenchmarkCase.from_values(
    "mutable-list",
    [3, 2, 1],
    fresh_inputs=True,
)
```

Use a custom copier when shallow copying is not enough for nested state.

## Keep benchmark targets synchronous

benchmatrix intentionally targets synchronous callables. If an implementation
returns a coroutine, future, generator, query plan, or other lazy object, resolve
or consume it inside a synchronous wrapper so the benchmark measures completed
work.

## Validate correctness separately

Benchmark tests should not be the only correctness signal. Add ordinary unit
tests that compare implementation outputs before relying on performance data.
