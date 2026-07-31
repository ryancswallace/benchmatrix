"""Build pytest-benchmark matrices and attach benchmatrix metadata.

pytest-benchmark remains the measurement engine and source of truth for
calibration, timing, statistics, reporting, and JSON export. This module
orchestrates metric-by-implementation-by-case matrices, attaches strict
JSON-safe metadata to ``benchmark.extra_info``, and streams lightweight
invocation progress records. Detailed timing statistics should be read from
pytest-benchmark's terminal report, CSV output, saved runs, or JSON output.

Target functions must be synchronous callables that complete the work to be
measured before returning. Async functions are not supported. Lazy return values
such as generators, lazy dataframe expressions, query objects, futures, and
deferred computation graphs are not forced by this harness; if such objects are
returned, the benchmark may measure only object construction.
"""

from __future__ import annotations

import copy
import datetime as dt
import enum
import importlib
import inspect
import json
import math
import re
import sys
import warnings
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Protocol, SupportsFloat, SupportsIndex, TextIO, TypeAlias, TypeVar, cast

from ._schema import (
    DEFAULT_METRICS,
    KEY_CASE_FRESH_INPUTS,
    KEY_CASE_NAME,
    KEY_IMPLEMENTATION_NAME,
    KEY_METRIC_NAME,
    KEY_PRODUCER,
    KEY_SCHEMA_VERSION,
    KEY_TAIL_LATENCY_NOTE,
    KEY_TAIL_PERCENTILES,
    KEY_THROUGHPUT_UNIT,
    KEY_WORK_UNIT_NAME,
    KEY_WORK_UNITS,
    KNOWN_METRICS,
    METRIC_BATCH_THROUGHPUT,
    METRIC_SINGLE_CALL_LATENCY,
    METRIC_TAIL_LATENCY,
    PRODUCER,
    SCHEMA_VERSION,
    TAIL_PERCENTILES,
    THROUGHPUT_UNIT_CALLS_PER_SECOND,
    THROUGHPUT_UNIT_WORK_UNITS_PER_SECOND,
    MetricName,
)
from ._schema import (
    JsonValue as _JsonValue,
)
from .exceptions import MetadataSerializationError

T = TypeVar("T")

TargetFunction: TypeAlias = Callable[..., object]
"""Synchronous callable measured by pytest-benchmark through benchmatrix.

Target functions must perform the work being measured before returning. Async
functions are rejected. Lazy return values are not forced by the harness.
"""

_ExtraInfo: TypeAlias = dict[str, _JsonValue]

_DEFAULT_PEDANTIC_ROUNDS = 100
_DEFAULT_WARMUP_ROUNDS = 10
_DEFAULT_PEDANTIC_ITERATIONS = 1
_DEFAULT_WORK_UNIT_NAME = "items"
_WORK_UNIT_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

_NO_NUMPY_SCALAR = object()


def _empty_args() -> tuple[object, ...]:
    """Return empty positional arguments."""
    return ()


def _empty_kwargs() -> dict[str, object]:
    """Return empty keyword arguments."""
    return {}


def _empty_metadata() -> dict[str, object]:
    """Return empty case metadata."""
    return {}


_RESERVED_CASE_METADATA_KEYS = frozenset({"fresh_inputs", "name"})
_RESERVED_EXTRA_INFO_KEYS = frozenset(
    {
        KEY_CASE_FRESH_INPUTS,
        KEY_CASE_NAME,
        KEY_IMPLEMENTATION_NAME,
        KEY_METRIC_NAME,
        KEY_PRODUCER,
        KEY_SCHEMA_VERSION,
        KEY_TAIL_LATENCY_NOTE,
        KEY_TAIL_PERCENTILES,
        KEY_THROUGHPUT_UNIT,
        KEY_WORK_UNIT_NAME,
        KEY_WORK_UNITS,
    }
)


class BenchmarkFixture(Protocol):
    """pytest-benchmark fixture surface used by benchmatrix.

    Attributes:
        extra_info: Mutable metadata attached to pytest-benchmark output.
    """

    extra_info: MutableMapping[str, object]

    def __call__(self, target: Callable[..., T], *args: object, **kwargs: object) -> T:
        """Benchmark ``target`` with pytest-benchmark automatic calibration."""
        ...

    def pedantic(
        self,
        target: Callable[..., T],
        *,
        args: Sequence[object] | None = None,
        kwargs: Mapping[str, object] | None = None,
        setup: Callable[[], tuple[Sequence[object], Mapping[str, object]]] | None = None,
        teardown: Callable[..., object] | None = None,
        rounds: int = _DEFAULT_PEDANTIC_ROUNDS,
        warmup_rounds: int = _DEFAULT_WARMUP_ROUNDS,
        iterations: int = _DEFAULT_PEDANTIC_ITERATIONS,
    ) -> T:
        """Benchmark ``target`` with pytest-benchmark pedantic mode."""
        ...


class _PytestModule(Protocol):
    """Small surface of pytest used by the harness."""

    mark: _PytestMark

    def param(self, *values: object, id: str | None = None) -> object:
        """Return a pytest parameter value."""
        ...


