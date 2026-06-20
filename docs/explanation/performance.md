# Performance model

benchmatrix reports three views over timings produced by pytest-benchmark.

## Single-call latency

Single-call latency represents one synchronous target invocation. pytest-benchmark
may run calibrated loops internally, but the reported value is normalized to the
target call.

## Batch throughput

Batch throughput derives logical work per second from the same target invocation.
Use `work_units` when one call completes multiple items of work.

## Tail latency

Tail latency summarizes local pytest-benchmark timing samples. It is useful for
comparing local distributions, but it is not production p95 or p99 under traffic,
queueing, retries, or network load.

## What not to conclude

Do not infer service capacity, saturation throughput, or production reliability
from benchmatrix output. Treat results as local comparative measurements and
retain environment metadata with saved runs.
