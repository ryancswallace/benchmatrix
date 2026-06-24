# Examples

These examples are runnable pytest-benchmark benchmark matrices.

## Files

* `test_factorial_benchmarks_simplified.py` uses `make_benchmark_test`. Start
    here when you want benchmatrix to generate the pytest parametrization.
* `test_factorial_benchmarks.py` uses `make_benchmark_parameters` and
    `run_benchmark_metric` directly. Use this shape when you need custom pytest
    behavior around each generated benchmark row.

Both examples benchmark iterative and recursive factorial implementations across
small and medium cases and every supported benchmatrix metric view.

## Run

Create the ignored output directory first:

```bash
mkdir -p examples/benchmark_results
```

Run the generated-test example:

```bash
uv run pytest examples/test_factorial_benchmarks_simplified.py --no-cov \
    --benchmark-json examples/benchmark_results/factorial-benchmark-simple.json
```

Run the explicit-parametrization example:

```bash
uv run pytest examples/test_factorial_benchmarks.py --no-cov \
    --benchmark-json examples/benchmark_results/factorial-benchmark.json
```

`examples/benchmark_results/` is ignored by Git because pytest-benchmark output
is machine-specific.

## Inspect

Parse and print the generated rows:

```bash
uv run python - <<'PY'
from benchmatrix import display_benchmark_rows, load_benchmark_json

rows = load_benchmark_json("examples/benchmark_results/factorial-benchmark-simple.json")
display_benchmark_rows(rows)
PY
```
