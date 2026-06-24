"""Tests for benchmark harness helpers."""

from __future__ import annotations

import datetime as dt
import enum
import io
import json
import math
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar, cast

import pytest

from benchmatrix import (
    BenchmarkCase,
    BenchmarkConfig,
    BenchmarkInvocationRecord,
    MetadataSerializationError,
    MetricName,
    benchmark_batch_throughput,
    benchmark_single_call_latency,
    benchmark_tail_latency,
    deep_copy,
    make_benchmark_parameters,
    make_benchmark_test,
    run_benchmark_metric,
    shallow_copy,
)

T = TypeVar("T")

pytestmark = pytest.mark.unit


class _MetadataKind(enum.Enum):
    """Sample enum for metadata coercion tests."""

    SAMPLE = "sample"


class _ParameterSet(Protocol):
    """Subset of pytest ParameterSet used by these tests."""

    values: tuple[object, ...]
    id: str | None


class _NumpyModule(Protocol):
    """Tiny NumPy surface used by optional metadata tests."""

    def int64(self, value: object) -> object:
        """Return a NumPy int scalar."""
        ...

    def float64(self, value: object) -> object:
        """Return a NumPy float scalar."""
        ...

    def bool_(self, value: object) -> object:
        """Return a NumPy bool scalar."""
        ...

    def array(self, value: object) -> object:
        """Return a NumPy array."""
        ...


@dataclass(frozen=True, slots=True)
class _AutoCall:
    """Recorded automatic benchmark call."""

    args: tuple[object, ...]
    kwargs: dict[str, object]


@dataclass(frozen=True, slots=True)
class _PedanticCall:
    """Recorded pedantic benchmark call."""

    args: tuple[object, ...]
    kwargs: dict[str, object]
    setup: bool
    teardown: Callable[..., object] | None
    rounds: int
    warmup_rounds: int
    iterations: int


def _empty_extra_info() -> dict[str, object]:
    """Return empty benchmark metadata."""
    return {}


@dataclass
class _RecordingBenchmark:
    """Small fake for the pytest-benchmark fixture."""

    extra_info: MutableMapping[str, object] = field(default_factory=_empty_extra_info)
    calls: list[_AutoCall] = field(default_factory=list)
    pedantic_calls: list[_PedanticCall] = field(default_factory=list)

    def __call__(self, target: Callable[..., T], *args: object, **kwargs: object) -> T:
        """Record an automatic benchmark call and invoke the target."""
        self.calls.append(_AutoCall(args=args, kwargs=kwargs))
        return target(*args, **kwargs)

    def pedantic(
        self,
        target: Callable[..., T],
        *,
        args: Sequence[object] | None = None,
        kwargs: Mapping[str, object] | None = None,
        setup: Callable[[], tuple[Sequence[object], Mapping[str, object]]] | None = None,
        teardown: Callable[..., object] | None = None,
        rounds: int = 100,
        warmup_rounds: int = 10,
        iterations: int = 1,
    ) -> T:
        """Record a pedantic benchmark call and invoke the target once."""
        if setup is None:
            call_args = tuple(args or ())
            call_kwargs = dict(kwargs or {})
        else:
            setup_args, setup_kwargs = setup()
            call_args = tuple(setup_args)
            call_kwargs = dict(setup_kwargs)

        self.pedantic_calls.append(
            _PedanticCall(
                args=call_args,
                kwargs=call_kwargs,
                setup=setup is not None,
                teardown=teardown,
                rounds=rounds,
                warmup_rounds=warmup_rounds,
                iterations=iterations,
            )
        )
        return target(*call_args, **call_kwargs)


def _add(left: int, right: int) -> int:
    """Return a simple target result."""
    return left + right


def _noop(*_args: object, **_kwargs: object) -> None:
    """Do nothing."""


def _identity(value: object) -> object:
    """Return the supplied value."""
    return value


def _parameter_set(value: object) -> _ParameterSet:
    """Cast a pytest parameter object for assertions."""
    return cast(_ParameterSet, value)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("pedantic_rounds", 0, "pedantic_rounds"),
        ("pedantic_rounds", -1, "pedantic_rounds"),
        ("warmup_rounds", -1, "warmup_rounds"),
        ("pedantic_iterations", 0, "pedantic_iterations"),
        ("pedantic_iterations", -1, "pedantic_iterations"),
    ],
)
def test_benchmark_config_rejects_invalid_values(field_name: str, value: int, message: str) -> None:
    constructors: dict[str, Callable[[int], BenchmarkConfig]] = {
        "pedantic_iterations": lambda invalid: BenchmarkConfig(pedantic_iterations=invalid),
        "pedantic_rounds": lambda invalid: BenchmarkConfig(pedantic_rounds=invalid),
        "warmup_rounds": lambda invalid: BenchmarkConfig(warmup_rounds=invalid),
    }

    with pytest.raises(ValueError, match=message):
        _ = constructors[field_name](value)


