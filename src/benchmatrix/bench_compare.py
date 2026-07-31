"""Matrix-aware comparison of parsed benchmark runs."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

from ._schema import (
    DERIVED_LATENCY_MEAN,
    DERIVED_P95,
    DERIVED_THROUGHPUT_MEAN,
    DERIVED_THROUGHPUT_UNIT_LABEL,
    KEY_CASE_FRESH_INPUTS,
    KEY_TAIL_PERCENTILES,
    KEY_THROUGHPUT_UNIT,
    KEY_WORK_UNIT_NAME,
    KEY_WORK_UNITS,
    KNOWN_METRICS,
    METRIC_BATCH_THROUGHPUT,
    METRIC_SINGLE_CALL_LATENCY,
    METRIC_TAIL_LATENCY,
    MetricName,
)
from .bench_results import BenchmarkRun, ParsedBenchmarkRow

ComparisonStatus: TypeAlias = Literal[
    "matched",
    "missing_baseline",
    "missing_candidate",
    "incompatible",
]
ComparisonDirection: TypeAlias = Literal["lower_is_better", "higher_is_better"]
RegressionClassification: TypeAlias = Literal[
    "improved",
    "unchanged",
    "regressed",
    "inconclusive",
    "not_comparable",
]
RegressionThresholdScope: TypeAlias = Literal["cell", "case", "implementation", "metric", "default"]
CompatibilityMode: TypeAlias = Literal["strict", "permissive", "off"]
CompatibilitySeverity: TypeAlias = Literal["blocking", "warning"]

_CellKey: TypeAlias = tuple[str, str, MetricName]
_MISSING = object()


@dataclass(frozen=True, slots=True)
class RunCompatibilityPolicy:
    """Policy controlling run-environment compatibility checks.

    ``permissive`` keeps lower-risk differences as warnings, ``strict``
    promotes every difference or missing environment record to a blocker, and
    ``off`` disables run-level compatibility checks.
    """

    mode: CompatibilityMode = "permissive"

    def __post_init__(self) -> None:
        """Validate the compatibility mode."""
        if self.mode not in {"strict", "permissive", "off"}:
            raise ValueError(f"Unsupported run compatibility mode: {self.mode!r}.")


@dataclass(frozen=True, slots=True)
class RunCompatibilityFinding:
    """One material difference between two run environments."""

    field: str
    baseline_value: object | None
    candidate_value: object | None
    severity: CompatibilitySeverity
    reason: str
    baseline_run: str | None = None
    candidate_run: str | None = None


@dataclass(frozen=True, slots=True)
class RunCompatibilityReport:
    """Compatibility findings for the baseline and candidate environments."""

    policy: RunCompatibilityPolicy
    findings: tuple[RunCompatibilityFinding, ...]
    pairs_checked: int = 1

    @property
    def blocking(self) -> tuple[RunCompatibilityFinding, ...]:
        """Return differences that prevent a trustworthy comparison."""
        return tuple(finding for finding in self.findings if finding.severity == "blocking")

    @property
    def warnings(self) -> tuple[RunCompatibilityFinding, ...]:
        """Return non-blocking environment differences."""
        return tuple(finding for finding in self.findings if finding.severity == "warning")

    @property
    def is_compatible(self) -> bool:
        """Return whether no blocking environment differences were found."""
        return not self.blocking


@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    """Minimum evidence required for repeated-run classifications.

    Args:
        minimum_runs: Minimum files on each side containing a matrix cell.
        minimum_samples_per_run: Minimum raw timing samples required from each
            observed file.
        require_rounds: Whether every row must report a positive round count.
        require_iterations: Whether every row must report a positive iteration
            count.
        maximum_cv: Optional maximum pooled-sample coefficient of variation.
        maximum_outlier_fraction: Optional maximum pooled-sample Tukey-outlier
            fraction.
    """

    minimum_runs: int = 2
    minimum_samples_per_run: int = 5
    require_rounds: bool = True
    require_iterations: bool = True
    maximum_cv: float | None = None
    maximum_outlier_fraction: float | None = None

    def __post_init__(self) -> None:
        """Validate evidence thresholds."""
        if isinstance(self.minimum_runs, bool) or not isinstance(self.minimum_runs, int):
            raise TypeError("EvidencePolicy.minimum_runs must be an integer.")
        if self.minimum_runs <= 0:
            raise ValueError("EvidencePolicy.minimum_runs must be a positive integer.")
        if isinstance(self.minimum_samples_per_run, bool) or not isinstance(self.minimum_samples_per_run, int):
            raise TypeError("EvidencePolicy.minimum_samples_per_run must be an integer.")
        if self.minimum_samples_per_run < 0:
            raise ValueError("EvidencePolicy.minimum_samples_per_run must be a non-negative integer.")
        if not isinstance(self.require_rounds, bool):
            raise TypeError("EvidencePolicy.require_rounds must be a boolean.")
        if not isinstance(self.require_iterations, bool):
            raise TypeError("EvidencePolicy.require_iterations must be a boolean.")
        if self.maximum_cv is not None:
            object.__setattr__(
                self,
                "maximum_cv",
                _validate_non_negative_number(
                    self.maximum_cv,
                    field_name="EvidencePolicy.maximum_cv",
                ),
            )
        if self.maximum_outlier_fraction is not None:
            object.__setattr__(
                self,
                "maximum_outlier_fraction",
                _validate_fraction(
                    self.maximum_outlier_fraction,
                    field_name="EvidencePolicy.maximum_outlier_fraction",
                ),
            )


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    """Trust diagnostics for one side of a matrix-cell comparison.

    Attributes:
        provided_run_count: Files supplied for this side.
        observed_run_count: Files containing this matrix cell.
        rounds: Positive pytest-benchmark round counts aligned to the files.
        iterations: Positive iteration counts aligned to the files.
        sample_counts: Raw timing sample counts aligned to the files.
        sample_count: Total pooled raw timing samples.
        iqr: Interquartile range of pooled timing samples in seconds.
        coefficient_of_variation: Pooled timing-sample population standard
            deviation divided by the absolute mean.
        outlier_count: Samples outside the pooled 1.5-IQR Tukey fences.
        outlier_fraction: Outlier count divided by total sample count.
        adequate: Whether the configured evidence policy was satisfied.
        issues: Human-readable reasons evidence is inadequate.
    """

    provided_run_count: int
    observed_run_count: int
    rounds: tuple[int | None, ...]
    iterations: tuple[int | None, ...]
    sample_counts: tuple[int, ...]
    sample_count: int
    iqr: float | None
    coefficient_of_variation: float | None
    outlier_count: int | None
    outlier_fraction: float | None
    adequate: bool
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegressionPolicy:
    """Threshold policy for classifying benchmark changes.

    Thresholds are percentage points and must be finite and non-negative. More
    specific mappings override broader ones in this order: exact matrix cell,
    case, implementation, metric, then the default threshold.
    """

    default_threshold_percent: float = 5.0
    by_metric: Mapping[MetricName, float] = field(default_factory=dict)
    by_implementation: Mapping[str, float] = field(default_factory=dict)
    by_case: Mapping[str, float] = field(default_factory=dict)
    by_cell: Mapping[tuple[str, str, MetricName], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate thresholds and freeze policy mappings."""
        default_threshold = _validate_threshold(
            self.default_threshold_percent,
            field_name="default_threshold_percent",
        )
        by_metric = {
            _validate_metric_key(metric_name): _validate_threshold(
                threshold,
                field_name=f"by_metric[{metric_name!r}]",
            )
            for metric_name, threshold in self.by_metric.items()
        }
        by_implementation = {
            _validate_selector_name(implementation_name, field_name="implementation"): _validate_threshold(
                threshold,
                field_name=f"by_implementation[{implementation_name!r}]",
            )
            for implementation_name, threshold in self.by_implementation.items()
        }
        by_case = {
            _validate_selector_name(case_name, field_name="case"): _validate_threshold(
                threshold,
                field_name=f"by_case[{case_name!r}]",
            )
            for case_name, threshold in self.by_case.items()
        }
        by_cell = {
            _validate_cell_key(cell): _validate_threshold(
                threshold,
                field_name=f"by_cell[{cell!r}]",
            )
            for cell, threshold in self.by_cell.items()
        }

        object.__setattr__(self, "default_threshold_percent", default_threshold)
        object.__setattr__(self, "by_metric", MappingProxyType(by_metric))
        object.__setattr__(self, "by_implementation", MappingProxyType(by_implementation))
        object.__setattr__(self, "by_case", MappingProxyType(by_case))
        object.__setattr__(self, "by_cell", MappingProxyType(by_cell))

    def threshold_for(
        self,
        implementation_name: str,
        case_name: str,
        metric_name: MetricName,
    ) -> float:
        """Return the effective threshold for one matrix cell."""
        scope = self.threshold_scope_for(implementation_name, case_name, metric_name)
        cell = (implementation_name, case_name, metric_name)
        if scope == "cell":
            return self.by_cell[cell]
        if scope == "case":
            return self.by_case[case_name]
        if scope == "implementation":
            return self.by_implementation[implementation_name]
        if scope == "metric":
            return self.by_metric[metric_name]
        return self.default_threshold_percent

    def threshold_scope_for(
        self,
        implementation_name: str,
        case_name: str,
        metric_name: MetricName,
    ) -> RegressionThresholdScope:
        """Return the selector scope that supplies one cell's threshold."""
        cell = (implementation_name, case_name, metric_name)
        if cell in self.by_cell:
            return "cell"
        if case_name in self.by_case:
            return "case"
        if implementation_name in self.by_implementation:
            return "implementation"
        if metric_name in self.by_metric:
            return "metric"
        return "default"


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    """Comparison for one implementation, case, and metric matrix cell.

    ``percent_change`` is the conventional candidate change from baseline,
    while ``improvement_percent`` is direction-aware and therefore positive
    when the candidate is better.
    """

    implementation_name: str
    case_name: str
    metric_name: MetricName
    statistic: str
    direction: ComparisonDirection
    status: ComparisonStatus
    baseline_value: float | None
    candidate_value: float | None
    ratio: float | None
    percent_change: float | None
    improvement_percent: float | None
    regression: RegressionClassification
    threshold_percent: float
    unit: str
    baseline_evidence: BenchmarkEvidence | None = None
    candidate_evidence: BenchmarkEvidence | None = None
    improvement_low_percent: float | None = None
    improvement_high_percent: float | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkRunComparison:
    """Matrix-aware comparison between a baseline and candidate run."""

    baseline: BenchmarkRun
    candidate: BenchmarkRun
    compatibility: RunCompatibilityReport
    regression_policy: RegressionPolicy
    comparisons: tuple[BenchmarkComparison, ...]
    baseline_runs: tuple[BenchmarkRun, ...] = ()
    candidate_runs: tuple[BenchmarkRun, ...] = ()
    evidence_policy: EvidencePolicy = field(default_factory=EvidencePolicy)

    @property
    def matched(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells that were compared successfully."""
        return tuple(comparison for comparison in self.comparisons if comparison.status == "matched")

    @property
    def missing(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells absent from either input run."""
        return tuple(
            comparison
            for comparison in self.comparisons
            if comparison.status in {"missing_baseline", "missing_candidate"}
        )

    @property
    def incompatible(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells whose measurement context cannot be compared."""
        return tuple(comparison for comparison in self.comparisons if comparison.status == "incompatible")

    @property
    def improved(self) -> tuple[BenchmarkComparison, ...]:
        """Return comparable cells that exceeded their improvement threshold."""
        return tuple(comparison for comparison in self.comparisons if comparison.regression == "improved")

    @property
    def unchanged(self) -> tuple[BenchmarkComparison, ...]:
        """Return comparable cells whose changes stayed within threshold."""
        return tuple(comparison for comparison in self.comparisons if comparison.regression == "unchanged")

    @property
    def regressed(self) -> tuple[BenchmarkComparison, ...]:
        """Return comparable cells that exceeded their regression threshold."""
        return tuple(comparison for comparison in self.comparisons if comparison.regression == "regressed")

    @property
    def inconclusive(self) -> tuple[BenchmarkComparison, ...]:
        """Return matched cells whose evidence cannot support a decision."""
        return tuple(comparison for comparison in self.comparisons if comparison.regression == "inconclusive")

    @property
    def not_comparable(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells without a trustworthy regression classification."""
        return tuple(comparison for comparison in self.comparisons if comparison.regression == "not_comparable")

    @property
    def is_complete(self) -> bool:
        """Return whether every matrix cell was compared successfully."""
        return len(self.matched) == len(self.comparisons)

    @property
    def is_comparable(self) -> bool:
        """Return whether environment and every matrix cell are comparable."""
        return self.compatibility.is_compatible and self.is_complete and not self.not_comparable

    @property
    def has_regressions(self) -> bool:
        """Return whether any comparable matrix cell regressed."""
        return bool(self.regressed)

    @property
    def passed(self) -> bool:
        """Return whether the comparison is trustworthy and regression-free."""
        return self.is_comparable and not self.has_regressions and not self.inconclusive


def compare_benchmark_runs(
    baseline: BenchmarkRun,
    candidate: BenchmarkRun,
    *,
    compatibility_policy: RunCompatibilityPolicy | None = None,
    regression_policy: RegressionPolicy | None = None,
) -> BenchmarkRunComparison:
    """Compare two runs across the union of their benchmark matrix cells.

    Comparisons use mean latency for ``single_call_latency``, mean throughput
    for ``batch_throughput``, and p95 latency for ``tail_latency``. Missing
    cells and changed case or unit metadata are retained as explicit results
    rather than silently dropped.

    Args:
        baseline: Reference benchmark run.
        candidate: Benchmark run being evaluated.
        compatibility_policy: Environment checks to apply. Defaults to
            permissive compatibility.
        regression_policy: Thresholds used to classify cell changes. Defaults
            to a five-percent threshold.

    Returns:
        A deterministic comparison across both run matrices.
    """
    return compare_benchmark_run_groups(
        (baseline,),
        (candidate,),
        compatibility_policy=compatibility_policy,
        regression_policy=regression_policy,
        evidence_policy=EvidencePolicy(
            minimum_runs=1,
            minimum_samples_per_run=0,
            require_rounds=False,
            require_iterations=False,
        ),
    )


def compare_benchmark_run_groups(
    baselines: Sequence[BenchmarkRun],
    candidates: Sequence[BenchmarkRun],
    *,
    compatibility_policy: RunCompatibilityPolicy | None = None,
    regression_policy: RegressionPolicy | None = None,
    evidence_policy: EvidencePolicy | None = None,
) -> BenchmarkRunComparison:
    """Compare repeated baseline and candidate runs as two evidence groups.

    Each cell uses the median of its per-run metric values. A change beyond the
    configured regression threshold is conclusive only when every pairwise
    baseline/candidate effect agrees beyond that threshold.

    Args:
        baselines: Repeated reference benchmark runs.
        candidates: Repeated candidate benchmark runs.
        compatibility_policy: Environment checks applied across every run.
        regression_policy: Percentage thresholds for classifying changes.
        evidence_policy: Minimum repeated-run and sample evidence.

    Returns:
        A matrix comparison with per-side trust diagnostics.

    Raises:
        ValueError: If either run group is empty.
        TypeError: If a group contains a value other than ``BenchmarkRun``.
    """
    baseline_runs = _validate_run_group(baselines, field_name="baselines")
    candidate_runs = _validate_run_group(candidates, field_name="candidates")
    resolved_compatibility_policy = compatibility_policy or RunCompatibilityPolicy()
    resolved_regression_policy = regression_policy or RegressionPolicy()
    resolved_evidence_policy = evidence_policy or EvidencePolicy()
    compatibility = _compare_run_group_compatibility(
        baseline_runs,
        candidate_runs,
        policy=resolved_compatibility_policy,
    )
    baseline_maps = tuple({_row_key(row): row for row in run.rows} for run in baseline_runs)
    candidate_maps = tuple({_row_key(row): row for row in run.rows} for run in candidate_runs)
    keys = sorted(
        set().union(*(set(rows) for rows in (*baseline_maps, *candidate_maps))),
        key=_sort_key,
    )
    comparisons = tuple(
        _compare_repeated_cell(
            key,
            tuple(rows.get(key) for rows in baseline_maps),
            tuple(rows.get(key) for rows in candidate_maps),
            environment_compatible=compatibility.is_compatible,
            regression_policy=resolved_regression_policy,
            evidence_policy=resolved_evidence_policy,
        )
        for key in keys
    )
    return BenchmarkRunComparison(
        baseline=baseline_runs[0],
        candidate=candidate_runs[0],
        compatibility=compatibility,
        regression_policy=resolved_regression_policy,
        comparisons=comparisons,
        baseline_runs=baseline_runs,
        candidate_runs=candidate_runs,
        evidence_policy=resolved_evidence_policy,
    )


def _row_key(row: ParsedBenchmarkRow) -> _CellKey:
    """Return the matrix identity for a parsed row."""
    return (row.implementation_name, row.case_name, row.metric_name)


def _sort_key(key: _CellKey) -> tuple[str, str, str]:
    """Return a stable ordering key for matrix cells."""
    implementation_name, case_name, metric_name = key
    return (implementation_name, case_name, metric_name)


def _compare_repeated_cell(
    key: _CellKey,
    baseline_rows: tuple[ParsedBenchmarkRow | None, ...],
    candidate_rows: tuple[ParsedBenchmarkRow | None, ...],
    *,
    environment_compatible: bool,
    regression_policy: RegressionPolicy,
    evidence_policy: EvidencePolicy,
) -> BenchmarkComparison:
    """Compare one matrix cell across repeated runs."""
    implementation_name, case_name, metric_name = key
    statistic, derived_key, direction, default_unit = _metric_policy(metric_name)
    threshold_percent = regression_policy.threshold_for(
        implementation_name,
        case_name,
        metric_name,
    )
    baseline_observed = tuple(row for row in baseline_rows if row is not None)
    candidate_observed = tuple(row for row in candidate_rows if row is not None)
    baseline_evidence = _analyze_evidence(baseline_rows, evidence_policy)
    candidate_evidence = _analyze_evidence(candidate_rows, evidence_policy)
    baseline_values = tuple(_row_value(row, derived_key) for row in baseline_observed)
    candidate_values = tuple(_row_value(row, derived_key) for row in candidate_observed)
    baseline_numeric_values = tuple(value for value in baseline_values if value is not None)
    candidate_numeric_values = tuple(value for value in candidate_values if value is not None)

    if not baseline_observed:
        return _missing_comparison(
            key,
            statistic=statistic,
            direction=direction,
            status="missing_baseline",
            value=_median_or_none(candidate_numeric_values),
            threshold_percent=threshold_percent,
            unit=_first_unit(candidate_observed, default_unit),
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )

    if not candidate_observed:
        return _missing_comparison(
            key,
            statistic=statistic,
            direction=direction,
            status="missing_candidate",
            value=_median_or_none(baseline_numeric_values),
            threshold_percent=threshold_percent,
            unit=_first_unit(baseline_observed, default_unit),
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )

    baseline_value = _median_or_none(baseline_numeric_values)
    candidate_value = _median_or_none(candidate_numeric_values)
    baseline_unit = _first_unit(baseline_observed, default_unit)
    candidate_unit = _first_unit(candidate_observed, default_unit)
    reason = _repeated_incompatibility_reason(
        (*baseline_observed, *candidate_observed),
        baseline_unit=baseline_unit,
        candidate_unit=candidate_unit,
    )
    if len(baseline_numeric_values) != len(baseline_observed) or len(candidate_numeric_values) != len(
        candidate_observed
    ):
        qualifier = "Both rows" if len(baseline_rows) == len(candidate_rows) == 1 else "Every row"
        reason = reason or f"{qualifier} must contain a finite {derived_key!r} derived value."

    if reason is not None or baseline_value is None or candidate_value is None:
        return BenchmarkComparison(
            implementation_name=implementation_name,
            case_name=case_name,
            metric_name=metric_name,
            statistic=statistic,
            direction=direction,
            status="incompatible",
            baseline_value=baseline_value,
            candidate_value=candidate_value,
            ratio=None,
            percent_change=None,
            improvement_percent=None,
            regression="not_comparable",
            threshold_percent=threshold_percent,
            unit=baseline_unit,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
            reason=reason or f"Both sides must contain a finite {derived_key!r} value.",
        )

    ratio = None if baseline_value == 0.0 else candidate_value / baseline_value
    percent_change = None if ratio is None else (ratio - 1.0) * 100.0
    improvement_percent = _directional_improvement(percent_change, direction)
    pairwise_improvements = _pairwise_improvements(
        baseline_numeric_values,
        candidate_numeric_values,
        direction=direction,
    )
    improvement_low = min(pairwise_improvements) if pairwise_improvements else None
    improvement_high = max(pairwise_improvements) if pairwise_improvements else None
    evidence_adequate = baseline_evidence.adequate and candidate_evidence.adequate
    regression = _classify_repeated_regression(
        improvement_percent,
        improvement_low=improvement_low,
        improvement_high=improvement_high,
        threshold_percent=threshold_percent,
        environment_compatible=environment_compatible,
        evidence_adequate=evidence_adequate,
    )
    comparison_reason = _classification_reason(
        regression,
        baseline_evidence=baseline_evidence,
        candidate_evidence=candidate_evidence,
        improvement_low=improvement_low,
        improvement_high=improvement_high,
        threshold_percent=threshold_percent,
    )

    return BenchmarkComparison(
        implementation_name=implementation_name,
        case_name=case_name,
        metric_name=metric_name,
        statistic=statistic,
        direction=direction,
        status="matched",
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        ratio=ratio,
        percent_change=percent_change,
        improvement_percent=improvement_percent,
        regression=regression,
        threshold_percent=threshold_percent,
        unit=baseline_unit,
        baseline_evidence=baseline_evidence,
        candidate_evidence=candidate_evidence,
        improvement_low_percent=improvement_low,
        improvement_high_percent=improvement_high,
        reason=comparison_reason,
    )


def _missing_comparison(
    key: _CellKey,
    *,
    statistic: str,
    direction: ComparisonDirection,
    status: Literal["missing_baseline", "missing_candidate"],
    value: float | None,
    threshold_percent: float,
    unit: str,
    baseline_evidence: BenchmarkEvidence,
    candidate_evidence: BenchmarkEvidence,
) -> BenchmarkComparison:
    """Build a comparison for a cell absent from one complete side."""
    implementation_name, case_name, metric_name = key
    missing_side = "baseline" if status == "missing_baseline" else "candidate"
    if baseline_evidence.provided_run_count == candidate_evidence.provided_run_count == 1:
        missing_reason = f"Matrix cell is absent from the {missing_side} run."
    else:
        missing_reason = f"Matrix cell is absent from every {missing_side} run."
    return BenchmarkComparison(
        implementation_name=implementation_name,
        case_name=case_name,
        metric_name=metric_name,
        statistic=statistic,
        direction=direction,
        status=status,
        baseline_value=None if status == "missing_baseline" else value,
        candidate_value=value if status == "missing_baseline" else None,
        ratio=None,
        percent_change=None,
        improvement_percent=None,
        regression="not_comparable",
        threshold_percent=threshold_percent,
        unit=unit,
        baseline_evidence=baseline_evidence,
        candidate_evidence=candidate_evidence,
        reason=missing_reason,
    )


def _analyze_evidence(
    rows: tuple[ParsedBenchmarkRow | None, ...],
    policy: EvidencePolicy,
) -> BenchmarkEvidence:
    """Compute trust diagnostics for one side of a matrix cell."""
    rounds = tuple(_positive_int_stat(row, "rounds") for row in rows)
    iterations = tuple(_positive_int_stat(row, "iterations") for row in rows)
    sample_counts = tuple(0 if row is None else len(row.samples) for row in rows)
    samples = tuple(sample for row in rows if row is not None for sample in row.samples)
    observed_indices = tuple(index for index, row in enumerate(rows) if row is not None)
    issues: list[str] = []

    if len(observed_indices) < policy.minimum_runs:
        issues.append(f"only {len(observed_indices)} run(s) contain the cell; {policy.minimum_runs} required")
    missing_count = len(rows) - len(observed_indices)
    if missing_count:
        issues.append(f"cell is missing from {missing_count} provided run(s)")

    for index in observed_indices:
        if sample_counts[index] < policy.minimum_samples_per_run:
            issues.append(
                f"run {index} has {sample_counts[index]} sample(s); " + f"{policy.minimum_samples_per_run} required"
            )
        if policy.require_rounds and rounds[index] is None:
            issues.append(f"run {index} does not report positive rounds")
        if policy.require_iterations and iterations[index] is None:
            issues.append(f"run {index} does not report positive iterations")

    iqr = _sample_iqr(samples)
    coefficient_of_variation = _coefficient_of_variation(samples)
    outlier_count = _tukey_outlier_count(samples)
    outlier_fraction = None if outlier_count is None or not samples else outlier_count / len(samples)
    if (
        policy.maximum_cv is not None
        and coefficient_of_variation is not None
        and coefficient_of_variation > policy.maximum_cv
    ):
        issues.append(f"coefficient of variation {coefficient_of_variation:.4f} exceeds " + f"{policy.maximum_cv:.4f}")
    if (
        policy.maximum_outlier_fraction is not None
        and outlier_fraction is not None
        and outlier_fraction > policy.maximum_outlier_fraction
    ):
        issues.append(f"outlier fraction {outlier_fraction:.4f} exceeds " + f"{policy.maximum_outlier_fraction:.4f}")

    return BenchmarkEvidence(
        provided_run_count=len(rows),
        observed_run_count=len(observed_indices),
        rounds=rounds,
        iterations=iterations,
        sample_counts=sample_counts,
        sample_count=len(samples),
        iqr=iqr,
        coefficient_of_variation=coefficient_of_variation,
        outlier_count=outlier_count,
        outlier_fraction=outlier_fraction,
        adequate=not issues,
        issues=tuple(issues),
    )


def _positive_int_stat(row: ParsedBenchmarkRow | None, key: str) -> int | None:
    """Return a positive integer row statistic when available."""
    if row is None:
        return None
    value = row.stats.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _sample_iqr(samples: Sequence[float]) -> float | None:
    """Return the pooled timing-sample interquartile range."""
    if len(samples) < 2:
        return None
    return _percentile(samples, 0.75) - _percentile(samples, 0.25)


def _coefficient_of_variation(samples: Sequence[float]) -> float | None:
    """Return pooled timing-sample population standard deviation over mean."""
    if len(samples) < 2:
        return None
    mean = statistics.fmean(samples)
    if mean == 0.0:
        return None
    return statistics.pstdev(samples, mu=mean) / abs(mean)


def _tukey_outlier_count(samples: Sequence[float]) -> int | None:
    """Count pooled timing samples outside the 1.5-IQR fences."""
    if len(samples) < 4:
        return None
    q1 = _percentile(samples, 0.25)
    q3 = _percentile(samples, 0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return sum(sample < lower or sample > upper for sample in samples)


def _percentile(values: Sequence[float], quantile: float) -> float:
    """Return a linearly interpolated percentile for non-empty values."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    upper_weight = position - lower_index
    return ordered[lower_index] * (1.0 - upper_weight) + ordered[upper_index] * upper_weight


def _median_or_none(values: Sequence[float]) -> float | None:
    """Return the median of finite per-run values."""
    return None if not values else float(statistics.median(values))


def _first_unit(rows: Sequence[ParsedBenchmarkRow], default: str) -> str:
    """Return the first observed comparison unit."""
    return default if not rows else _row_unit(rows[0], default)


def _repeated_incompatibility_reason(
    rows: Sequence[ParsedBenchmarkRow],
    *,
    baseline_unit: str,
    candidate_unit: str,
) -> str | None:
    """Return why any repeated row differs from the first row context."""
    if baseline_unit != candidate_unit:
        return f"Comparison units differ: {baseline_unit!r} != {candidate_unit!r}."
    reference = rows[0]
    reference_unit = _row_unit(reference, baseline_unit)
    for row in rows[1:]:
        reason = _incompatibility_reason(
            reference,
            row,
            baseline_unit=reference_unit,
            candidate_unit=_row_unit(row, baseline_unit),
        )
        if reason is not None:
            return reason
    return None


def _directional_improvement(
    percent_change: float | None,
    direction: ComparisonDirection,
) -> float | None:
    """Convert conventional percentage change into direction-aware improvement."""
    if percent_change is None:
        return None
    return -percent_change if direction == "lower_is_better" else percent_change


def _pairwise_improvements(
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    *,
    direction: ComparisonDirection,
) -> tuple[float, ...]:
    """Return every finite baseline/candidate pairwise improvement."""
    improvements: list[float] = []
    for baseline_value in baseline_values:
        if baseline_value == 0.0:
            continue
        for candidate_value in candidate_values:
            percent_change = (candidate_value / baseline_value - 1.0) * 100.0
            improvement = _directional_improvement(percent_change, direction)
            if improvement is not None and math.isfinite(improvement):
                improvements.append(improvement)
    return tuple(improvements)


def _classification_reason(
    regression: RegressionClassification,
    *,
    baseline_evidence: BenchmarkEvidence,
    candidate_evidence: BenchmarkEvidence,
    improvement_low: float | None,
    improvement_high: float | None,
    threshold_percent: float,
) -> str | None:
    """Explain evidence-driven inconclusive classifications."""
    if regression != "inconclusive":
        return None
    evidence_issues = (
        *(f"baseline: {issue}" for issue in baseline_evidence.issues),
        *(f"candidate: {issue}" for issue in candidate_evidence.issues),
    )
    if evidence_issues:
        return "Inadequate evidence: " + "; ".join(evidence_issues) + "."
    if improvement_low is not None and improvement_high is not None:
        return (
            "Repeated-run effects are not conclusive at the "
            + f"{threshold_percent:.2f}% threshold "
            + f"(pairwise range {improvement_low:+.2f}% to {improvement_high:+.2f}%)."
        )
    return "Repeated-run effects are not conclusive."


def _metric_policy(
    metric_name: MetricName,
) -> tuple[str, str, ComparisonDirection, str]:
    """Return statistic, derived key, direction, and default unit."""
    if metric_name == METRIC_SINGLE_CALL_LATENCY:
        return ("mean", DERIVED_LATENCY_MEAN, "lower_is_better", "seconds")
    if metric_name == METRIC_BATCH_THROUGHPUT:
        return ("mean", DERIVED_THROUGHPUT_MEAN, "higher_is_better", "")
    if metric_name == METRIC_TAIL_LATENCY:
        return ("p95", DERIVED_P95, "lower_is_better", "seconds")
    raise ValueError(f"Unsupported benchmatrix metric: {metric_name!r}")


def _row_value(row: ParsedBenchmarkRow | None, key: str) -> float | None:
    """Return one finite derived value from a row."""
    if row is None:
        return None
    value = row.derived.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric_value = float(value)
    return numeric_value if math.isfinite(numeric_value) else None


def _row_unit(row: ParsedBenchmarkRow | None, default: str) -> str:
    """Return the comparison unit for a row."""
    if row is None or row.metric_name != METRIC_BATCH_THROUGHPUT:
        return default
    unit = row.derived.get(DERIVED_THROUGHPUT_UNIT_LABEL)
    return unit if isinstance(unit, str) else default


def _incompatibility_reason(
    baseline: ParsedBenchmarkRow,
    candidate: ParsedBenchmarkRow,
    *,
    baseline_unit: str,
    candidate_unit: str,
) -> str | None:
    """Return why two rows cannot be compared, if their contexts differ."""
    if baseline_unit != candidate_unit:
        return f"Comparison units differ: {baseline_unit!r} != {candidate_unit!r}."

    context_keys = {key for key in set(baseline.extra_info) | set(candidate.extra_info) if key.startswith("case_")}
    context_keys.update(
        {
            KEY_CASE_FRESH_INPUTS,
            KEY_TAIL_PERCENTILES,
            KEY_THROUGHPUT_UNIT,
            KEY_WORK_UNIT_NAME,
            KEY_WORK_UNITS,
        }
    )

    changed_keys = [
        key
        for key in sorted(context_keys)
        if (key in baseline.extra_info) != (key in candidate.extra_info)
        or baseline.extra_info.get(key) != candidate.extra_info.get(key)
    ]
    if changed_keys:
        return f"Measurement context differs for metadata: {', '.join(changed_keys)}."

    return None


def _classify_repeated_regression(
    improvement_percent: float | None,
    *,
    improvement_low: float | None,
    improvement_high: float | None,
    threshold_percent: float,
    environment_compatible: bool,
    evidence_adequate: bool,
) -> RegressionClassification:
    """Classify an aggregate change only when repeated effects agree."""
    if improvement_percent is None or not environment_compatible:
        return "not_comparable"
    if not evidence_adequate or improvement_low is None or improvement_high is None:
        return "inconclusive"
    if math.isclose(abs(improvement_percent), threshold_percent, rel_tol=1e-12, abs_tol=1e-12):
        return "unchanged"
    if improvement_percent > threshold_percent:
        return "improved" if improvement_low > threshold_percent else "inconclusive"
    if improvement_percent < -threshold_percent:
        return "regressed" if improvement_high < -threshold_percent else "inconclusive"
    if improvement_low < -threshold_percent or improvement_high > threshold_percent:
        return "inconclusive"
    return "unchanged"


def _validate_run_group(
    runs: Sequence[BenchmarkRun],
    *,
    field_name: str,
) -> tuple[BenchmarkRun, ...]:
    """Validate and freeze one repeated-run group."""
    resolved = tuple(runs)
    if not resolved:
        raise ValueError(f"Benchmark {field_name} must contain at least one run.")
    for index, run in enumerate(resolved):
        if not isinstance(run, BenchmarkRun):
            raise TypeError(f"Benchmark {field_name}[{index}] must be a BenchmarkRun.")
    return resolved


def _compare_run_group_compatibility(
    baselines: tuple[BenchmarkRun, ...],
    candidates: tuple[BenchmarkRun, ...],
    *,
    policy: RunCompatibilityPolicy,
) -> RunCompatibilityReport:
    """Compare every repeated-run environment against one baseline anchor."""
    if policy.mode == "off":
        return RunCompatibilityReport(policy=policy, findings=(), pairs_checked=0)

    anchor = baselines[0]
    pairs: list[tuple[BenchmarkRun, BenchmarkRun, str, str]] = [
        (anchor, run, "baseline[0]", f"baseline[{index}]") for index, run in enumerate(baselines[1:], start=1)
    ]
    pairs.extend((anchor, run, "baseline[0]", f"candidate[{index}]") for index, run in enumerate(candidates))
    findings: list[RunCompatibilityFinding] = []
    for baseline, candidate, baseline_label, candidate_label in pairs:
        report = _compare_run_compatibility(
            baseline,
            candidate,
            policy=policy,
        )
        findings.extend(
            replace(
                finding,
                baseline_run=baseline_label,
                candidate_run=candidate_label,
            )
            for finding in report.findings
        )
    return RunCompatibilityReport(
        policy=policy,
        findings=tuple(findings),
        pairs_checked=len(pairs),
    )


def _compare_run_compatibility(
    baseline: BenchmarkRun,
    candidate: BenchmarkRun,
    *,
    policy: RunCompatibilityPolicy,
) -> RunCompatibilityReport:
    """Compare normalized run-environment metadata."""
    if policy.mode == "off":
        return RunCompatibilityReport(policy=policy, findings=())

    baseline_machine = _mapping_value(baseline.metadata.get("machine_info"))
    candidate_machine = _mapping_value(candidate.metadata.get("machine_info"))
    findings: list[RunCompatibilityFinding] = []

    if baseline_machine is None or candidate_machine is None:
        findings.append(
            _make_compatibility_finding(
                field="machine_info",
                baseline_value=baseline.metadata.get("machine_info"),
                candidate_value=candidate.metadata.get("machine_info"),
                permissive_severity="warning",
                policy=policy,
                reason="Complete machine metadata is unavailable for one or both runs.",
            )
        )
        return RunCompatibilityReport(policy=policy, findings=tuple(findings))

    _compare_python_version(
        baseline_machine,
        candidate_machine,
        policy=policy,
        findings=findings,
    )

    field_specs: tuple[tuple[str, tuple[str, ...], CompatibilitySeverity], ...] = (
        ("os.system", ("system",), "blocking"),
        ("architecture", ("machine",), "blocking"),
        ("python.implementation", ("python_implementation",), "blocking"),
        ("cpu.bits", ("cpu", "bits"), "blocking"),
        ("cpu.brand", ("cpu", "brand_raw"), "blocking"),
        ("cpu.vendor", ("cpu", "vendor_id_raw"), "warning"),
        ("cpu.flags", ("cpu", "flags"), "warning"),
        ("os.release", ("release",), "warning"),
        ("python.compiler", ("python_compiler",), "warning"),
        ("cpu.count", ("cpu", "count"), "warning"),
    )
    for field_name, path, severity in field_specs:
        _compare_environment_field(
            field_name,
            _nested_value(baseline_machine, path),
            _nested_value(candidate_machine, path),
            permissive_severity=severity,
            policy=policy,
            findings=findings,
        )

    _compare_environment_field(
        "pytest_benchmark.version",
        baseline.metadata.get("version", _MISSING),
        candidate.metadata.get("version", _MISSING),
        permissive_severity="warning",
        policy=policy,
        findings=findings,
    )
    _compare_environment_field(
        "dependencies",
        baseline.metadata.get("dependencies", _MISSING),
        candidate.metadata.get("dependencies", _MISSING),
        permissive_severity="warning",
        policy=policy,
        findings=findings,
        required_in_strict=False,
    )

    return RunCompatibilityReport(policy=policy, findings=tuple(findings))


def _compare_python_version(
    baseline_machine: Mapping[str, object],
    candidate_machine: Mapping[str, object],
    *,
    policy: RunCompatibilityPolicy,
    findings: list[RunCompatibilityFinding],
) -> None:
    """Compare Python versions with patch-level awareness."""
    baseline_value = baseline_machine.get("python_version", _MISSING)
    candidate_value = candidate_machine.get("python_version", _MISSING)
    if baseline_value is _MISSING and candidate_value is _MISSING:
        if policy.mode == "strict":
            findings.append(
                _make_compatibility_finding(
                    field="python.version",
                    baseline_value=None,
                    candidate_value=None,
                    permissive_severity="warning",
                    policy=policy,
                    reason="Python version metadata is missing from both runs.",
                )
            )
        return
    if baseline_value is _MISSING or candidate_value is _MISSING:
        findings.append(
            _make_compatibility_finding(
                field="python.version",
                baseline_value=_public_value(baseline_value),
                candidate_value=_public_value(candidate_value),
                permissive_severity="warning",
                policy=policy,
                reason="Python version metadata is missing from one run.",
            )
        )
        return
    if baseline_value == candidate_value:
        return

    baseline_release = _python_release(baseline_value)
    candidate_release = _python_release(candidate_value)
    severity: CompatibilitySeverity = "blocking"
    reason = "Python versions differ and cannot be normalized safely."
    if baseline_release is not None and candidate_release is not None:
        if baseline_release[:2] == candidate_release[:2]:
            severity = "warning"
            reason = "Python patch versions differ."
        else:
            reason = "Python major or minor versions differ."

    findings.append(
        _make_compatibility_finding(
            field="python.version",
            baseline_value=baseline_value,
            candidate_value=candidate_value,
            permissive_severity=severity,
            policy=policy,
            reason=reason,
        )
    )


def _compare_environment_field(
    field_name: str,
    baseline_value: object,
    candidate_value: object,
    *,
    permissive_severity: CompatibilitySeverity,
    policy: RunCompatibilityPolicy,
    findings: list[RunCompatibilityFinding],
    required_in_strict: bool = True,
) -> None:
    """Append a compatibility finding for one normalized field."""
    if baseline_value is _MISSING and candidate_value is _MISSING:
        if policy.mode == "strict" and required_in_strict:
            findings.append(
                _make_compatibility_finding(
                    field=field_name,
                    baseline_value=None,
                    candidate_value=None,
                    permissive_severity="warning",
                    policy=policy,
                    reason=f"{field_name} metadata is missing from both runs.",
                )
            )
        return
    if baseline_value is _MISSING or candidate_value is _MISSING:
        findings.append(
            _make_compatibility_finding(
                field=field_name,
                baseline_value=_public_value(baseline_value),
                candidate_value=_public_value(candidate_value),
                permissive_severity="warning",
                policy=policy,
                reason=f"{field_name} metadata is missing from one run.",
            )
        )
        return

    normalized_baseline = _normalize_environment_value(field_name, baseline_value)
    normalized_candidate = _normalize_environment_value(field_name, candidate_value)
    if normalized_baseline == normalized_candidate:
        return

    findings.append(
        _make_compatibility_finding(
            field=field_name,
            baseline_value=baseline_value,
            candidate_value=candidate_value,
            permissive_severity=permissive_severity,
            policy=policy,
            reason=f"{field_name} differs between runs.",
        )
    )


def _make_compatibility_finding(
    *,
    field: str,
    baseline_value: object | None,
    candidate_value: object | None,
    permissive_severity: CompatibilitySeverity,
    policy: RunCompatibilityPolicy,
    reason: str,
) -> RunCompatibilityFinding:
    """Build a finding and promote warnings under strict policy."""
    severity: CompatibilitySeverity = "blocking" if policy.mode == "strict" else permissive_severity
    return RunCompatibilityFinding(
        field=field,
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        severity=severity,
        reason=reason,
    )


def _mapping_value(value: object) -> Mapping[str, object] | None:
    """Return a string-keyed mapping when available."""
    if not isinstance(value, Mapping):
        return None
    if any(not isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _nested_value(mapping: Mapping[str, object], path: Sequence[str]) -> object:
    """Read one nested environment value."""
    current: object = mapping
    for key in path:
        current_mapping = _mapping_value(current)
        if current_mapping is None or key not in current_mapping:
            return _MISSING
        current = current_mapping[key]
    return current


def _normalize_environment_value(field_name: str, value: object) -> object:
    """Normalize aliases and order-insensitive environment values."""
    if field_name == "architecture" and isinstance(value, str):
        architecture = value.casefold().replace("-", "_")
        aliases = {
            "amd64": "x86_64",
            "x64": "x86_64",
            "arm64": "aarch64",
        }
        return aliases.get(architecture, architecture)
    if field_name in {"os.system", "python.implementation"} and isinstance(value, str):
        return value.casefold()
    if field_name == "cpu.flags" and isinstance(value, list):
        return tuple(sorted(str(item) for item in value))
    return value


def _python_release(value: object) -> tuple[int, int, int] | None:
    """Extract a three-part Python release tuple."""
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch or 0))


def _public_value(value: object) -> object | None:
    """Convert the internal missing sentinel to a public value."""
    return None if value is _MISSING else value


def _validate_threshold(value: object, *, field_name: str) -> float:
    """Validate a finite, non-negative percentage threshold."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a numeric percentage.")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"{field_name} must be finite.")
    if numeric_value < 0.0:
        raise ValueError(f"{field_name} must not be negative.")
    return numeric_value


def _validate_fraction(value: object, *, field_name: str) -> float:
    """Validate a finite fraction between zero and one."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be numeric.")
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or not 0.0 <= numeric_value <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0.")
    return numeric_value


def _validate_non_negative_number(value: object, *, field_name: str) -> float:
    """Validate a finite non-negative numeric value."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be numeric.")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"{field_name} must be finite.")
    if numeric_value < 0.0:
        raise ValueError(f"{field_name} must not be negative.")
    return numeric_value


def _validate_selector_name(value: object, *, field_name: str) -> str:
    """Validate an implementation or case selector."""
    if not isinstance(value, str):
        raise TypeError(f"Regression policy {field_name} selector must be a string.")
    if not value:
        raise ValueError(f"Regression policy {field_name} selector must not be empty.")
    return value


def _validate_metric_key(value: object) -> MetricName:
    """Validate a regression-policy metric key."""
    if not isinstance(value, str) or value not in KNOWN_METRICS:
        raise ValueError(f"Unsupported regression policy metric: {value!r}.")
    return cast(MetricName, value)


def _validate_cell_key(value: object) -> _CellKey:
    """Validate an exact regression-policy matrix-cell key."""
    if not isinstance(value, tuple) or len(value) != 3:
        raise TypeError("Regression policy cell keys must be (implementation, case, metric) tuples.")
    implementation_name = _validate_selector_name(value[0], field_name="implementation")
    case_name = _validate_selector_name(value[1], field_name="case")
    metric_name = _validate_metric_key(value[2])
    return (implementation_name, case_name, metric_name)
