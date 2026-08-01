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
each sample into a per-round average of multiple calls. That averaging hides
variation between the individual calls in a round.

The default evidence policy requires at least 100 round-duration observations
per run and exactly one target iteration per round for tail-latency inference.
With 100 observations, only about five observations are expected beyond the
population p95. Tail estimates therefore need more care than means even when
the process-run count is adequate.

## Statistical comparison model

benchmatrix treats each separately launched pytest process as one independent
experimental unit. pytest-benchmark rounds inside that process are repeated
measurements under shared process state, not independent replicates of the code
change. Collecting more rounds can improve a run's mean or p95 estimate, but it
does not substitute for collecting more process runs.

For each cell, let `b` be the median of the baseline per-run statistics and `c`
the median of the candidate per-run statistics. The reported direction-aware
improvement estimand is:

```text
higher is better: 100 * (c / b - 1)
lower is better:  100 * (1 - c / b)
```

Positive values always mean improvement. The underlying per-run statistic is
mean latency for `single_call_latency`, mean throughput for
`batch_throughput`, and p95 latency for `tail_latency`.

The default `bca_bootstrap` method resamples complete runs with replacement,
recalculates the estimand 50,000 times, and forms a bias-corrected and
accelerated (BCa) interval. Independent comparisons resample the baseline and
candidate groups separately. Explicit paired comparisons resample complete
matched `(baseline, candidate)` tuples, so shared block-level noise remains in
the analysis. Pairing changes the resampling design, not the estimand above.

The policy seed and matrix-cell identity derive a stable per-cell seed, so
results do not depend on matrix ordering. Paired tuples are sorted within their
declared strata before seeded resampling, which makes the result insensitive to
the order in which complete pairs were supplied without breaking their
matches. Pairing is never inferred from filenames, timestamps, or nearby
collection times. A manifest-backed comparison supplies the recorded AB/BA
orientation as a fixed stratum: resampling preserves each orientation's count,
and the stratified delete-one jackknife supplies the BCa acceleration. A
low-level paired comparison without strata remains available, but its inference
contains an explicit exchangeability warning.

The paired bootstrap does not force every resample to retain the exact
matrix-order-row composition. Instead, collection uses a joint supercycle in
which each balanced-order row occurs once under AB and once under BA before
manifest-backed formal inference is allowed. Schedule-row effects can still
contribute pair-to-pair variation, making the interval conservative when that
variation is material.

If the delete-one jackknife needed for BCa is degenerate, benchmatrix reports a
`percentile_bootstrap` fallback using the same run-level bootstrap samples. The
bias correction uses a midrank convention for bootstrap estimates tied with
the observed estimate. Independent acceleration centers and scales delete-one
values separately for the two groups, including unequal group sizes; paired
acceleration deletes one complete pair at a time.

The default family confidence is 95%. For `m` structurally comparable cells,
Bonferroni multiplicity uses a per-cell confidence level of:

```text
1 - (1 - 0.95) / m
```

The family contains environment-compatible cells with matching measurement
context and finite positive run statistics on both sides. It is defined before
evidence outcomes are classified, so excluding a noisy result cannot make the
remaining intervals artificially narrower. Missing or structurally
incompatible cells are not hypotheses in the family and remain explicit
non-comparable results.

## Practical decisions

The regression threshold is a practical-effect boundary, not a significance
level. With threshold `d` and adjusted confidence interval `[L, U]`:

| Interval condition | Classification |
| --- | --- |
| `U < -d` | `regressed` |
| `L > +d` | `improved` |
| `L >= -d` and `U <= +d` | `unchanged` (practically equivalent) |
| Any other placement | `inconclusive` |

This rule deliberately distinguishes equivalence from absence of evidence. A
point estimate inside the practical region is not enough for `unchanged`; the
complete interval must fit inside it. Likewise, a point estimate beyond the
threshold is inconclusive when its interval crosses a boundary.

Selecting `multiplicity = "none"` keeps the configured confidence level for
each cell but provides no matrix-wide error control. Reports label that mode as
exploratory. Selecting `method = "legacy_consistency"` restores the earlier
observed Cartesian pairwise-range rule. That method calculates no formal
confidence interval and must not be interpreted as statistical inference.

## Paired AB/BA design and balanced cell order

`collect_paired_benchmark_runs` collects each target pair as one adjacent
two-command block. Blocks alternate between baseline-first (`AB`) and
candidate-first (`BA`); the configured seed chooses the first orientation.
Baseline and candidate may use different working directories and commits, but
their matrices and environments must remain compatible.

