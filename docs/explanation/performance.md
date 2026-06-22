# Performance model

benchmatrix reports three views over timings produced by pytest-benchmark. The
views share the same measurement engine but answer different questions.

## Single-call latency

Single-call latency represents one synchronous target invocation. pytest-benchmark
may run calibrated loops internally, but the reported value is normalized to the
target call. Input construction is excluded unless it happens inside the target
function.

## Batch throughput

Batch throughput derives logical work per second from the same target invocation.
Use `work_units` when one call completes multiple comparable units of work, such
as 100 items processed by one function call.

`work_units` must describe completed work for one target call and must be
comparable across implementations. Incorrect counts produce precise-looking but
wrong throughput values.

## Tail latency

Tail latency summarizes local pytest-benchmark timing samples. It derives
p50/p90/p95/p99-style summaries from saved samples so implementations can be
compared by local timing distribution.

Keep `pedantic_iterations=1` for tail-latency comparisons. Higher values turn
each sample into an aggregate round timing rather than a clean one-call sample.

## Guardrails

Do not infer service capacity, saturation throughput, production p95/p99,
queueing behavior, retry behavior, or network reliability from benchmatrix
output. Treat results as local comparative measurements and retain environment
metadata with saved runs.

Common pitfalls:

* A target returning a generator, coroutine, future, query plan, or other lazy
  object may only measure object creation. Resolve lazy work inside the
  synchronous target wrapper.
* Fresh-input factories and copying run outside the timed target body. Put
  construction inside the target only when setup cost is part of the operation
  being measured.
* Reused mutable inputs can drift across invocations. Use `fresh_inputs=True`,
  `deep_copy`, or a domain-specific copier when targets mutate their inputs.
* Small differences need repeated runs, distribution checks, and controlled
  environments before they become conclusions.
* A faster implementation still needs ordinary correctness tests. Benchmark
  tests should not be the only proof that two implementations do the same work.