class _PytestMark(Protocol):
    """Small surface of pytest.mark used by the harness."""

    def parametrize(
        self,
        names: str | Sequence[str],
        values: Iterable[object],
    ) -> Callable[[Callable[..., None]], Callable[..., None]]:
        """Parametrize a pytest test function."""
        ...


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Configuration passed from benchmatrix to pytest-benchmark.

    Args:
        pedantic_rounds: Number of pedantic benchmark rounds to request.
        warmup_rounds: Number of pedantic warmup rounds to request.
        pedantic_iterations: Number of function calls per pedantic round when
            inputs are reused. This value is intentionally ignored when
            ``BenchmarkCase.fresh_inputs`` is true because pytest-benchmark
            setup mode is used to keep input construction outside the timed
            target-function body.
        stream_progress: Whether benchmark helpers should print one progress
            line per benchmark invocation.
        before_benchmark: Optional synchronous hook called immediately before
            pytest-benchmark starts an invocation.
        validate_result: Optional synchronous correctness hook called with the
            result returned by pytest-benchmark. The hook should raise when the
            result is invalid.
        after_benchmark: Optional synchronous hook called after result
            validation, or during cleanup if benchmarking or validation raises.

    Attributes:
        pedantic_rounds: Number of pedantic benchmark rounds to request.
        warmup_rounds: Number of pedantic warmup rounds to request.
        pedantic_iterations: Number of function calls per pedantic round when
            inputs are reused.
        stream_progress: Whether benchmark helpers should print one progress
            line per benchmark invocation.
        before_benchmark: Optional untimed setup hook for a benchmark
            invocation.
        validate_result: Optional untimed correctness hook for the returned
            target result.
        after_benchmark: Optional untimed cleanup hook for a benchmark
            invocation.

    Raises:
        TypeError: If a timing control has the wrong type, progress output is
            not boolean, or a configured hook is not callable or is
            asynchronous.
        ValueError: If rounds or iterations are not positive, or if warmup
            rounds are negative.

    Warning:
        For ``tail_latency`` benchmarks, setting ``pedantic_iterations`` above
        one means raw samples are per-round averages of multiple calls rather
        than individual-call latency samples. The harness emits a runtime
        warning for this configuration.
    """

    pedantic_rounds: int = _DEFAULT_PEDANTIC_ROUNDS
    warmup_rounds: int = _DEFAULT_WARMUP_ROUNDS
    pedantic_iterations: int = _DEFAULT_PEDANTIC_ITERATIONS
    stream_progress: bool = True
    before_benchmark: BenchmarkLifecycleHook | None = None
    validate_result: BenchmarkResultValidator | None = None
    after_benchmark: BenchmarkLifecycleHook | None = None

    def __post_init__(self) -> None:
        """Validate benchmark configuration after initialization."""
        if isinstance(self.pedantic_rounds, bool) or not isinstance(self.pedantic_rounds, int):
            raise TypeError("BenchmarkConfig.pedantic_rounds must be an integer.")
        if self.pedantic_rounds <= 0:
            raise ValueError("BenchmarkConfig.pedantic_rounds must be positive.")

        if isinstance(self.warmup_rounds, bool) or not isinstance(self.warmup_rounds, int):
            raise TypeError("BenchmarkConfig.warmup_rounds must be an integer.")
        if self.warmup_rounds < 0:
            raise ValueError("BenchmarkConfig.warmup_rounds must be non-negative.")

        if isinstance(self.pedantic_iterations, bool) or not isinstance(self.pedantic_iterations, int):
            raise TypeError("BenchmarkConfig.pedantic_iterations must be an integer.")
        if self.pedantic_iterations <= 0:
            raise ValueError("BenchmarkConfig.pedantic_iterations must be positive.")

        if not isinstance(self.stream_progress, bool):
            raise TypeError("BenchmarkConfig.stream_progress must be a boolean.")

        _validate_hook(self.before_benchmark, field="before_benchmark")
        _validate_hook(self.validate_result, field="validate_result")
        _validate_hook(self.after_benchmark, field="after_benchmark")


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """Named input case and metadata for a pytest-benchmark matrix.

    Warning:
        If ``fresh_inputs`` is false, pytest-benchmark may call the target
        function repeatedly with the same argument objects. That is appropriate
        only when the target function treats its inputs as immutable or when
        reuse reflects the workload you want to measure.

        If ``fresh_inputs`` is true, this harness uses pytest-benchmark
        pedantic setup so input construction is setup work rather than timed
        target-function work. That avoids accidentally timing input creation,
        but it also means the benchmark is not an end-to-end measurement that
        includes input construction. To benchmark construction cost, put that
        construction inside the target function itself.

        When ``fresh_inputs`` is true, ``BenchmarkConfig.pedantic_iterations``
        is ignored because pytest-benchmark setup mode is used. The harness
        emits a runtime warning when a non-default value is ignored.

    Args:
        name: Human-readable case name used in parameter IDs and metadata.
        make_args: Factory returning positional arguments for the target
            function.
        make_kwargs: Factory returning keyword arguments for the target
            function.
        work_units: Positive logical amount of work performed by one target
            call. This can represent items, rows, bytes, tokens, records,
            events, or any other domain-specific unit.
        work_unit_name: Name of the logical work unit, such as ``"items"``,
            ``"rows"``, ``"bytes"``, or ``"tokens"``. Use a base unit name
            without spaces, slashes, or ``"/s"``; display code appends ``"/s"``
            for throughput.
        fresh_inputs: Whether each benchmark round needs newly created inputs.
        metadata: Additional strict-JSON-renderable metadata describing the
            case. Reasonable scalar types such as paths, datetimes, enums, and
            NumPy scalars are coerced; unsupported values raise
            ``MetadataSerializationError``.

    Attributes:
        name: Human-readable case name used in parameter IDs and metadata.
        make_args: Factory returning positional arguments for the target
            function.
        make_kwargs: Factory returning keyword arguments for the target
            function.
        work_units: Positive logical amount of work performed by one target
            call.
        work_unit_name: Name of the logical work unit.
        fresh_inputs: Whether each benchmark round needs newly created inputs.
        metadata: Strict JSON-safe metadata describing the case.
    """

    name: str
    make_args: Callable[[], tuple[object, ...]] = _empty_args
    make_kwargs: Callable[[], dict[str, object]] = _empty_kwargs
    work_units: float | Callable[[], float] | None = None
    work_unit_name: str = _DEFAULT_WORK_UNIT_NAME
    fresh_inputs: bool = False
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        """Validate benchmark case fields after initialization."""
        object.__setattr__(self, "name", _validate_name(self.name, field="case name"))

        _validate_case_callable(self.make_args, field="make_args")
        _validate_case_callable(self.make_kwargs, field="make_kwargs")

        object.__setattr__(self, "work_unit_name", _validate_work_unit_name(self.work_unit_name))

        if self.work_units is not None:
            if callable(self.work_units):
                _validate_case_callable(self.work_units, field="work_units")
            else:
                _ = _validate_work_units(self.work_units)

        if not isinstance(self.fresh_inputs, bool):
            raise TypeError("BenchmarkCase.fresh_inputs must be a boolean.")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("BenchmarkCase.metadata must be a mapping.")

        coerced_metadata = _coerce_json_mapping(
            self.metadata,
            path="BenchmarkCase.metadata",
        )
        reserved_metadata = sorted(_RESERVED_CASE_METADATA_KEYS.intersection(coerced_metadata))
        if reserved_metadata:
            formatted = ", ".join(repr(key) for key in reserved_metadata)
            raise ValueError(f"BenchmarkCase.metadata uses reserved key(s): {formatted}.")
        object.__setattr__(self, "metadata", coerced_metadata)

    def make_call(self) -> tuple[tuple[object, ...], dict[str, object]]:
        """Return positional and keyword arguments for one target invocation.

        Returns:
            A tuple containing positional arguments and keyword arguments.
        """
        args = self.make_args()
        if not isinstance(args, tuple):
            raise TypeError("BenchmarkCase.make_args must return a tuple.")

        kwargs = self.make_kwargs()
        if not isinstance(kwargs, dict):
            raise TypeError("BenchmarkCase.make_kwargs must return a dictionary.")
        if any(not isinstance(key, str) for key in kwargs):
            raise TypeError("BenchmarkCase.make_kwargs must return a dictionary with string keys.")

        return args, kwargs

    def work_unit_count(self) -> float | None:
        """Return the logical work-unit count for throughput metrics.

        Returns:
            The logical work-unit count, or ``None`` when the case has no work
            unit count.

        Raises:
            ValueError: If the work-unit count is not positive or finite.
        """
        if self.work_units is None:
            return None

        value = self.work_units() if callable(self.work_units) else self.work_units
        return _validate_work_units(value)

    @classmethod
    def from_values(
        cls,
        name: str,
        *args: object,
        work_units: float | Callable[[], float] | None = None,
        work_unit_name: str = _DEFAULT_WORK_UNIT_NAME,
        fresh_inputs: bool = False,
        copier: Callable[[object], object] | None = None,
        metadata: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> BenchmarkCase:
        """Create a benchmark case from concrete argument values.

        Args:
            name: Case name.
            *args: Positional arguments for the target function.
            work_units: Positive logical amount of work performed by one target
                call.
            work_unit_name: Name of the logical work unit, such as ``"items"``,
                ``"rows"``, ``"bytes"``, or ``"tokens"``. Use a base unit name
                without spaces, slashes, or ``"/s"``.
            fresh_inputs: Whether target invocations need fresh inputs. When
                true and ``copier`` is omitted, a shallow copy is made for each
                argument value.
            copier: Optional copy function applied to each argument value. Use
                ``deep_copy`` or a domain-specific copy function when shallow
                copies are not fresh enough for the benchmarked workload.
            metadata: Optional strict-JSON-renderable case metadata.
            **kwargs: Keyword arguments for the target function.

        Returns:
            A configured benchmark case.
        """

        if not isinstance(fresh_inputs, bool):
            raise TypeError("BenchmarkCase.fresh_inputs must be a boolean.")
        if copier is not None:
            _validate_case_callable(copier, field="copier")

        effective_copier = shallow_copy if fresh_inputs and copier is None else copier

        def make_args() -> tuple[object, ...]:
            """Return case positional arguments."""
            if effective_copier is None:
                return args

            return tuple(effective_copier(arg) for arg in args)

        def make_kwargs() -> dict[str, object]:
            """Return case keyword arguments."""
            if effective_copier is None:
                return dict(kwargs)

            return {key: effective_copier(value) for key, value in kwargs.items()}

        return cls(
            name=name,
            make_args=make_args,
            make_kwargs=make_kwargs,
            work_units=work_units,
            work_unit_name=work_unit_name,
            fresh_inputs=fresh_inputs or effective_copier is not None,
            metadata={} if metadata is None else dict(metadata),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkHookContext:
    """Identity and inputs available to benchmark lifecycle hooks.

    Attributes:
        metric_name: Metric requested for this benchmark invocation.
        implementation_name: Name of the implementation under test.
        case_name: Matrix case name under test.
        function: Synchronous target function under test.
        case: Benchmark case definition used by the invocation.
    """

    metric_name: MetricName
    implementation_name: str
    case_name: str
    function: TargetFunction
    case: BenchmarkCase


BenchmarkLifecycleHook: TypeAlias = Callable[[BenchmarkHookContext], None]
"""Synchronous setup or cleanup hook for one benchmark invocation."""

BenchmarkResultValidator: TypeAlias = Callable[[BenchmarkHookContext, object], None]
"""Synchronous correctness hook for one benchmark invocation result."""


@dataclass(frozen=True, slots=True)
class BenchmarkInvocationRecord:
    """Lightweight record returned after one benchmark invocation.

    This record is not a timing result. Timing results come from
    pytest-benchmark's report, saved runs, CSV output, or JSON output.

    Attributes:
        metric_name: Metric requested for this benchmark invocation.
        implementation_name: Name of the implementation under test.
        case_name: Name of the input case under test.
        extra_info: Strict JSON-safe metadata attached to pytest-benchmark
            output. Values are limited to JSON primitives, lists, and
            string-keyed mappings after metadata coercion. The metadata includes
            benchmatrix producer and schema-version markers.
    """

    metric_name: MetricName
    implementation_name: str
    case_name: str
    extra_info: Mapping[str, object]


def benchmark_single_call_latency(
    benchmark: BenchmarkFixture,
    implementation_name: str,
    function: TargetFunction,
    case_name: str,
    case: BenchmarkCase,
    *,
    config: BenchmarkConfig | None = None,
    stream: TextIO | None = None,
) -> BenchmarkInvocationRecord:
    """Benchmark single-call latency for one implementation and case.

    Args:
        benchmark: Pytest-benchmark fixture instance.
        implementation_name: Name of the implementation under test.
        function: Synchronous function implementation to benchmark. The
            function must complete the measured work before returning.
        case_name: Name of the input case under test.
        case: Benchmark input case.
        config: Benchmark harness configuration. Defaults to
            ``BenchmarkConfig()``.
        stream: Stream used for progress output. Defaults to ``sys.stdout``
            when progress output is enabled.

    Returns:
        A lightweight invocation record containing metadata attached to the
        benchmark. This is not a timing result.

    Raises:
        TypeError: If ``function`` is an async function.

    Warning:
        This measures completed target-function work only. Input construction,
        lazy-result consumption, and other setup are excluded unless they occur
        inside ``function``.
    """
    resolved_config = _resolve_config(config)
    metric_name = METRIC_SINGLE_CALL_LATENCY
    extra_info: dict[str, object] = _make_base_extra_info(
        metric_name,
        implementation_name,
        case_name,
        case,
    )
    final_extra_info = _set_extra_info(benchmark, extra_info)
    _ = _run_target_with_hooks(
        benchmark,
        metric_name,
        implementation_name,
        function,
        case_name,
        case,
        config=resolved_config,
        force_pedantic=False,
    )

    record = BenchmarkInvocationRecord(
        metric_name=metric_name,
        implementation_name=implementation_name,
        case_name=case_name,
        extra_info=final_extra_info,
    )
    _maybe_display_invocation_record(record, config=resolved_config, stream=stream)
    return record


def benchmark_batch_throughput(
    benchmark: BenchmarkFixture,
    implementation_name: str,
    function: TargetFunction,
    case_name: str,
    case: BenchmarkCase,
    *,
    config: BenchmarkConfig | None = None,
    stream: TextIO | None = None,
) -> BenchmarkInvocationRecord:
    """Benchmark batch throughput for one implementation and case.

    Args:
        benchmark: Pytest-benchmark fixture instance.
        implementation_name: Name of the implementation under test.
        function: Synchronous function implementation to benchmark. The
            function must complete the measured work before returning.
        case_name: Name of the input case under test.
        case: Benchmark input case. If ``case.work_units`` is provided,
            throughput is later derived as work units per second; otherwise it
            is derived as calls per second.
        config: Benchmark harness configuration. Defaults to
            ``BenchmarkConfig()``.
        stream: Stream used for progress output. Defaults to ``sys.stdout``
            when progress output is enabled.

    Returns:
        A lightweight invocation record containing metadata attached to the
        benchmark. This is not a timing result.

    Raises:
        TypeError: If ``function`` is an async function.
        ValueError: If ``case.work_units`` is not positive or finite.

    Warning:
        Throughput is derived from one synchronous target invocation. It does
        not model concurrency, saturation, queueing, or service request load.
        ``case.work_units`` must accurately describe work completed by each
        target call.
    """
    resolved_config = _resolve_config(config)
    metric_name = METRIC_BATCH_THROUGHPUT
    extra_info: dict[str, object] = _make_base_extra_info(
        metric_name,
        implementation_name,
        case_name,
        case,
    )
    work_unit_count = case.work_unit_count()

    if work_unit_count is None:
        extra_info[KEY_THROUGHPUT_UNIT] = THROUGHPUT_UNIT_CALLS_PER_SECOND
    else:
        extra_info[KEY_WORK_UNITS] = work_unit_count
        extra_info[KEY_WORK_UNIT_NAME] = case.work_unit_name
        extra_info[KEY_THROUGHPUT_UNIT] = THROUGHPUT_UNIT_WORK_UNITS_PER_SECOND

    final_extra_info = _set_extra_info(benchmark, extra_info)
    _ = _run_target_with_hooks(
        benchmark,
        metric_name,
        implementation_name,
        function,
        case_name,
        case,
        config=resolved_config,
        force_pedantic=False,
    )

    record = BenchmarkInvocationRecord(
        metric_name=metric_name,
        implementation_name=implementation_name,
        case_name=case_name,
        extra_info=final_extra_info,
    )
    _maybe_display_invocation_record(record, config=resolved_config, stream=stream)
    return record


def benchmark_tail_latency(
    benchmark: BenchmarkFixture,
    implementation_name: str,
    function: TargetFunction,
    case_name: str,
    case: BenchmarkCase,
    *,
    config: BenchmarkConfig | None = None,
    stream: TextIO | None = None,
) -> BenchmarkInvocationRecord:
    """Benchmark latency distribution for one implementation and case.

    Args:
        benchmark: Pytest-benchmark fixture instance.
        implementation_name: Name of the implementation under test.
        function: Synchronous function implementation to benchmark. The
            function must complete the measured work before returning.
        case_name: Name of the input case under test.
        case: Benchmark input case.
        config: Benchmark harness configuration. Defaults to
            ``BenchmarkConfig()``.
        stream: Stream used for progress output. Defaults to ``sys.stdout``
            when progress output is enabled.

    Returns:
        A lightweight invocation record containing metadata attached to the
        benchmark. This is not a timing result.

    Raises:
        TypeError: If ``function`` is an async function.

    Warning:
        This uses pedantic mode. Tail percentiles should be calculated from
        pytest-benchmark JSON ``data`` values. This is an
        implementation-comparison metric, not production p95/p99 latency under
        load.

        If ``case.fresh_inputs`` is false and ``config.pedantic_iterations`` is
        greater than one, raw samples are per-round averages of multiple calls,
        not individual-call latency samples. The harness emits a runtime
        warning for that configuration.
    """
    resolved_config = _resolve_config(config)
    metric_name = METRIC_TAIL_LATENCY
    _warn_for_tail_latency_iteration_semantics(case, resolved_config)

    extra_info: dict[str, object] = _make_base_extra_info(
        metric_name,
        implementation_name,
        case_name,
        case,
    )
    extra_info[KEY_TAIL_LATENCY_NOTE] = (
        "Use pytest-benchmark JSON data to compute p50/p90/p95/p99. "
        "This is not production p95/p99 under load. If pedantic_iterations is "
        "greater than one, samples are per-round averages of multiple calls."
    )
    extra_info[KEY_TAIL_PERCENTILES] = list(TAIL_PERCENTILES)

    final_extra_info = _set_extra_info(benchmark, extra_info)
    _ = _run_target_with_hooks(
        benchmark,
        metric_name,
        implementation_name,
        function,
        case_name,
        case,
        config=resolved_config,
        force_pedantic=True,
    )

    record = BenchmarkInvocationRecord(
        metric_name=metric_name,
        implementation_name=implementation_name,
        case_name=case_name,
        extra_info=final_extra_info,
    )
    _maybe_display_invocation_record(record, config=resolved_config, stream=stream)
    return record


def run_benchmark_metric(
    benchmark: BenchmarkFixture,
    metric_name: MetricName,
    implementation_name: str,
    function: TargetFunction,
    case_name: str,
    case: BenchmarkCase,
    *,
    config: BenchmarkConfig | None = None,
    stream: TextIO | None = None,
) -> BenchmarkInvocationRecord:
    """Run one benchmark metric for one implementation and case.

    Args:
        benchmark: Pytest-benchmark fixture instance.
        metric_name: Metric to benchmark.
        implementation_name: Name of the implementation under test.
        function: Synchronous function implementation to benchmark.
        case_name: Name of the input case under test.
        case: Benchmark input case.
        config: Benchmark harness configuration. Defaults to
            ``BenchmarkConfig()``.
        stream: Stream used for progress output. Defaults to ``sys.stdout``
            when progress output is enabled.

    Returns:
        A lightweight invocation record containing metadata attached to the
        benchmark. This is not a timing result.

    Raises:
        TypeError: If ``function`` is an async function.
        ValueError: If ``metric_name`` is unsupported.
    """
    resolved_config = _resolve_config(config)
    resolved_metric_name = _validate_metric_name(metric_name)

    if resolved_metric_name == METRIC_SINGLE_CALL_LATENCY:
        return benchmark_single_call_latency(
            benchmark,
            implementation_name,
            function,
            case_name,
            case,
            config=resolved_config,
            stream=stream,
        )

    if resolved_metric_name == METRIC_BATCH_THROUGHPUT:
        return benchmark_batch_throughput(
            benchmark,
            implementation_name,
            function,
            case_name,
            case,
            config=resolved_config,
            stream=stream,
        )

    if resolved_metric_name == METRIC_TAIL_LATENCY:
        return benchmark_tail_latency(
            benchmark,
            implementation_name,
            function,
            case_name,
            case,
            config=resolved_config,
            stream=stream,
        )

    raise ValueError(f"Unsupported benchmark metric: {resolved_metric_name!r}")


def make_benchmark_parameters(
    implementations: Mapping[str, TargetFunction],
    cases: Mapping[str, BenchmarkCase] | Iterable[BenchmarkCase],
    *,
    metrics: Iterable[MetricName] | None = None,
) -> list[object]:
    """Create pytest parameters for a metric-by-implementation-by-case matrix.

    Args:
        implementations: Mapping from implementation name to target function.
        cases: Mapping or iterable of benchmark input cases.
        metrics: Metrics to include in the parameter matrix. Defaults to all
            supported benchmatrix metrics.

    Returns:
        A list of values suitable for ``pytest.mark.parametrize``.
    """
    resolved_metrics = _metric_items(metrics)
    implementation_items = _implementation_items(implementations)
    case_items = _case_items(cases)
    pytest = _load_pytest()
    parameters: list[object] = []

    for metric_name in resolved_metrics:
        for implementation_name, function in implementation_items:
            for case_name, case in case_items:
                parameters.append(
                    pytest.param(
                        metric_name,
                        implementation_name,
                        function,
                        case_name,
                        case,
                        id=f"{metric_name}::{implementation_name}::{case_name}",
                    )
                )

    return parameters


def make_benchmark_test(
    implementations: Mapping[str, TargetFunction],
    cases: Mapping[str, BenchmarkCase] | Iterable[BenchmarkCase],
    *,
    metrics: Iterable[MetricName] | None = None,
    config: BenchmarkConfig | None = None,
) -> Callable[..., None]:
    """Create a pytest test function for a complete benchmark matrix.

    Assign the returned function to a module-level name beginning with
    ``test_`` so pytest collects it.

    Args:
        implementations: Mapping from implementation name to target function.
        cases: Mapping or iterable of benchmark input cases.
        metrics: Metrics to include in the parameter matrix. Defaults to all
            supported benchmatrix metrics.
        config: Benchmark harness configuration. Defaults to
            ``BenchmarkConfig()``.

    Returns:
        A parametrized pytest test function ready for module-level assignment.
    """
    resolved_config = _resolve_config(config)
    parameters = make_benchmark_parameters(implementations, cases, metrics=metrics)

    def benchmark_test(
        benchmark: BenchmarkFixture,
        metric_name: MetricName,
        implementation_name: str,
        function: TargetFunction,
        case_name: str,
        case: BenchmarkCase,
    ) -> None:
        """Run one entry in the generated benchmark matrix."""
        _ = run_benchmark_metric(
            benchmark,
            metric_name,
            implementation_name,
            function,
            case_name,
            case,
            config=resolved_config,
        )

    pytest = _load_pytest()
    return pytest.mark.parametrize(
        ("metric_name", "implementation_name", "function", "case_name", "case"),
        parameters,
    )(benchmark_test)


def shallow_copy(value: object) -> object:
    """Return a shallow copy of ``value``.

    Args:
        value: Value to copy.

    Returns:
        A shallow copy of ``value``.
    """
    return copy.copy(value)


def deep_copy(value: object) -> object:
    """Return a deep copy of ``value``.

    Args:
        value: Value to copy.

    Returns:
        A deep copy of ``value``.
    """
    return copy.deepcopy(value)


def _resolve_config(config: BenchmarkConfig | None) -> BenchmarkConfig:
    """Return the supplied config or a default config."""
    return BenchmarkConfig() if config is None else config


def _load_pytest() -> _PytestModule:
    """Import pytest at runtime."""
    module = cast(object, importlib.import_module("pytest"))
    return cast(_PytestModule, module)


def _run_target_with_hooks(
    benchmark: BenchmarkFixture,
    metric_name: MetricName,
    implementation_name: str,
    function: TargetFunction,
    case_name: str,
    case: BenchmarkCase,
    *,
    config: BenchmarkConfig,
    force_pedantic: bool,
) -> object:
    """Run one target with untimed correctness and lifecycle hooks."""
    context = BenchmarkHookContext(
        metric_name=metric_name,
        implementation_name=implementation_name,
        case_name=case_name,
        function=function,
        case=case,
    )
    lifecycle_started = config.before_benchmark is None

    if config.before_benchmark is not None:
        config.before_benchmark(context)
        lifecycle_started = True

    try:
        result = _run_target(
            benchmark,
            function,
            case,
            config=config,
            force_pedantic=force_pedantic,
        )
        if config.validate_result is not None:
            config.validate_result(context, result)
        return result
    finally:
        if lifecycle_started and config.after_benchmark is not None:
            config.after_benchmark(context)


def _run_target(
    benchmark: BenchmarkFixture,
    function: TargetFunction,
    case: BenchmarkCase,
    *,
    config: BenchmarkConfig,
    force_pedantic: bool,
) -> object:
    """Run one target function through pytest-benchmark."""
    _validate_target_function(function)

    use_pedantic = force_pedantic or case.fresh_inputs

    if not use_pedantic:
        args, kwargs = case.make_call()
        return benchmark(function, *args, **kwargs)

    if case.fresh_inputs:
        _warn_if_pedantic_iterations_ignored(config)
        return benchmark.pedantic(
            function,
            setup=case.make_call,
            rounds=config.pedantic_rounds,
            warmup_rounds=config.warmup_rounds,
        )

    args, kwargs = case.make_call()
    return benchmark.pedantic(
        function,
        args=args,
        kwargs=kwargs,
        rounds=config.pedantic_rounds,
        warmup_rounds=config.warmup_rounds,
        iterations=config.pedantic_iterations,
    )


def _validate_target_function(function: TargetFunction) -> None:
    """Reject unsupported target-function shapes."""
    if inspect.iscoroutinefunction(function) or inspect.iscoroutinefunction(type(function).__call__):
        message = (
            "benchmatrix supports only synchronous target functions; "
            + "async functions would benchmark coroutine creation rather than execution."
        )
        raise TypeError(message)


def _validate_hook(hook: object, *, field: str) -> None:
    """Reject invalid or asynchronous benchmark hooks."""
    if hook is None:
        return

    if not callable(hook):
        raise TypeError(f"BenchmarkConfig.{field} must be callable.")

    if inspect.iscoroutinefunction(hook) or inspect.iscoroutinefunction(type(hook).__call__):
        raise TypeError(f"BenchmarkConfig.{field} must be synchronous.")


def _validate_case_callable(value: object, *, field: str) -> None:
    """Reject invalid or asynchronous benchmark-case callables."""
    if not callable(value):
        raise TypeError(f"BenchmarkCase.{field} must be callable.")

    if inspect.iscoroutinefunction(value) or inspect.iscoroutinefunction(type(value).__call__):
        raise TypeError(f"BenchmarkCase.{field} must be synchronous.")


def _warn_if_pedantic_iterations_ignored(config: BenchmarkConfig) -> None:
    """Warn when pedantic_iterations is ignored for fresh-input cases."""
    if config.pedantic_iterations == _DEFAULT_PEDANTIC_ITERATIONS:
        return

    message = (
        "BenchmarkConfig.pedantic_iterations is ignored when BenchmarkCase.fresh_inputs is true because "
        + "pytest-benchmark setup mode is used to keep input construction outside the timed function body."
    )
    warnings.warn(
        message,
        RuntimeWarning,
        stacklevel=3,
    )


def _warn_for_tail_latency_iteration_semantics(
    case: BenchmarkCase,
    config: BenchmarkConfig,
) -> None:
    """Warn when tail-latency samples are not individual-call samples."""
    if case.fresh_inputs or config.pedantic_iterations == _DEFAULT_PEDANTIC_ITERATIONS:
        return

    message = (
        "tail_latency with pedantic_iterations greater than one produces per-round averages of multiple calls, not "
        + "individual-call latency samples."
    )
    warnings.warn(
        message,
        RuntimeWarning,
        stacklevel=3,
    )


def _validate_work_units(value: object) -> float:
    """Validate and return a positive finite work-unit count."""
    if isinstance(value, bool) or not isinstance(value, str | bytes | bytearray | SupportsFloat | SupportsIndex):
        raise ValueError("Benchmark work_units must be numeric.")

    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Benchmark work_units must be numeric.") from exc

    if not math.isfinite(numeric_value):
        raise ValueError("Benchmark work_units must be finite.")

    if numeric_value <= 0.0:
        raise ValueError("Benchmark work_units must be positive.")

    return numeric_value


def _validate_name(value: object, *, field: str) -> str:
    """Validate and return a non-empty benchmark name field."""
    if not isinstance(value, str):
        raise TypeError(f"Benchmark {field} must be a string.")

    if not value:
        raise ValueError(f"Benchmark {field} must not be empty.")

    return value


def _validate_work_unit_name(value: object) -> str:
    """Validate a throughput work-unit name."""
    if not isinstance(value, str):
        raise TypeError("Benchmark work_unit_name must be a string.")

    if not value:
        raise ValueError("Benchmark work_unit_name must not be empty.")

    if not _WORK_UNIT_NAME_PATTERN.fullmatch(value):
        message = (
            "Benchmark work_unit_name must start with a letter and contain only letters, digits, underscores, or "
            + "hyphens. Use base units such as 'items', 'rows', 'bytes', or 'tokens', not units like 'rows/s'."
        )
        raise ValueError(message)

    return value


def _validate_metric_name(value: object) -> MetricName:
    """Validate and return a supported metric name."""
    if not isinstance(value, str):
        raise TypeError("Benchmark metric name must be a string.")

    if value not in KNOWN_METRICS:
        raise ValueError(f"Unsupported benchmark metric: {value!r}")

    return cast(MetricName, value)


def _make_base_extra_info(
    metric_name: MetricName,
    implementation_name: str,
    case_name: str,
    case: BenchmarkCase,
) -> dict[str, object]:
    """Build raw metadata common to every benchmark metric."""
    resolved_metric_name = _validate_metric_name(metric_name)
    resolved_implementation_name = _validate_name(implementation_name, field="implementation name")
    resolved_case_name = _validate_name(case_name, field="case name")

    extra_info: dict[str, object] = {
        KEY_PRODUCER: PRODUCER,
        KEY_SCHEMA_VERSION: SCHEMA_VERSION,
        KEY_METRIC_NAME: resolved_metric_name,
        KEY_IMPLEMENTATION_NAME: resolved_implementation_name,
        KEY_CASE_NAME: resolved_case_name,
        KEY_CASE_FRESH_INPUTS: case.fresh_inputs,
    }

    for key, value in case.metadata.items():
        extra_info[f"case_{key}"] = value

    return extra_info


def _set_extra_info(
    benchmark: BenchmarkFixture,
    extra_info: Mapping[str, object],
) -> _ExtraInfo:
    """Validate, attach, and return strict JSON-safe benchmark metadata."""
    retained_extra_info = {
        key: value
        for key, value in benchmark.extra_info.items()
        if key not in _RESERVED_EXTRA_INFO_KEYS and not key.startswith("case_")
    }
    retained_extra_info.update(extra_info)
    final_extra_info = _coerce_json_mapping(retained_extra_info, path="extra_info")
    benchmark.extra_info.clear()
    benchmark.extra_info.update(final_extra_info)
    return final_extra_info


def _maybe_display_invocation_record(
    record: BenchmarkInvocationRecord,
    *,
    config: BenchmarkConfig,
    stream: TextIO | None,
) -> None:
    """Display a progress record when streaming is enabled."""
    if config.stream_progress:
        _display_invocation_record(record, stream=stream)


def _display_invocation_record(
    record: BenchmarkInvocationRecord,
    stream: TextIO | None = None,
) -> None:
    """Print one lightweight benchmark invocation progress record."""
    output = sys.stdout if stream is None else stream
    message = (
        f"[benchmark invoked] metric={record.metric_name} "
        + f"implementation={record.implementation_name} case={record.case_name}; "
        + "timing is available in pytest-benchmark output"
    )
    print(message, file=output, flush=True)


def _case_items(
    cases: Mapping[str, BenchmarkCase] | Iterable[BenchmarkCase],
) -> list[tuple[str, BenchmarkCase]]:
    """Normalize case inputs into named case pairs."""
    if isinstance(cases, Mapping):
        mapping = cast(Mapping[str, BenchmarkCase], cases)
        case_items = list(mapping.items())
        if not case_items:
            raise ValueError("Benchmark cases must not be empty.")

        return [
            (_validate_name(case_name, field="case name"), _validate_case(case, label=case_name))
            for case_name, case in case_items
        ]

    resolved_cases = list(cases)
    if not resolved_cases:
        raise ValueError("Benchmark cases must not be empty.")

    resolved_items: list[tuple[str, BenchmarkCase]] = []
    for case in resolved_cases:
        resolved_case = _validate_case(case)
        resolved_items.append((_validate_name(resolved_case.name, field="case name"), resolved_case))

    duplicate_names = _duplicate_strings(name for name, _case in resolved_items)
    if duplicate_names:
        formatted = ", ".join(repr(name) for name in duplicate_names)
        raise ValueError(f"Benchmark cases must not contain duplicate names: {formatted}.")

    return resolved_items


def _implementation_items(implementations: Mapping[str, TargetFunction]) -> list[tuple[str, TargetFunction]]:
    """Normalize implementation inputs into named function pairs."""
    implementation_items = list(implementations.items())
    if not implementation_items:
        raise ValueError("Benchmark implementations must not be empty.")

    resolved_items: list[tuple[str, TargetFunction]] = []
    for implementation_name, function in implementation_items:
        resolved_name = _validate_name(implementation_name, field="implementation name")
        if not callable(function):
            raise TypeError(f"Benchmark implementation {resolved_name!r} must be callable.")

        resolved_items.append((resolved_name, function))

    return resolved_items


def _metric_items(metrics: Iterable[MetricName] | None) -> tuple[MetricName, ...]:
    """Normalize metric inputs into supported metric names."""
    resolved_metrics: tuple[MetricName, ...]
    if metrics is None:
        resolved_metrics = DEFAULT_METRICS
    else:
        resolved_metrics = tuple(_validate_metric_name(metric) for metric in metrics)

    if not resolved_metrics:
        raise ValueError("Benchmark metrics must not be empty.")

    duplicate_metrics = _duplicate_strings(resolved_metrics)
    if duplicate_metrics:
        formatted = ", ".join(repr(metric) for metric in duplicate_metrics)
        raise ValueError(f"Benchmark metrics must not contain duplicates: {formatted}.")

    return resolved_metrics


def _duplicate_strings(values: Iterable[str]) -> tuple[str, ...]:
    """Return duplicate strings once, preserving first duplicate order."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


