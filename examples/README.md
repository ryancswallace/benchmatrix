# Examples

These runnable examples compare iterative and recursive factorial
implementations across two input cases. Each file also includes an ordinary
correctness test so a fast but incorrect implementation cannot produce trusted
benchmark evidence.

## Choose an example

* `test_factorial_benchmarks_simplified.py` uses `make_benchmark_test`. Start
    here when benchmatrix should generate the pytest parametrization.
* `test_factorial_benchmarks.py` uses `make_benchmark_parameters` and
    `run_benchmark_metric` directly. Use this form for custom pytest behavior
    around each generated benchmark row.

## Collect repeated runs

From the repository root, collect a baseline with the simplified example:

```bash
uv run benchmatrix measure --runs 3 \
    --output examples/benchmark_results/baseline \
    examples/test_factorial_benchmarks_simplified.py
```

After changing an implementation, collect a candidate and compare it:

```bash
uv run benchmatrix measure --runs 3 \
    --output examples/benchmark_results/candidate \
    examples/test_factorial_benchmarks_simplified.py

uv run benchmatrix compare \
    examples/benchmark_results/baseline \
    examples/benchmark_results/candidate \
    --summary
```

`examples/benchmark_results/` is ignored because benchmark evidence is
machine-specific.

## Export one raw pytest-benchmark file

Direct pytest invocation remains useful when another tool owns collection:

```bash
mkdir -p examples/benchmark_results
uv run pytest examples/test_factorial_benchmarks.py --no-cov \
    --benchmark-json examples/benchmark_results/factorial-benchmark.json
```

Load and print that file through the Python API:

```bash
uv run python - <<'PY'
from benchmatrix import display_benchmark_rows, load_benchmark_json

rows = load_benchmark_json("examples/benchmark_results/factorial-benchmark.json")
display_benchmark_rows(rows)
PY
```
