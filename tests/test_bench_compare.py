"""Tests for matrix-aware benchmark run comparisons."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from benchmatrix import (
    BenchmarkRun,
    EvidencePolicy,
    MetricName,
    ParsedBenchmarkRow,
    RegressionPolicy,
    RunCompatibilityPolicy,
    compare_benchmark_run_groups,
    compare_benchmark_runs,
)
from benchmatrix.bench_compare import CompatibilityMode

pytestmark = pytest.mark.unit


def _row(
    metric_name: MetricName,
    *,
    implementation_name: str = "impl",
    case_name: str = "small",
    value: float | None = None,
    unit: str = "calls/s",
    extra_info: dict[str, object] | None = None,
    samples: tuple[float, ...] = (),
    rounds: int | None = None,
    iterations: int | None = None,
) -> ParsedBenchmarkRow:
    """Create a parsed row with the primary comparison statistic."""
    derived: dict[str, object]
    if metric_name == "single_call_latency":
        derived = {} if value is None else {"latency_mean": value}
    elif metric_name == "batch_throughput":
        derived = {"throughput_unit_label": unit}
        if value is not None:
            derived["throughput_mean"] = value
    else:
        derived = {} if value is None else {"p95": value}

    metadata: dict[str, object] = {
        "benchmatrix_producer": "benchmatrix",
        "benchmatrix_schema_version": 1,
        "metric_name": metric_name,
        "implementation_name": implementation_name,
        "case_name": case_name,
        "case_fresh_inputs": False,
    }
    if metric_name == "batch_throughput":
        metadata["throughput_unit"] = "calls_per_second"
    if extra_info:
        metadata.update(extra_info)

    stats: dict[str, object] = {}
    if rounds is not None:
        stats["rounds"] = rounds
    if iterations is not None:
        stats["iterations"] = iterations

    return ParsedBenchmarkRow(
        benchmark_name=f"bench[{implementation_name}-{case_name}-{metric_name}]",
        metric_name=metric_name,
        implementation_name=implementation_name,
        case_name=case_name,
        stats=stats,
        extra_info=metadata,
        derived=derived,
        samples=samples,
    )


def _run(
    *rows: ParsedBenchmarkRow,
    source: str | None = None,
    metadata: dict[str, object] | None = None,
) -> BenchmarkRun:
    """Create a benchmark run."""
    return BenchmarkRun(
        rows=tuple(rows),
        metadata={"datetime": "2026-07-30"} if metadata is None else metadata,
        source=None if source is None else Path(source),
    )


def _environment_metadata(
    *,
    system: str = "Linux",
    release: str = "6.8.0",
    machine: str = "x86_64",
    python_implementation: str = "CPython",
    python_version: str = "3.14.6",
    python_compiler: str = "GCC 14",
    cpu_brand: str = "Example CPU",
    cpu_count: int = 8,
    flags: list[str] | None = None,
    benchmark_version: str = "5.2.3",
) -> dict[str, object]:
    """Create representative pytest-benchmark run metadata."""
    return {
        "version": benchmark_version,
        "machine_info": {
            "system": system,
            "release": release,
            "machine": machine,
            "python_implementation": python_implementation,
            "python_version": python_version,
            "python_compiler": python_compiler,
            "cpu": {
                "bits": 64,
                "brand_raw": cpu_brand,
                "vendor_id_raw": "ExampleVendor",
                "count": cpu_count,
                "flags": ["sse4", "avx2"] if flags is None else flags,
            },
        },
    }


def test_compare_benchmark_runs_uses_metric_aware_statistics_and_direction() -> None:
    baseline = _run(
        _row("single_call_latency", value=4.0),
        _row("batch_throughput", case_name="batch", value=100.0),
        _row("tail_latency", case_name="tail", value=8.0),
    )
    candidate = _run(
        _row("single_call_latency", value=3.0),
        _row("batch_throughput", case_name="batch", value=125.0),
        _row("tail_latency", case_name="tail", value=10.0),
    )

    result = compare_benchmark_runs(baseline, candidate)

    assert result.is_complete
    assert not result.missing
    assert not result.incompatible
    by_metric = {comparison.metric_name: comparison for comparison in result.matched}

    latency = by_metric["single_call_latency"]
    assert latency.statistic == "mean"
    assert latency.direction == "lower_is_better"
    assert latency.unit == "seconds"
    assert latency.ratio == 0.75
    assert latency.percent_change == -25.0
    assert latency.improvement_percent == 25.0

    throughput = by_metric["batch_throughput"]
    assert throughput.statistic == "mean"
    assert throughput.direction == "higher_is_better"
    assert throughput.unit == "calls/s"
    assert throughput.ratio == 1.25
    assert throughput.improvement_percent == 25.0

    tail = by_metric["tail_latency"]
    assert tail.statistic == "p95"
    assert tail.direction == "lower_is_better"
    assert tail.percent_change == 25.0
    assert tail.improvement_percent == -25.0
    assert tail.regression == "regressed"
    assert {comparison.metric_name for comparison in result.improved} == {
        "single_call_latency",
        "batch_throughput",
    }
    assert result.regressed == (tail,)
    assert result.has_regressions
    assert not result.passed


def test_compare_to_reports_union_of_matrix_cells_in_stable_order() -> None:
    baseline = _run(
        _row("single_call_latency", implementation_name="zeta", value=2.0),
        _row("single_call_latency", implementation_name="alpha", case_name="removed", value=1.0),
    )
    candidate = _run(
        _row("single_call_latency", implementation_name="zeta", value=1.0),
        _row("single_call_latency", implementation_name="alpha", case_name="added", value=1.0),
    )

    result = baseline.compare_to(candidate)

    assert [
        (comparison.implementation_name, comparison.case_name, comparison.status) for comparison in result.comparisons
    ] == [
        ("alpha", "added", "missing_baseline"),
        ("alpha", "removed", "missing_candidate"),
        ("zeta", "small", "matched"),
    ]
    assert [comparison.status for comparison in result.missing] == [
        "missing_baseline",
        "missing_candidate",
    ]
    assert not result.is_complete
    assert result.comparisons[0].reason == "Matrix cell is absent from the baseline run."
    assert result.comparisons[1].reason == "Matrix cell is absent from the candidate run."


def test_compare_benchmark_runs_rejects_changed_units_and_case_context() -> None:
    baseline = _run(
        _row(
            "batch_throughput",
            value=10.0,
            unit="rows/s",
            extra_info={
                "throughput_unit": "work_units_per_second",
                "work_units": 10.0,
                "work_unit_name": "rows",
                "case_size": 10,
            },
        ),
        _row(
            "single_call_latency",
            case_name="context",
            value=1.0,
            extra_info={"case_size": 10},
        ),
    )
    candidate = _run(
        _row(
            "batch_throughput",
            value=20.0,
            unit="items/s",
            extra_info={
                "throughput_unit": "work_units_per_second",
                "work_units": 10.0,
                "work_unit_name": "items",
                "case_size": 10,
            },
        ),
        _row(
            "single_call_latency",
            case_name="context",
            value=0.5,
            extra_info={"case_size": 20},
        ),
    )

    result = compare_benchmark_runs(baseline, candidate)

    assert len(result.incompatible) == 2
    by_case = {comparison.case_name: comparison for comparison in result.incompatible}
    assert by_case["small"].reason == "Comparison units differ: 'rows/s' != 'items/s'."
    assert by_case["context"].reason == "Measurement context differs for metadata: case_size."
    assert all(comparison.ratio is None for comparison in result.incompatible)


@pytest.mark.parametrize("bad_value", [None, float("nan"), float("inf"), True, "1.0"])
def test_compare_benchmark_runs_marks_invalid_derived_values_incompatible(
    bad_value: object,
) -> None:
    baseline_row = _row("single_call_latency", value=1.0)
    candidate_row = _row("single_call_latency", value=None)
    candidate_row = ParsedBenchmarkRow(
        benchmark_name=candidate_row.benchmark_name,
        metric_name=candidate_row.metric_name,
        implementation_name=candidate_row.implementation_name,
        case_name=candidate_row.case_name,
        stats=candidate_row.stats,
        extra_info=candidate_row.extra_info,
        derived={"latency_mean": bad_value},
    )

    comparison = compare_benchmark_runs(_run(baseline_row), _run(candidate_row)).comparisons[0]

    assert comparison.status == "incompatible"
    assert comparison.candidate_value is None
    assert comparison.reason == "Both rows must contain a finite 'latency_mean' derived value."


def test_compare_benchmark_runs_handles_zero_baseline_without_infinite_change() -> None:
    result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=0.0)),
        _run(_row("single_call_latency", value=1.0)),
    )

    comparison = result.matched[0]
    assert comparison.baseline_value == 0.0
    assert comparison.candidate_value == 1.0
    assert comparison.ratio is None
    assert comparison.percent_change is None
    assert comparison.improvement_percent is None


def test_compare_benchmark_runs_distinguishes_missing_metadata_from_null() -> None:
    baseline = _row(
        "single_call_latency",
        value=1.0,
        extra_info={"case_optional": None},
    )
    candidate = _row("single_call_latency", value=1.0)

    comparison = compare_benchmark_runs(_run(baseline), _run(candidate)).incompatible[0]

    assert comparison.reason == "Measurement context differs for metadata: case_optional."


def test_compare_benchmark_runs_handles_missing_throughput_unit_label() -> None:
    baseline = _row("batch_throughput", value=1.0, unit="")
    candidate = _row("batch_throughput", value=2.0, unit="")
    baseline = ParsedBenchmarkRow(
        benchmark_name=baseline.benchmark_name,
        metric_name=baseline.metric_name,
        implementation_name=baseline.implementation_name,
        case_name=baseline.case_name,
        stats=baseline.stats,
        extra_info=baseline.extra_info,
        derived={"throughput_mean": 1.0, "throughput_unit_label": cast(object, 123)},
    )

    comparison = compare_benchmark_runs(_run(baseline), _run(candidate)).matched[0]

    assert comparison.unit == ""
    assert comparison.ratio == 2.0


def test_run_compatibility_accepts_equivalent_normalized_environments() -> None:
    baseline_metadata = _environment_metadata(
        system="Linux",
        machine="AMD64",
        flags=["avx2", "sse4"],
    )
    candidate_metadata = _environment_metadata(
        system="linux",
        machine="x86-64",
        python_implementation="cpython",
        flags=["sse4", "avx2"],
    )

    result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=1.0), metadata=baseline_metadata),
        _run(_row("single_call_latency", value=0.99), metadata=candidate_metadata),
    )

    assert result.compatibility.is_compatible
    assert not result.compatibility.findings
    assert result.unchanged[0].regression == "unchanged"
    assert result.passed


def test_permissive_compatibility_blocks_material_environment_changes() -> None:
    baseline_metadata = _environment_metadata()
    candidate_metadata = _environment_metadata(
        system="Darwin",
        machine="arm64",
        python_implementation="PyPy",
        python_version="3.13.2",
        cpu_brand="Other CPU",
    )

    result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=1.0), metadata=baseline_metadata),
        _run(_row("single_call_latency", value=0.5), metadata=candidate_metadata),
    )

    blocking_fields = {finding.field for finding in result.compatibility.blocking}
    assert blocking_fields == {
        "architecture",
        "cpu.brand",
        "os.system",
        "python.implementation",
        "python.version",
    }
    assert not result.compatibility.is_compatible
    assert result.matched[0].regression == "not_comparable"
    assert result.not_comparable == result.comparisons
    assert not result.is_comparable
    assert not result.passed


def test_permissive_compatibility_warns_for_lower_risk_changes() -> None:
    baseline_metadata = _environment_metadata()
    baseline_metadata["dependencies"] = {"benchmatrix": "0.3.0"}
    candidate_metadata = _environment_metadata(
        release="6.9.0",
        python_version="3.14.7",
        python_compiler="GCC 15",
        cpu_count=16,
        flags=["avx2", "avx512", "sse4"],
        benchmark_version="5.3.0",
    )
    candidate_metadata["dependencies"] = {"benchmatrix": "0.4.0"}

    result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=1.0), metadata=baseline_metadata),
        _run(_row("single_call_latency", value=1.0), metadata=candidate_metadata),
    )

    warning_fields = {finding.field for finding in result.compatibility.warnings}
    assert warning_fields == {
        "cpu.count",
        "cpu.flags",
        "dependencies",
        "os.release",
        "pytest_benchmark.version",
        "python.compiler",
        "python.version",
    }
    assert not result.compatibility.blocking
    assert result.compatibility.is_compatible
    assert result.passed


def test_strict_compatibility_promotes_warnings_and_missing_metadata() -> None:
    baseline_metadata = _environment_metadata()
    candidate_metadata = _environment_metadata(python_version="3.14.7")
    strict = RunCompatibilityPolicy(mode="strict")

    patch_result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=1.0), metadata=baseline_metadata),
        _run(_row("single_call_latency", value=1.0), metadata=candidate_metadata),
        compatibility_policy=strict,
    )
    missing_result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=1.0)),
        _run(_row("single_call_latency", value=1.0)),
        compatibility_policy=strict,
    )

    assert patch_result.compatibility.blocking[0].field == "python.version"
    assert patch_result.compatibility.blocking[0].reason == "Python patch versions differ."
    assert missing_result.compatibility.blocking[0].field == "machine_info"
    assert not missing_result.compatibility.is_compatible


def test_strict_compatibility_requires_core_fields_but_not_dependency_metadata() -> None:
    sparse_metadata = {
        "version": "5.2.3",
        "machine_info": {"python_version": "3.14.6"},
    }

    result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=1.0), metadata=sparse_metadata),
        _run(_row("single_call_latency", value=1.0), metadata=sparse_metadata),
        compatibility_policy=RunCompatibilityPolicy(mode="strict"),
    )

    blocking_fields = {finding.field for finding in result.compatibility.blocking}
    assert "architecture" in blocking_fields
    assert "os.system" in blocking_fields
    assert "python.implementation" in blocking_fields
    assert "dependencies" not in blocking_fields


def test_compatibility_off_disables_environment_findings() -> None:
    result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=1.0), metadata=_environment_metadata(system="Linux")),
        _run(_row("single_call_latency", value=2.0), metadata=_environment_metadata(system="Darwin")),
        compatibility_policy=RunCompatibilityPolicy(mode="off"),
    )

    assert result.compatibility.findings == ()
    assert result.compatibility.is_compatible
    assert result.regressed[0].regression == "regressed"


def test_permissive_compatibility_reports_partially_missing_fields() -> None:
    baseline_metadata = _environment_metadata()
    candidate_metadata = _environment_metadata()
    candidate_machine = cast(dict[str, object], candidate_metadata["machine_info"])
    _ = candidate_machine.pop("python_compiler")

    result = compare_benchmark_runs(
        _run(_row("single_call_latency", value=1.0), metadata=baseline_metadata),
        _run(_row("single_call_latency", value=1.0), metadata=candidate_metadata),
    )

    finding = result.compatibility.warnings[0]
    assert finding.field == "python.compiler"
    assert finding.baseline_value == "GCC 14"
    assert finding.candidate_value is None
    assert finding.reason == "python.compiler metadata is missing from one run."


def test_regression_policy_classifies_threshold_boundaries() -> None:
    policy = RegressionPolicy(default_threshold_percent=5.0)
    baseline = _run(
        _row("single_call_latency", case_name="improved", value=100.0),
        _row("single_call_latency", case_name="boundary", value=100.0),
        _row("single_call_latency", case_name="regressed", value=100.0),
    )
    candidate = _run(
        _row("single_call_latency", case_name="improved", value=94.0),
        _row("single_call_latency", case_name="boundary", value=105.0),
        _row("single_call_latency", case_name="regressed", value=106.0),
    )

    result = compare_benchmark_runs(baseline, candidate, regression_policy=policy)
    by_case = {comparison.case_name: comparison for comparison in result.comparisons}

    assert by_case["improved"].regression == "improved"
    assert by_case["boundary"].regression == "unchanged"
    assert by_case["regressed"].regression == "regressed"
    assert all(comparison.threshold_percent == 5.0 for comparison in result.comparisons)
    assert len(result.improved) == 1
    assert len(result.unchanged) == 1
    assert len(result.regressed) == 1


def test_regression_policy_uses_documented_selector_precedence() -> None:
    policy = RegressionPolicy(
        default_threshold_percent=10.0,
        by_metric={"single_call_latency": 8.0},
        by_implementation={"impl": 6.0},
        by_case={"special": 4.0},
        by_cell={("impl", "exact", "single_call_latency"): 2.0},
    )
    baseline = _run(
        _row("single_call_latency", implementation_name="other", case_name="default", value=100.0),
        _row("single_call_latency", case_name="implementation", value=100.0),
        _row("single_call_latency", case_name="special", value=100.0),
        _row("single_call_latency", case_name="exact", value=100.0),
    )
    candidate = _run(
        _row("single_call_latency", implementation_name="other", case_name="default", value=95.0),
        _row("single_call_latency", case_name="implementation", value=95.0),
        _row("single_call_latency", case_name="special", value=95.0),
        _row("single_call_latency", case_name="exact", value=95.0),
    )

    result = compare_benchmark_runs(baseline, candidate, regression_policy=policy)
    thresholds = {
        (comparison.implementation_name, comparison.case_name): comparison.threshold_percent
        for comparison in result.comparisons
    }

    assert thresholds == {
        ("impl", "exact"): 2.0,
        ("impl", "implementation"): 6.0,
        ("impl", "special"): 4.0,
        ("other", "default"): 8.0,
    }
    assert len(result.improved) == 2
    assert len(result.unchanged) == 2
    assert policy.threshold_scope_for("impl", "exact", "single_call_latency") == "cell"
    assert policy.threshold_scope_for("impl", "special", "single_call_latency") == "case"
    assert policy.threshold_scope_for("impl", "implementation", "single_call_latency") == "implementation"
    assert policy.threshold_scope_for("other", "default", "single_call_latency") == "metric"
    assert policy.threshold_scope_for("other", "default", "tail_latency") == "default"


@pytest.mark.parametrize(
    ("kwargs", "error_type", "message"),
    [
        ({"default_threshold_percent": True}, TypeError, "must be a numeric percentage"),
        ({"default_threshold_percent": float("inf")}, ValueError, "must be finite"),
        ({"default_threshold_percent": -1.0}, ValueError, "must not be negative"),
        ({"by_metric": {cast(MetricName, "unknown"): 1.0}}, ValueError, "Unsupported regression policy metric"),
        ({"by_case": {"": 1.0}}, ValueError, "case selector must not be empty"),
        (
            {"by_cell": {cast(tuple[str, str, MetricName], ("bad",)): 1.0}},
            TypeError,
            "cell keys must be",
        ),
    ],
)
def test_regression_policy_rejects_invalid_configuration(
    kwargs: dict[str, Any],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        _ = RegressionPolicy(**kwargs)


def test_run_compatibility_policy_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="Unsupported run compatibility mode"):
        _ = RunCompatibilityPolicy(mode=cast(CompatibilityMode, "unknown"))


def _evidence_row(value: float, *samples: float) -> ParsedBenchmarkRow:
    """Create a latency row with complete trust-diagnostic statistics."""
    return _row(
        "single_call_latency",
        value=value,
        samples=tuple(samples),
        rounds=len(samples),
        iterations=1,
    )


def test_repeated_run_comparison_aggregates_medians_and_consistent_effects() -> None:
    baselines = (
        _run(_evidence_row(100.0, 98.0, 99.0, 100.0, 101.0, 102.0)),
        _run(_evidence_row(102.0, 100.0, 101.0, 102.0, 103.0, 104.0)),
    )
    candidates = (
        _run(_evidence_row(110.0, 108.0, 109.0, 110.0, 111.0, 112.0)),
        _run(_evidence_row(112.0, 110.0, 111.0, 112.0, 113.0, 114.0)),
    )

    result = compare_benchmark_run_groups(baselines, candidates)

    comparison = result.comparisons[0]
    assert comparison.baseline_value == 101.0
    assert comparison.candidate_value == 111.0
    assert comparison.regression == "regressed"
    assert comparison.improvement_low_percent == pytest.approx(-12.0)
    assert comparison.improvement_high_percent == pytest.approx(-7.8431372549)
    assert comparison.baseline_evidence is not None
    assert comparison.baseline_evidence.rounds == (5, 5)
    assert comparison.baseline_evidence.iterations == (1, 1)
    assert comparison.baseline_evidence.sample_count == 10
    assert comparison.baseline_evidence.iqr == pytest.approx(2.0)
    assert comparison.baseline_evidence.coefficient_of_variation is not None
    assert comparison.baseline_evidence.outlier_count == 0
    assert comparison.baseline_evidence.adequate
    assert result.baseline_runs == baselines
    assert result.candidate_runs == candidates
    assert result.has_regressions


def test_repeated_run_comparison_marks_conflicting_effects_inconclusive() -> None:
    baselines = (
        _run(_evidence_row(100.0, 98.0, 99.0, 100.0, 101.0, 102.0)),
        _run(_evidence_row(120.0, 118.0, 119.0, 120.0, 121.0, 122.0)),
    )
    candidates = (
        _run(_evidence_row(105.0, 103.0, 104.0, 105.0, 106.0, 107.0)),
        _run(_evidence_row(115.0, 113.0, 114.0, 115.0, 116.0, 117.0)),
    )

    comparison = compare_benchmark_run_groups(baselines, candidates).comparisons[0]

    assert comparison.regression == "inconclusive"
    assert comparison.reason is not None
    assert "pairwise range" in comparison.reason


def test_repeated_run_comparison_reports_inadequate_evidence() -> None:
    baseline = _run(_evidence_row(100.0, 99.0, 100.0))
    candidate = _run(_evidence_row(110.0, 109.0, 110.0))

    result = compare_benchmark_run_groups((baseline,), (candidate,))

    comparison = result.comparisons[0]
    assert comparison.regression == "inconclusive"
    assert comparison.baseline_evidence is not None
    assert not comparison.baseline_evidence.adequate
    assert comparison.baseline_evidence.issues == (
        "only 1 run(s) contain the cell; 2 required",
        "run 0 has 2 sample(s); 5 required",
    )
    assert comparison.reason is not None
    assert comparison.reason.startswith("Inadequate evidence:")
    assert result.inconclusive == (comparison,)
    assert not result.passed


def test_evidence_policy_can_reject_high_variation_and_outlier_fraction() -> None:
    noisy = _evidence_row(1.0, 1.0, 1.0, 1.0, 1.0, 10.0)
    policy = EvidencePolicy(
        maximum_cv=0.1,
        maximum_outlier_fraction=0.1,
    )

    comparison = compare_benchmark_run_groups(
        (_run(noisy), _run(noisy)),
        (_run(noisy), _run(noisy)),
        evidence_policy=policy,
    ).comparisons[0]

    assert comparison.regression == "inconclusive"
    assert comparison.baseline_evidence is not None
    assert comparison.baseline_evidence.outlier_count == 2
    assert comparison.baseline_evidence.outlier_fraction == 0.2
    assert any("coefficient of variation" in issue for issue in comparison.baseline_evidence.issues)
    assert any("outlier fraction" in issue for issue in comparison.baseline_evidence.issues)


def test_repeated_run_comparison_requires_cell_in_every_provided_run() -> None:
    present = _evidence_row(100.0, 98.0, 99.0, 100.0, 101.0, 102.0)
    other = _row(
        "single_call_latency",
        case_name="other",
        value=1.0,
        samples=(1.0,) * 5,
        rounds=5,
        iterations=1,
    )

    result = compare_benchmark_run_groups(
        (_run(present), _run(other)),
        (_run(present), _run(present)),
    )
    comparison = next(cell for cell in result.comparisons if cell.case_name == "small")

    assert comparison.status == "matched"
    assert comparison.regression == "inconclusive"
    assert comparison.baseline_evidence is not None
    assert "cell is missing from 1 provided run(s)" in comparison.baseline_evidence.issues


def test_repeated_run_compatibility_checks_every_environment() -> None:
    row = _evidence_row(1.0, 0.9, 1.0, 1.0, 1.0, 1.1)
    linux = _environment_metadata(system="Linux")
    darwin = _environment_metadata(system="Darwin")

    result = compare_benchmark_run_groups(
        (_run(row, metadata=linux), _run(row, metadata=linux)),
        (_run(row, metadata=linux), _run(row, metadata=darwin)),
    )

    assert result.compatibility.pairs_checked == 3
    finding = next(item for item in result.compatibility.blocking if item.field == "os.system")
    assert finding.baseline_run == "baseline[0]"
    assert finding.candidate_run == "candidate[1]"
    assert result.comparisons[0].regression == "not_comparable"


@pytest.mark.parametrize(
    ("kwargs", "error_type", "message"),
    [
        ({"minimum_runs": 0}, ValueError, "minimum_runs"),
        ({"minimum_runs": cast(int, "2")}, TypeError, "must be an integer"),
        ({"minimum_samples_per_run": -1}, ValueError, "minimum_samples_per_run"),
        ({"maximum_cv": -0.1}, ValueError, "must not be negative"),
        ({"maximum_outlier_fraction": True}, TypeError, "must be numeric"),
        ({"require_rounds": cast(bool, 1)}, TypeError, "must be a boolean"),
    ],
)
def test_evidence_policy_rejects_invalid_configuration(
    kwargs: dict[str, Any],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        _ = EvidencePolicy(**kwargs)


def test_repeated_run_comparison_rejects_empty_or_invalid_groups() -> None:
    run = _run(_row("single_call_latency", value=1.0))

    with pytest.raises(ValueError, match="baselines"):
        _ = compare_benchmark_run_groups((), (run,))
    with pytest.raises(TypeError, match=r"candidates\[0\]"):
        _ = compare_benchmark_run_groups((run,), cast(tuple[BenchmarkRun], (object(),)))