def test_benchmark_config_accepts_valid_boundary_values() -> None:
    config = BenchmarkConfig(pedantic_rounds=1, warmup_rounds=0, pedantic_iterations=1, stream_progress=False)

    assert config.pedantic_rounds == 1
    assert config.warmup_rounds == 0
    assert config.pedantic_iterations == 1
    assert not config.stream_progress


@pytest.mark.parametrize("name", ["", None, 123])
def test_benchmark_case_rejects_empty_or_non_string_name(name: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _ = BenchmarkCase(cast(str, name))


@pytest.mark.parametrize("work_unit_name", ["", "rows/s", "1rows", "row count", "rows.second"])
def test_benchmark_case_rejects_invalid_work_unit_names(work_unit_name: str) -> None:
    with pytest.raises(ValueError, match="work_unit_name"):
        _ = BenchmarkCase("case", work_unit_name=work_unit_name)


def test_benchmark_case_rejects_non_string_work_unit_name() -> None:
    with pytest.raises(TypeError, match="work_unit_name"):
        _ = BenchmarkCase("case", work_unit_name=cast(str, None))


@pytest.mark.parametrize("work_units", [0, -1, math.inf, -math.inf, math.nan, "bad", object()])
def test_benchmark_case_rejects_invalid_static_work_units(work_units: object) -> None:
    with pytest.raises(ValueError, match="work_units"):
        _ = BenchmarkCase("case", work_units=cast(float, work_units))


@pytest.mark.parametrize("work_units", [1, 2.5, "3"])
def test_benchmark_case_accepts_numeric_static_work_units(work_units: object) -> None:
    case = BenchmarkCase("case", work_units=cast(float, work_units))

    assert case.work_unit_count() == float(cast(str | float | int, work_units))


def test_benchmark_case_validates_dynamic_work_units_each_time() -> None:
    values = iter([2.0, 0.0])
    case = BenchmarkCase("case", work_units=lambda: next(values))

    assert case.work_unit_count() == 2.0
    with pytest.raises(ValueError, match="positive"):
        _ = case.work_unit_count()


def test_benchmark_case_make_call_uses_factories() -> None:
    case = BenchmarkCase(
        "case",
        make_args=lambda: (1, 2),
        make_kwargs=lambda: {"scale": 3},
    )

    assert case.make_call() == ((1, 2), {"scale": 3})


def test_from_values_reuses_values_without_fresh_inputs_or_copier() -> None:
    original = ["seed"]
    case = BenchmarkCase.from_values("mutable", original, mode="fast")

    args, kwargs = case.make_call()

    assert not case.fresh_inputs
    assert args == (original,)
    assert args[0] is original
    assert kwargs == {"mode": "fast"}


def test_from_values_fresh_inputs_shallow_copies_values_by_default() -> None:
    original = ["seed"]
    case = BenchmarkCase.from_values("mutable", original, fresh_inputs=True)

    first_args, _ = case.make_call()
    second_args, _ = case.make_call()

    assert case.fresh_inputs
    assert first_args[0] == original
    assert second_args[0] == original
    assert first_args[0] is not original
    assert second_args[0] is not original
    assert first_args[0] is not second_args[0]


def test_from_values_custom_copier_controls_fresh_inputs() -> None:
    original = [["nested"]]
    case = BenchmarkCase.from_values("nested", original, copier=deep_copy)

    args, _ = case.make_call()
    copied = args[0]

    assert case.fresh_inputs
    assert copied == original
    assert copied is not original
    assert isinstance(copied, list)
    assert copied[0] is not original[0]


def test_shallow_copy_and_deep_copy_have_distinct_nested_behavior() -> None:
    original = [["nested"]]

    shallow = shallow_copy(original)
    deep = deep_copy(original)

    assert shallow == original
    assert deep == original
    assert shallow is not original
    assert deep is not original
    assert isinstance(shallow, list)
    assert isinstance(deep, list)
    assert shallow[0] is original[0]
    assert deep[0] is not original[0]


def test_case_metadata_is_coerced_to_strict_json_values() -> None:
    case = BenchmarkCase(
        "metadata",
        metadata={
            "none": None,
            "string": "value",
            "bool": True,
            "int": 3,
            "float": 1.5,
            "path": Path("input.txt"),
            "created": dt.date(2026, 6, 17),
            "time": dt.time(12, 30, 5),
            "timestamp": dt.datetime(2026, 6, 17, 12, 30, 5),
            "kind": _MetadataKind.SAMPLE,
            "values": (1, 2, 3),
            "nested": {"path": Path("nested.txt")},
        },
    )

    assert case.metadata == {
        "none": None,
        "string": "value",
        "bool": True,
        "int": 3,
        "float": 1.5,
        "path": "input.txt",
        "created": "2026-06-17",
        "time": "12:30:05",
        "timestamp": "2026-06-17T12:30:05",
        "kind": "sample",
        "values": [1, 2, 3],
        "nested": {"path": "nested.txt"},
    }
    _ = json.dumps(case.metadata, allow_nan=False)


@pytest.mark.numpy
def test_case_metadata_supports_numpy_scalars() -> None:
    numpy = cast(_NumpyModule, cast(object, pytest.importorskip("numpy")))

    case = BenchmarkCase(
        "numpy",
        metadata={
            "int": numpy.int64(3),
            "float": numpy.float64(1.5),
            "bool": numpy.bool_(True),
        },
    )

    assert case.metadata == {"int": 3, "float": 1.5, "bool": True}


@pytest.mark.numpy
def test_case_metadata_rejects_numpy_arrays() -> None:
    numpy = cast(_NumpyModule, cast(object, pytest.importorskip("numpy")))

    with pytest.raises(MetadataSerializationError, match="NumPy array"):
        _ = BenchmarkCase("numpy-array", metadata={"array": numpy.array([1, 2, 3])})


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({1: "value"}, "Metadata key"),
        ({"bad": object()}, "unsupported type"),
        ({"bad": math.nan}, "finite"),
        ({"bad": math.inf}, "finite"),
    ],
)
def test_case_metadata_rejects_non_json_safe_values(metadata: Mapping[object, object], message: str) -> None:
    with pytest.raises(MetadataSerializationError, match=message):
        _ = BenchmarkCase("bad-metadata", metadata=cast(Mapping[str, object], metadata))


