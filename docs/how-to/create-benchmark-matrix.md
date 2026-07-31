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

## Validate every implementation result

Use an untimed result validator to reject benchmark entries that do not match a
reference implementation:

```python
from benchmatrix import BenchmarkConfig, BenchmarkHookContext


def validate_sum(context: BenchmarkHookContext, result: object) -> None:
    args, kwargs = context.case.make_call()
    expected = sum(*args, **kwargs)
    if result != expected:
        raise AssertionError(f"{context.implementation_name} returned {result!r}; expected {expected!r}")


config = BenchmarkConfig(validate_result=validate_sum)
test_sum_matrix = make_benchmark_test(
    implementations,
    cases,
    config=config,
)
```

The validator receives the result returned by pytest-benchmark after timing, so
the validation itself is not measured. One shared validator applies the same
reference behavior to every metric, implementation, and case. If the validator
raises, the benchmark test fails and its performance result should not be
trusted.

When an implementation mutates inputs, use `fresh_inputs=True` so the reference
call receives independent values. Keep ordinary unit tests too: an untimed
benchmark validator is a guardrail for the matrix, not a replacement for a
focused correctness suite.

## Prepare and clean up benchmark resources

Configure lifecycle hooks for resources that should exist for the whole
pytest-benchmark invocation:

```python
from benchmatrix import BenchmarkConfig, BenchmarkHookContext


def open_resources(context: BenchmarkHookContext) -> None:
    resource_pool.open_for(context.case_name)


def close_resources(context: BenchmarkHookContext) -> None:
    resource_pool.close_for(context.case_name)


config = BenchmarkConfig(
    before_benchmark=open_resources,
    after_benchmark=close_resources,
)
```

Both hooks run outside pytest-benchmark's timed target body.
`after_benchmark` runs when the target or validator raises, provided
`before_benchmark` completed successfully. If setup itself raises, cleanup is
not called.

Lifecycle hooks wrap the complete benchmark entry, not each calibrated call or
pedantic round. Use `fresh_inputs=True` for per-round input reconstruction.
