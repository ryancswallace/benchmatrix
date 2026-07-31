# First benchmark

This tutorial builds a small benchmark matrix, introduces a deliberate
regression, and compares repeated baseline and candidate runs.

## 1. Install benchmatrix

Add benchmatrix as a development dependency:

```bash
uv add --dev benchmatrix
```

The examples below assume commands run from the project root.

## 2. Create a benchmark matrix

Create `tests/test_sum_benchmark.py`:

```python
from collections.abc import Callable

from benchmatrix import BenchmarkCase, make_benchmark_test


def loop_sum(values: list[int]) -> int:
    total = 0
    for value in values:
        total += value
    return total


implementations: dict[str, Callable[[list[int]], int]] = {
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


def test_implementations_agree() -> None:
    values = list(range(100))
    expected = sum(values)
    assert all(function(values) == expected for function in implementations.values())


test_sum_matrix = make_benchmark_test(implementations, cases)
```

The ordinary test protects correctness. The generated benchmark test measures
every implementation, case, and selected metric combination.

## 3. Collect a baseline

Measure the current code three times:

```bash
uv run benchmatrix measure --runs 3 --output baseline \
    tests/test_sum_benchmark.py
```

`measure` invokes pytest with benchmark-friendly defaults and writes three JSON
files plus `baseline/benchmatrix-manifest.json`. pytest-benchmark still owns
timing and calibration.

## 4. Introduce a regression

Temporarily replace `loop_sum` with this deliberately slower version:

```python
def loop_sum(values: list[int]) -> int:
    total = 0
    for value in values:
        total += value

    for _ in range(20):
        for value in values:
            total += value
            total -= value

    return total
```

The correctness test still passes, but the implementation now performs much
more work.

Collect the candidate runs:

```bash
uv run benchmatrix measure --runs 3 --output candidate \
    tests/test_sum_benchmark.py
```

## 5. Compare baseline and candidate

```bash
uv run benchmatrix compare baseline candidate --threshold 5% --summary
```

The exact percentages depend on the machine. The `loop` cells should be marked
`regressed`; unaffected cells may be `unchanged` or `inconclusive` when repeated
runs disagree. Inconclusive means the available measurements do not support a
confident decision—it is not silently treated as a pass or a regression.

Add `--fail-on-regression` when the comparison should act as a local or CI gate:

```bash
uv run benchmatrix compare baseline candidate \
    --threshold 5% \
    --fail-on-regression
```

The command exits `1` for a regression, inadequate evidence, an incomplete
matrix, or a blocking environment difference.

In GitHub Actions, add `--github-summary` to publish the same decision in the
job summary.

## 6. Load a saved run from Python

The CLI is the shortest comparison path. Use the Python API when building a
custom report or analysis:

```python
from benchmatrix import load_benchmark_run

run = load_benchmark_run("baseline/run-001.json")

print(run.implementations)
print(run.cases)
print(run.metrics)
print(run.metadata.get("machine_info"))
```

## Checkpoint

You now have:

* a correctness-checked benchmark matrix;
* three baseline and three candidate runs;
* manifests recording the commands, environments, and collection lifecycle;
* a matrix-aware regression decision suitable for local use or CI.

Next, read [Create a benchmark matrix](../how-to/create-benchmark-matrix.md) for
fresh inputs, lifecycle hooks, and result validation, or
[Gate regressions in GitHub Actions](../how-to/github-actions.md) to automate
the comparison.