def test_benchmark_single_call_latency_records_metadata_and_streams_progress() -> None:
    benchmark = _RecordingBenchmark()
    case = BenchmarkCase.from_values("input", 2, 3, metadata={"size": 2})
    stream = io.StringIO()

    record = benchmark_single_call_latency(
        benchmark,
        "impl",
        _add,
        "case-id",
        case,
        config=BenchmarkConfig(stream_progress=True),
        stream=stream,
    )

    assert isinstance(record, BenchmarkInvocationRecord)
    assert record.metric_name == "single_call_latency"
    assert record.extra_info == benchmark.extra_info
    assert record.extra_info["benchmatrix_producer"] == "benchmatrix"
    assert record.extra_info["benchmatrix_schema_version"] == 1
    assert record.extra_info["metric_name"] == "single_call_latency"
    assert record.extra_info["implementation_name"] == "impl"
    assert record.extra_info["case_name"] == "case-id"
    assert record.extra_info["case_size"] == 2
    assert len(benchmark.calls) == 1
    assert benchmark.calls[0] == _AutoCall(args=(2, 3), kwargs={})
    assert "[benchmark invoked] metric=single_call_latency implementation=impl case=case-id" in stream.getvalue()


def test_benchmark_progress_can_be_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    benchmark = _RecordingBenchmark()
    case = BenchmarkCase.from_values("input")

    _ = benchmark_single_call_latency(
        benchmark,
        "impl",
        _noop,
        "case-id",
        case,
        config=BenchmarkConfig(stream_progress=False),
    )

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("case", "expected_extra"),
    [
        (
            BenchmarkCase.from_values("without-work"),
            {"throughput_unit": "calls_per_second"},
        ),
        (
            BenchmarkCase.from_values("with-work", work_units=5.0, work_unit_name="rows"),
            {"throughput_unit": "work_units_per_second", "work_units": 5.0, "work_unit_name": "rows"},
        ),
    ],
)
def test_benchmark_batch_throughput_metadata(case: BenchmarkCase, expected_extra: dict[str, object]) -> None:
    benchmark = _RecordingBenchmark()

    record = benchmark_batch_throughput(
        benchmark,
        "impl",
        _noop,
        case.name,
        case,
        config=BenchmarkConfig(stream_progress=False),
    )

    assert record.metric_name == "batch_throughput"
    for key, value in expected_extra.items():
        assert record.extra_info[key] == value


