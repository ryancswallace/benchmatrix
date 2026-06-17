"""Utilities for defining pytest-benchmark benchmark matrices.

The module keeps pytest-benchmark as the source of truth for runtime
measurements. Benchmark helpers attach strict JSON-safe metadata to
``benchmark.extra_info`` and stream lightweight invocation progress records.
Detailed timing statistics should be read from pytest-benchmark's terminal
report, CSV output, saved runs, or JSON output.

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
from typing import Protocol, SupportsFloat, SupportsIndex, TextIO, TypeVar, cast

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

type TargetFunction = Callable[..., object]
"""Synchronous function signature accepted by the benchmark harness.

Target functions must perform the work being measured before returning. Async
functions are rejected. Lazy return values are not forced by the harness.
"""

type _BenchmarkParameter = object
type _ExtraInfo = dict[str, _JsonValue]

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


class _BenchmarkFixture(Protocol):
    """Structural type for the pytest-benchmark fixture used internally."""

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

    def param(self, *values: object, id: str | None = None) -> object:
        """Return a pytest parameter value."""
        ...


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Configuration for benchmark execution.

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

    Attributes:
        pedantic_rounds: Number of pedantic benchmark rounds to request.
        warmup_rounds: Number of pedantic warmup rounds to request.
        pedantic_iterations: Number of function calls per pedantic round when
            inputs are reused.
        stream_progress: Whether benchmark helpers should print one progress
            line per benchmark invocation.

    Raises:
        ValueError: If rounds or iterations are not positive, or if warmup
            rounds are negative.

    Warning:
        For ``tail_latency`` benchmarks, setting ``pedantic_iterations`` above
        one means raw samples should be interpreted as per-round aggregate
        timings rather than clean one-call latency samples. The harness emits a
        runtime warning for this configuration.
    """

    pedantic_rounds: int = _DEFAULT_PEDANTIC_ROUNDS
    warmup_rounds: int = _DEFAULT_WARMUP_ROUNDS
    pedantic_iterations: int = _DEFAULT_PEDANTIC_ITERATIONS
    stream_progress: bool = True

    def __post_init__(self) -> None:
        """Validate benchmark configuration after initialization."""
        if self.pedantic_rounds <= 0:
            raise ValueError("BenchmarkConfig.pedantic_rounds must be positive.")

        if self.warmup_rounds < 0:
            raise ValueError("BenchmarkConfig.warmup_rounds must be non-negative.")

        if self.pedantic_iterations <= 0:
            raise ValueError("BenchmarkConfig.pedantic_iterations must be positive.")


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """Input case for benchmarking a target function.

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
    work_unit_name: str = "items"
    fresh_inputs: bool = False
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        """Validate benchmark case fields after initialization."""
        if not self.name:
            raise ValueError("Benchmark case name must not be empty.")

        _validate_work_unit_name(self.work_unit_name)

        if self.work_units is not None and not callable(self.work_units):
            _ = _validate_work_units(self.work_units)

        coerced_metadata = _coerce_json_mapping(
            self.metadata,
            path="BenchmarkCase.metadata",
        )
        object.__setattr__(self, "metadata", coerced_metadata)

    def make_call(self) -> tuple[tuple[object, ...], dict[str, object]]:
        """Return positional and keyword arguments for one target invocation.

        Returns:
            A tuple containing positional arguments and keyword arguments.
        """
        return self.make_args(), self.make_kwargs()

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
        work_unit_name: str = "items",
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
            fresh_inputs: Whether target invocations need fresh inputs.
            copier: Optional copy function applied to each argument value.
            metadata: Optional strict-JSON-renderable case metadata.
            **kwargs: Keyword arguments for the target function.

        Returns:
            A configured benchmark case.
        """

        def make_args() -> tuple[object, ...]:
            """Return case positional arguments."""
            if copier is None:
                return args

            return tuple(copier(arg) for arg in args)

        def make_kwargs() -> dict[str, object]:
            """Return case keyword arguments."""
            if copier is None:
                return dict(kwargs)

            return {key: copier(value) for key, value in kwargs.items()}

        return cls(
            name=name,
            make_args=make_args,
            make_kwargs=make_kwargs,
            work_units=work_units,
            work_unit_name=work_unit_name,
            fresh_inputs=fresh_inputs or copier is not None,
            metadata={} if metadata is None else dict(metadata),
        )


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
            benchkit producer and schema-version markers.
    """

    metric_name: MetricName
    implementation_name: str
    case_name: str
    extra_info: Mapping[str, object]


def benchmark_single_call_latency(
    benchmark: _BenchmarkFixture,
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
    _ = _run_target(benchmark, function, case, config=resolved_config, force_pedantic=False)

    record = BenchmarkInvocationRecord(
        metric_name=metric_name,
        implementation_name=implementation_name,
        case_name=case_name,
        extra_info=final_extra_info,
    )
    _maybe_display_invocation_record(record, config=resolved_config, stream=stream)
    return record


def benchmark_batch_throughput(
    benchmark: _BenchmarkFixture,
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
    _ = _run_target(benchmark, function, case, config=resolved_config, force_pedantic=False)

    record = BenchmarkInvocationRecord(
        metric_name=metric_name,
        implementation_name=implementation_name,
        case_name=case_name,
        extra_info=final_extra_info,
    )
    _maybe_display_invocation_record(record, config=resolved_config, stream=stream)
    return record


def benchmark_tail_latency(
    benchmark: _BenchmarkFixture,
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
        greater than one, raw samples should be interpreted as per-round
        aggregate timings rather than clean one-call latency samples. The
        harness emits a runtime warning for that configuration.
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
        "greater than one, samples may represent per-round aggregate timings."
    )
    extra_info[KEY_TAIL_PERCENTILES] = list(TAIL_PERCENTILES)

    final_extra_info = _set_extra_info(benchmark, extra_info)
    _ = _run_target(benchmark, function, case, config=resolved_config, force_pedantic=True)

    record = BenchmarkInvocationRecord(
        metric_name=metric_name,
        implementation_name=implementation_name,
        case_name=case_name,
        extra_info=final_extra_info,
    )
    _maybe_display_invocation_record(record, config=resolved_config, stream=stream)
    return record


def run_benchmark_metric(
    benchmark: _BenchmarkFixture,
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

    if metric_name == METRIC_SINGLE_CALL_LATENCY:
        return benchmark_single_call_latency(
            benchmark,
            implementation_name,
            function,
            case_name,
            case,
            config=resolved_config,
            stream=stream,
        )

    if metric_name == METRIC_BATCH_THROUGHPUT:
        return benchmark_batch_throughput(
            benchmark,
            implementation_name,
            function,
            case_name,
            case,
            config=resolved_config,
            stream=stream,
        )

    if metric_name == METRIC_TAIL_LATENCY:
        return benchmark_tail_latency(
            benchmark,
            implementation_name,
            function,
            case_name,
            case,
            config=resolved_config,
            stream=stream,
        )

    raise ValueError(f"Unsupported benchmark metric: {metric_name!r}")


def make_benchmark_parameters(
    implementations: Mapping[str, TargetFunction],
    cases: Mapping[str, BenchmarkCase] | Iterable[BenchmarkCase],
    *,
    metrics: Iterable[MetricName] | None = None,
) -> list[_BenchmarkParameter]:
    """Create pytest parameters for a metric-by-implementation-by-case matrix.

    Args:
        implementations: Mapping from implementation name to target function.
        cases: Mapping or iterable of benchmark input cases.
        metrics: Metrics to include in the parameter matrix. Defaults to all
            supported benchkit metrics.

    Returns:
        A list of values suitable for ``pytest.mark.parametrize``.
    """
    resolved_metrics = DEFAULT_METRICS if metrics is None else tuple(metrics)
    case_items = _case_items(cases)
    pytest = _load_pytest()
    parameters: list[_BenchmarkParameter] = []

    for metric_name in resolved_metrics:
        for implementation_name, function in implementations.items():
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


def _run_target(
    benchmark: _BenchmarkFixture,
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
            "benchkit supports only synchronous target functions; async functions would benchmark coroutine creation "
            + "rather than execution."
        )
        raise TypeError(message)


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
    """Warn when tail-latency samples are not clean one-call samples."""
    if case.fresh_inputs or config.pedantic_iterations == _DEFAULT_PEDANTIC_ITERATIONS:
        return

    message = (
        "tail_latency with pedantic_iterations greater than one produces per-round aggregate timing samples, not clean "
        + "one-call latency samples."
    )
    warnings.warn(
        message,
        RuntimeWarning,
        stacklevel=3,
    )


def _validate_work_units(value: object) -> float:
    """Validate and return a positive finite work-unit count."""
    if not isinstance(value, str | bytes | bytearray | SupportsFloat | SupportsIndex):
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


def _validate_work_unit_name(value: str) -> None:
    """Validate a throughput work-unit name."""
    if not value:
        raise ValueError("Benchmark work_unit_name must not be empty.")

    if not _WORK_UNIT_NAME_PATTERN.fullmatch(value):
        message = (
            "Benchmark work_unit_name must start with a letter and contain only letters, digits, underscores, or "
            + "hyphens. Use base units such as 'items', 'rows', 'bytes', or 'tokens', not units like 'rows/s'."
        )
        raise ValueError(message)


def _make_base_extra_info(
    metric_name: MetricName,
    implementation_name: str,
    case_name: str,
    case: BenchmarkCase,
) -> dict[str, object]:
    """Build raw metadata common to every benchmark metric."""
    extra_info: dict[str, object] = {
        KEY_PRODUCER: PRODUCER,
        KEY_SCHEMA_VERSION: SCHEMA_VERSION,
        KEY_METRIC_NAME: metric_name,
        KEY_IMPLEMENTATION_NAME: implementation_name,
        KEY_CASE_NAME: case_name,
        KEY_CASE_FRESH_INPUTS: case.fresh_inputs,
    }

    for key, value in case.metadata.items():
        extra_info[f"case_{key}"] = value

    return extra_info


def _set_extra_info(
    benchmark: _BenchmarkFixture,
    extra_info: Mapping[str, object],
) -> _ExtraInfo:
    """Validate, attach, and return strict JSON-safe benchmark metadata."""
    final_extra_info = _coerce_json_mapping(extra_info, path="extra_info")
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
        return list(mapping.items())

    return [(case.name, case) for case in cases]


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
