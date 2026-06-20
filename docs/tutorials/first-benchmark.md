# First benchmark

This tutorial creates a small benchmark matrix and writes pytest-benchmark JSON
that benchmatrix can parse later.

## 1. Create a benchmark test file

Create `tests/test_sum_benchmark.py`:

```python
from benchmatrix import BenchmarkCase, make_benchmark_test


def loop_sum(values: list[int]) -> int:
    total = 0
    for value in values:
        total += value
    return total


implementations = {
    "builtin": sum,
    "loop": loop_sum,
}

cases = [
    BenchmarkCase.from_values(
        "small",
        list(range(100)),
        work_units=100,
        work_unit_name="items",
    ),
]

test_sum_matrix = make_benchmark_test(implementations, cases)
```

## 2. Run the benchmark

```bash
uv run pytest tests/test_sum_benchmark.py --benchmark-json benchmark.json
```

pytest-benchmark owns timing, calibration, and JSON export. benchmatrix owns the
benchmark matrix and the metadata that identifies each row.

## 3. Parse the results

```python
from benchmatrix import display_benchmark_rows, load_benchmark_json

rows = load_benchmark_json("benchmark.json")
display_benchmark_rows(rows)
```

## 4. Add another metric

By default, generated tests include the supported metric views. Use the parsed
rows to compare implementations by metric instead of mixing latency and
throughput as if they were the same measurement.

## Checkpoint

You now have:

* one benchmark matrix;
* two implementations;
* one input case;
* JSON output that can be parsed into benchmatrix result objects.

Next, read [Create a benchmark matrix](../how-to/create-benchmark-matrix.md) for
focused examples of fresh inputs and work-unit metadata.