def _validate_case(case: object, *, label: object | None = None) -> BenchmarkCase:
    """Validate and return a benchmark case."""
    if isinstance(case, BenchmarkCase):
        return case

    if label is None:
        raise TypeError("Benchmark cases must contain BenchmarkCase instances.")

    raise TypeError(f"Benchmark case {label!r} must be a BenchmarkCase instance.")


def _coerce_json_mapping(
    mapping: Mapping[str, object] | Mapping[object, object],
    *,
    path: str,
) -> _ExtraInfo:
    """Coerce a mapping to strict JSON-safe metadata."""
    output: _ExtraInfo = {}

    for key, value in mapping.items():
        if not isinstance(key, str):
            raise MetadataSerializationError(f"Metadata key at {path} must be str, got {type(key).__name__}.")

        output[key] = _coerce_json_value(value, path=f"{path}.{key}")

    _validate_strict_json(output, path=path)
    return output


def _coerce_json_value(value: object, *, path: str) -> _JsonValue:
    """Coerce a value to strict JSON or raise a serialization error."""
    if value is None or isinstance(value, str | bool):
        return value

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    if isinstance(value, float):
        if math.isfinite(value):
            return value

        raise MetadataSerializationError(f"Metadata value at {path} must be finite, got {value!r}.")

    if isinstance(value, PurePath):
        return str(value)

    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()

    if isinstance(value, enum.Enum):
        enum_value = cast(object, value.value)
        return _coerce_json_value(enum_value, path=f"{path}.value")

    if isinstance(value, list | tuple):
        sequence = cast(Sequence[object], value)
        return [_coerce_json_value(item, path=f"{path}[{index}]") for index, item in enumerate(sequence)]

    if isinstance(value, Mapping):
        return _coerce_json_mapping(cast(Mapping[object, object], value), path=path)

    numpy_scalar = _maybe_numpy_scalar_to_python(value, path=path)
    if numpy_scalar is not _NO_NUMPY_SCALAR:
        return _coerce_json_value(numpy_scalar, path=path)

    raise MetadataSerializationError(
        f"Metadata value at {path} has unsupported type {type(value).__module__}.{type(value).__qualname__}."
    )


def _maybe_numpy_scalar_to_python(value: object, *, path: str) -> object:
    """Return a Python scalar for NumPy scalar values."""
    value_type = type(value)
    module_name = value_type.__module__

    if not module_name.startswith("numpy"):
        return _NO_NUMPY_SCALAR

    if value_type.__name__ == "ndarray":
        message = (
            f"Metadata value at {path} is a NumPy array, not a NumPy scalar. "
            + "Convert arrays to JSON-safe lists explicitly."
        )
        raise MetadataSerializationError(message)

    item = getattr(value, "item", None)
    if not callable(item):
        return _NO_NUMPY_SCALAR

    try:
        scalar = item()
    except Exception as exc:
        raise MetadataSerializationError(
            f"Metadata value at {path} looks NumPy-like but could not be converted to a Python scalar."
        ) from exc

    if scalar is value:
        return _NO_NUMPY_SCALAR

    return scalar


def _validate_strict_json(value: _JsonValue, *, path: str) -> None:
    """Validate that a coerced value can be serialized as strict JSON."""
    try:
        _ = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MetadataSerializationError(f"Metadata at {path} could not be serialized as strict JSON.") from exc
