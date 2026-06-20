# Troubleshooting

## Benchmarks measure almost no time

Check whether the target returns lazy work such as a generator, coroutine, query
plan, or future. The target must perform the work synchronously before it
returns.

## Results differ between local and CI

Benchmark timings are sensitive to CPU, Python version, dependency versions,
power management, thermal throttling, and background load. Compare results only
within controlled environments and keep pytest-benchmark metadata with saved
runs.

## Throughput values look too good

Confirm `work_units` describes work completed by one target call. Incorrect work
units produce precise-looking but wrong throughput.

## A mutable input benchmark changes over time

Use `fresh_inputs=True` or a custom copier. Fresh-input setup is excluded from
the timed target body, so put construction inside the target only when setup cost
is part of what you want to measure.

## Documentation build fails

Run:

```bash
make docs
```

Then inspect the first MkDocs warning. The docs build runs in strict mode, so a
missing page, broken link, or undocumented API import becomes a failed build.

## CI fails but local checks pass

Run the same commands CI uses:

```bash
make check
make test-matrix
```

If the failure is Python-version-specific, run a single nox session such as
`uv run nox -s tests-3.11`.