Both members of a pair use the same deterministic Williams-style matrix-cell
order. Across a complete ordering cycle, every cell occupies each ordinal
position equally often. For odd-sized matrices larger than one, a reversed
second cycle also balances directed first-order carryover; the row-cycle length
is `2n` rather than `n`. The collector assigns every row to two consecutive
blocks while continuing to alternate AB/BA, so every row occurs once under each
orientation. This joint supercycle has twice the row-cycle length and prevents
command orientation from being permanently confounded with matrix position.

When no pair target is supplied, the collector learns the matrix from the
first accepted command and chooses the smallest whole joint-supercycle target
that satisfies the default five-pair evidence minimum. If neither command in
the first target pair succeeds, collection stops because it cannot yet build
the row schedule; resume/retry establishes that anchor before later pairs run.
Explicit partial-cycle targets remain useful for exploratory pilots, but the
manifest-backed `compare` path rejects them for formal inference. This design
reduces systematic order, warm-up, and drift confounding; it cannot make an
unstable machine stable.

Pair membership is atomic. Both adjacent commands must succeed within the same
block attempt before either result enters `complete_pairs` or paired inference.
An interrupted block or a block with one failure remains fully auditable, but
an orphan success is excluded. Resume abandons a partially recorded block and
runs a fresh adjacent block. `retry_failed=True` similarly appends one fresh
two-command attempt for each still-incomplete pair; it never joins successes
from different attempts.

## Fixed-design precision planning

Precision planning is optional and available only for explicitly paired pilot
data. For pair `i`, the planner forms a signed log ratio so positive means
improvement:

```text
higher is better: log(c_i / b_i)
lower is better:  log(b_i / c_i)
```

When AB/BA strata are available, let `s` be the pooled within-orientation
residual standard deviation of those log ratios; fixed command-order effects
are not counted as random pair noise. Otherwise, `s` is the ordinary pilot
sample standard deviation and the plan carries an exchangeability warning. The
planner uses `s / sqrt(n)` as the standard error of a **mean signed
paired-log-ratio proxy**. A requested multiplicative percentage width `w`
becomes `h = log1p(w / 100)`. After applying the same Bonferroni
family-confidence adjustment as inference, the planner first finds the
unconstrained `n` satisfying:

```text
t_((1 + adjusted confidence) / 2, n - strata) * s / sqrt(n) <= h
```

This proxy is not the ratio-of-marginal-medians estimand used by the paired BCa
comparison. Its Student-t width therefore does not estimate or guarantee the
future BCa interval width or a fixed number of percentage points around a
nonzero effect; it is a transparent heuristic for selecting a fixed design
size. The final `required_pairs` is at least the active evidence-policy minimum
and is rounded up to a complete paired-design multiple. The unrounded
statistical result remains available as `unconstrained_required_pairs`.

The calculation assumes independent pairs, stable within-stratum log-ratio
variability, and a pilot representative of the future experiment. Pilot
variance is plugged in rather than bounded by an assurance calculation, so
small pilots remain explicitly provisional. Zero residual variability cannot
support a finite planning claim.

`required_pairs` sizes a **fresh future confirmatory collection** whose total
pair count is fixed before collection starts. `additional_pairs` is only the
arithmetic difference between that count and the pilot size. It does not mean
that adding those runs to the observed pilot restores confirmatory coverage.
The plan is not power analysis, does not guarantee a classification, and must
not be recalculated after each result to create a sequential stopping rule.

## Current limits

The CLI keeps the experimental design explicit: `collect` and `measure`
produce independent groups, while `collect-paired` produces atomic AB/BA
blocks that `compare --paired` preserves. The same distinction is available
through the Python APIs. benchmatrix does not estimate power, collect until a
result becomes conclusive, or provide a sequential-analysis boundary. It also
cannot remove thermal, frequency-scaling, background-load, or long-term drift
effects that remain inside a supposedly controlled block. Fix the design and
sample size before a confirmatory collection and investigate inconclusive
outcomes rather than sampling until they change category.

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
* Correctness and lifecycle hooks run outside the timed target body and wrap a
    complete benchmark entry. They do not run once per calibrated call or
    pedantic round.
* Reused mutable inputs can drift across invocations. Use `fresh_inputs=True`,
    `deep_copy`, or a domain-specific copier when targets mutate their inputs.
* Small differences need independent runs, uncertainty intervals, and
    controlled environments before they become conclusions.
* A result validator prevents invalid matrix entries from passing silently, but
    a faster implementation still needs ordinary correctness tests.