def test_benchmark_tail_latency_uses_pedantic_mode_and_records_notes() -> None:
    benchmark = _RecordingBenchmark()
    case = BenchmarkCase.from_values("input", 2, 3)

    record = benchmark_tail_latency(
        benchmark,
        "impl",
        _add,
        "case-id",
        case,
        config=BenchmarkConfig(pedantic_rounds=7, warmup_rounds=2, stream_progress=False),
    )

    assert record.metric_name == "tail_latency"
    assert len(benchmark.calls) == 0
    assert len(benchmark.pedantic_calls) == 1
    assert benchmark.pedantic_calls[0].args == (2, 3)
    assert benchmark.pedantic_calls[0].rounds == 7
    assert benchmark.pedantic_calls[0].warmup_rounds == 2
    assert record.extra_info["tail_percentiles"] == [0.5, 0.9, 0.95, 0.99]
    assert "pytest-benchmark JSON data" in cast(str, record.extra_info["tail_latency_note"])


def test_fresh_input_cases_use_pedantic_setup_and_warn_when_iterations_are_ignored() -> None:
    benchmark = _RecordingBenchmark()
    original = ["seed"]
    case = BenchmarkCase.from_values("fresh", original, fresh_inputs=True)

    with pytest.warns(RuntimeWarning, match="pedantic_iterations is ignored"):
        _ = benchmark_single_call_latency(
            benchmark,
            "impl",
            _identity,
            "fresh",
            case,
            config=BenchmarkConfig(pedantic_iterations=3, stream_progress=False),
        )

    assert len(benchmark.calls) == 0
    assert len(benchmark.pedantic_calls) == 1
    assert benchmark.pedantic_calls[0].setup
    assert benchmark.pedantic_calls[0].args[0] == original
    assert benchmark.pedantic_calls[0].args[0] is not original
    assert benchmark.pedantic_calls[0].iterations == 1


def test_tail_latency_warns_when_iterations_are_aggregate_samples() -> None:
    benchmark = _RecordingBenchmark()
    case = BenchmarkCase.from_values("input", 1)

    with pytest.warns(RuntimeWarning, match="per-round aggregate"):
        _ = benchmark_tail_latency(
            benchmark,
            "impl",
            _identity,
            "case-id",
            case,
            config=BenchmarkConfig(pedantic_iterations=3, stream_progress=False),
        )


def test_run_benchmark_metric_dispatches_all_supported_metrics() -> None:
    case = BenchmarkCase.from_values("input", 1)
    metrics: tuple[MetricName, ...] = ("single_call_latency", "batch_throughput", "tail_latency")

    for metric_name in metrics:
        benchmark = _RecordingBenchmark()
        record = run_benchmark_metric(
            benchmark,
            metric_name,
            "impl",
            _identity,
            "case-id",
            case,
            config=BenchmarkConfig(stream_progress=False),
        )

        assert record.metric_name == metric_name


def test_run_benchmark_metric_rejects_unsupported_metric() -> None:
    with pytest.raises(ValueError, match="Unsupported benchmark metric"):
        _ = run_benchmark_metric(
            _RecordingBenchmark(),
            cast(MetricName, cast(object, "not-a-metric")),
            "impl",
            _noop,
            "case-id",
            BenchmarkCase("input"),
            config=BenchmarkConfig(stream_progress=False),
        )


@pytest.mark.parametrize(
    ("implementation_name", "case_name", "message"),
    [
        ("", "case-id", "implementation name"),
        ("impl", "", "case name"),
    ],
)
def test_benchmark_helpers_reject_empty_metadata_names(
    implementation_name: str,
    case_name: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _ = benchmark_single_call_latency(
            _RecordingBenchmark(),
            implementation_name,
            _noop,
            case_name,
            BenchmarkCase("input"),
            config=BenchmarkConfig(stream_progress=False),
        )


async def _async_target() -> None:
    """Async target used to verify rejection."""


class _AsyncCallable:
    """Callable object with an async call method."""

    async def __call__(self) -> None:
        """Return asynchronously."""


@pytest.mark.parametrize("target", [_async_target, _AsyncCallable()])
def test_benchmark_helpers_reject_async_targets(target: Callable[..., object]) -> None:
    with pytest.raises(TypeError, match="synchronous target functions"):
        _ = benchmark_single_call_latency(
            _RecordingBenchmark(),
            "impl",
            target,
            "case-id",
            BenchmarkCase("input"),
            config=BenchmarkConfig(stream_progress=False),
        )


def test_make_benchmark_parameters_generates_cross_product_with_stable_ids() -> None:
    first = BenchmarkCase("first")
    second = BenchmarkCase("second")

    parameters = make_benchmark_parameters(
        {"impl-a": _noop, "impl-b": _noop},
        [first, second],
        metrics=("single_call_latency", "batch_throughput"),
    )

    assert len(parameters) == 8
    first_parameter = _parameter_set(parameters[0])
    assert first_parameter.values == ("single_call_latency", "impl-a", _noop, "first", first)
    assert first_parameter.id == "single_call_latency::impl-a::first"
    assert _parameter_set(parameters[-1]).id == "batch_throughput::impl-b::second"


def test_make_benchmark_parameters_accepts_mapping_case_names() -> None:
    case = BenchmarkCase("internal-name")

    parameters = make_benchmark_parameters(
        {"impl": _noop},
        {"external-name": case},
        metrics=("tail_latency",),
    )

    parameter = _parameter_set(parameters[0])
    assert parameter.values == ("tail_latency", "impl", _noop, "external-name", case)
    assert parameter.id == "tail_latency::impl::external-name"


@pytest.mark.parametrize(
    ("implementations", "cases", "metrics", "message"),
    [
        ({}, [BenchmarkCase("case")], ("single_call_latency",), "implementations"),
        ({"impl": _noop}, [], ("single_call_latency",), "cases"),
        ({"impl": _noop}, [BenchmarkCase("case")], (), "metrics"),
    ],
)
def test_make_benchmark_parameters_rejects_empty_matrix_inputs(
    implementations: Mapping[str, Callable[..., object]],
    cases: list[BenchmarkCase],
    metrics: tuple[MetricName, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _ = make_benchmark_parameters(implementations, cases, metrics=metrics)


def test_make_benchmark_parameters_rejects_unsupported_metrics() -> None:
    with pytest.raises(ValueError, match="Unsupported benchmark metric"):
        _ = make_benchmark_parameters(
            {"impl": _noop},
            [BenchmarkCase("case")],
            metrics=(cast(MetricName, cast(object, "not-a-metric")),),
        )


def test_make_benchmark_parameters_rejects_non_callable_implementations() -> None:
    implementations = cast(Mapping[str, Callable[..., object]], {"impl": object()})

    with pytest.raises(TypeError, match="must be callable"):
        _ = make_benchmark_parameters(
            implementations,
            [BenchmarkCase("case")],
            metrics=("single_call_latency",),
        )


def test_make_benchmark_parameters_rejects_non_case_iterables() -> None:
    cases = cast(list[BenchmarkCase], [object()])

    with pytest.raises(TypeError, match="Benchmark cases"):
        _ = make_benchmark_parameters(
            {"impl": _noop},
            cases,
            metrics=("single_call_latency",),
        )


def test_make_benchmark_parameters_rejects_non_case_mapping_values() -> None:
    cases = cast(Mapping[str, BenchmarkCase], {"external": object()})

    with pytest.raises(TypeError, match="Benchmark case 'external'"):
        _ = make_benchmark_parameters(
            {"impl": _noop},
            cases,
            metrics=("single_call_latency",),
        )


def test_make_benchmark_test_generates_executable_parametrized_test() -> None:
    benchmark = _RecordingBenchmark()
    case = BenchmarkCase.from_values("input", 3)
    benchmark_test = make_benchmark_test(
        {"identity": _identity},
        {"case-id": case},
        metrics=("tail_latency",),
        config=BenchmarkConfig(pedantic_rounds=7, warmup_rounds=2, stream_progress=False),
    )

    benchmark_test(
        benchmark,
        "tail_latency",
        "identity",
        _identity,
        "case-id",
        case,
    )

    assert len(benchmark.pedantic_calls) == 1
    assert benchmark.pedantic_calls[0].rounds == 7
    assert benchmark.pedantic_calls[0].warmup_rounds == 2
    assert benchmark.extra_info["metric_name"] == "tail_latency"
    assert benchmark.extra_info["implementation_name"] == "identity"
    assert benchmark.extra_info["case_name"] == "case-id"
