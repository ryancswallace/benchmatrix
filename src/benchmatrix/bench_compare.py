"""Matrix-aware comparison of parsed benchmark runs."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from hashlib import sha256
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
from .bench_statistics import (
    PrecisionPlan,
    bootstrap_median_ratio_interval,
    bootstrap_paired_median_ratio_interval,
    plan_paired_precision,
)

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
InferenceMethod: TypeAlias = Literal["bca_bootstrap", "legacy_consistency"]
IntervalMethod: TypeAlias = Literal["bca_bootstrap", "percentile_bootstrap"]
MultiplicityCorrection: TypeAlias = Literal["bonferroni", "none"]
ComparisonDesign: TypeAlias = Literal["independent", "paired"]

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
        minimum_rounds_per_run: Minimum pytest-benchmark rounds required from
            each observed file.
        require_rounds: Whether every row must report a positive round count.
        require_iterations: Whether every row must report a positive iteration
            count.
        require_raw_samples_for_inference: Whether every observed row must
            retain raw per-round durations.
        minimum_tail_samples_per_run: Minimum round-duration observations
            required from each tail-latency row.
        require_tail_iterations_one: Whether tail-latency rows must represent
            individual calls rather than averages of multiple iterations.
        maximum_cv: Optional maximum within-run coefficient of variation.
        maximum_outlier_fraction: Optional maximum within-run Tukey-outlier
            fraction.
    """

    minimum_runs: int = 5
    minimum_samples_per_run: int = 5
    minimum_rounds_per_run: int = 5
    require_rounds: bool = True
    require_iterations: bool = True
    require_raw_samples_for_inference: bool = True
    minimum_tail_samples_per_run: int = 100
    require_tail_iterations_one: bool = True
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
        if isinstance(self.minimum_rounds_per_run, bool) or not isinstance(self.minimum_rounds_per_run, int):
            raise TypeError("EvidencePolicy.minimum_rounds_per_run must be an integer.")
        if self.minimum_rounds_per_run < 0:
            raise ValueError("EvidencePolicy.minimum_rounds_per_run must be a non-negative integer.")
        if not isinstance(self.require_rounds, bool):
            raise TypeError("EvidencePolicy.require_rounds must be a boolean.")
        if not isinstance(self.require_iterations, bool):
            raise TypeError("EvidencePolicy.require_iterations must be a boolean.")
        if not isinstance(self.require_raw_samples_for_inference, bool):
            raise TypeError("EvidencePolicy.require_raw_samples_for_inference must be a boolean.")
        if isinstance(self.minimum_tail_samples_per_run, bool) or not isinstance(
            self.minimum_tail_samples_per_run, int
        ):
            raise TypeError("EvidencePolicy.minimum_tail_samples_per_run must be an integer.")
        if self.minimum_tail_samples_per_run < 0:
            raise ValueError("EvidencePolicy.minimum_tail_samples_per_run must be a non-negative integer.")
        if not isinstance(self.require_tail_iterations_one, bool):
            raise TypeError("EvidencePolicy.require_tail_iterations_one must be a boolean.")
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
        iqr: Interquartile range of pooled timing samples in seconds. Retained
            as a descriptive compatibility field; evidence gates use the
            corresponding per-run diagnostics.
        coefficient_of_variation: Pooled timing-sample population standard
            deviation divided by the absolute mean.
        outlier_count: Samples outside the pooled 1.5-IQR Tukey fences.
        outlier_fraction: Outlier count divided by total sample count.
        adequate: Whether the configured evidence policy was satisfied.
        issues: Human-readable reasons evidence is inadequate.
        run_iqrs: Per-run timing-sample interquartile ranges.
        run_coefficients_of_variation: Per-run coefficients of variation.
        run_outlier_counts: Per-run Tukey-outlier counts.
        run_outlier_fractions: Per-run Tukey-outlier fractions.
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
    run_iqrs: tuple[float | None, ...] = ()
    run_coefficients_of_variation: tuple[float | None, ...] = ()
    run_outlier_counts: tuple[int | None, ...] = ()
    run_outlier_fractions: tuple[float | None, ...] = ()


@dataclass(frozen=True, slots=True)
class InferencePolicy:
    """Policy controlling run-level statistical inference.

    The default method bootstraps complete process-run statistics, applies a
    BCa interval, and uses a Bonferroni-adjusted simultaneous confidence level
    across the reported matrix. ``legacy_consistency`` preserves the version 1
    observed-pairwise-range decision rule and is intentionally non-inferential.
    """

    method: InferenceMethod = "bca_bootstrap"
    confidence_level: float = 0.95
    resamples: int = 50_000
    random_seed: int = 0
    multiplicity: MultiplicityCorrection = "bonferroni"

    def __post_init__(self) -> None:
        """Validate inference controls."""
        if self.method not in {"bca_bootstrap", "legacy_consistency"}:
            raise ValueError(f"Unsupported inference method: {self.method!r}.")
        confidence_level = _validate_fraction(
            self.confidence_level,
            field_name="InferencePolicy.confidence_level",
        )
        if confidence_level in {0.0, 1.0}:
            raise ValueError("InferencePolicy.confidence_level must be between zero and one.")
        if isinstance(self.resamples, bool) or not isinstance(self.resamples, int):
            raise TypeError("InferencePolicy.resamples must be an integer.")
        if self.resamples < 1_000:
            raise ValueError("InferencePolicy.resamples must be at least 1000.")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise TypeError("InferencePolicy.random_seed must be an integer.")
        if self.random_seed < 0:
            raise ValueError("InferencePolicy.random_seed must be non-negative.")
        if self.multiplicity not in {"bonferroni", "none"}:
            raise ValueError(f"Unsupported multiplicity correction: {self.multiplicity!r}.")
        object.__setattr__(self, "confidence_level", confidence_level)


@dataclass(frozen=True, slots=True)
class PrecisionPolicy:
    """Optional fixed-design precision target for paired pilot comparisons.

    ``target_half_width_percent=None`` disables planning. When enabled, each
    paired matrix cell estimates the pair count for a fresh future collection;
    the pilot comparison and its pass/fail decision are never changed by the
    plan.
    """

    target_half_width_percent: float | None = None

    def __post_init__(self) -> None:
        """Validate and normalize the optional percentage target."""
        if self.target_half_width_percent is None:
            return
        target = _validate_non_negative_number(
            self.target_half_width_percent,
            field_name="PrecisionPolicy.target_half_width_percent",
        )
        if target == 0.0:
            raise ValueError("PrecisionPolicy.target_half_width_percent must be positive when enabled.")
        object.__setattr__(self, "target_half_width_percent", target)

    @property
    def enabled(self) -> bool:
        """Return whether paired precision planning is requested."""
        return self.target_half_width_percent is not None


@dataclass(frozen=True, slots=True)
class BenchmarkInference:
    """Statistical inference for one benchmark matrix cell."""

    method: IntervalMethod
    estimand: str
    design: ComparisonDesign
    confidence_level: float
    adjusted_confidence_level: float
    multiplicity: MultiplicityCorrection
    family_size: int
    resamples: int
    random_seed: int
    estimate_percent: float | None
    confidence_low_percent: float | None
    confidence_high_percent: float | None
    warnings: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    pair_count: int | None = None
    strata_count: int | None = None

    def __post_init__(self) -> None:
        """Validate and normalize an inference result."""
        if self.method not in {"bca_bootstrap", "percentile_bootstrap"}:
            raise ValueError(f"Unsupported interval method: {self.method!r}.")
        if self.design not in {"independent", "paired"}:
            raise ValueError(f"Unsupported inference design: {self.design!r}.")
        if not isinstance(self.estimand, str) or not self.estimand:
            raise ValueError("BenchmarkInference.estimand must be a non-empty string.")
        confidence_level = _validate_fraction(
            self.confidence_level,
            field_name="BenchmarkInference.confidence_level",
        )
        adjusted_confidence_level = _validate_fraction(
            self.adjusted_confidence_level,
            field_name="BenchmarkInference.adjusted_confidence_level",
        )
        if confidence_level in {0.0, 1.0} or adjusted_confidence_level in {0.0, 1.0}:
            raise ValueError("BenchmarkInference confidence levels must be between zero and one.")
        if adjusted_confidence_level < confidence_level:
            raise ValueError("Adjusted confidence level must not be lower than the nominal confidence level.")
        if self.multiplicity not in {"bonferroni", "none"}:
            raise ValueError(f"Unsupported multiplicity correction: {self.multiplicity!r}.")
        if isinstance(self.family_size, bool) or not isinstance(self.family_size, int) or self.family_size <= 0:
            raise ValueError("BenchmarkInference.family_size must be a positive integer.")
        if isinstance(self.resamples, bool) or not isinstance(self.resamples, int):
            raise TypeError("BenchmarkInference.resamples must be an integer.")
        if self.resamples < 1_000:
            raise ValueError("BenchmarkInference.resamples must be at least 1000.")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise TypeError("BenchmarkInference.random_seed must be an integer.")
        if self.random_seed < 0:
            raise ValueError("BenchmarkInference.random_seed must be non-negative.")
        if self.design == "independent" and (self.pair_count is not None or self.strata_count is not None):
            raise ValueError("Independent inference must not define paired-design counts.")
        if self.design == "paired" and (
            isinstance(self.pair_count, bool) or not isinstance(self.pair_count, int) or self.pair_count <= 0
        ):
            raise ValueError("Paired inference requires a positive integer pair_count.")
        if self.design == "paired" and (
            isinstance(self.strata_count, bool)
            or not isinstance(self.strata_count, int)
            or self.strata_count <= 0
            or self.pair_count is None
            or self.strata_count > self.pair_count
        ):
            raise ValueError("Paired inference requires a valid positive strata_count no greater than pair_count.")
        for field_name, value in (
            ("estimate_percent", self.estimate_percent),
            ("confidence_low_percent", self.confidence_low_percent),
            ("confidence_high_percent", self.confidence_high_percent),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"BenchmarkInference.{field_name} must be finite or None.")
        present = (
            self.estimate_percent is not None,
            self.confidence_low_percent is not None,
            self.confidence_high_percent is not None,
        )
        if any(present) and not all(present):
            raise ValueError("BenchmarkInference estimate and confidence bounds must be present together.")
        if (
            self.confidence_low_percent is not None
            and self.confidence_high_percent is not None
            and self.confidence_low_percent > self.confidence_high_percent
        ):
            raise ValueError("BenchmarkInference confidence bounds are reversed.")
        warnings = tuple(self.warnings)
        issues = tuple(self.issues)
        if any(not isinstance(item, str) or not item for item in (*warnings, *issues)):
            raise ValueError("BenchmarkInference warnings and issues must contain non-empty strings.")
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "confidence_level", confidence_level)
        object.__setattr__(self, "adjusted_confidence_level", adjusted_confidence_level)

    @property
    def adequate(self) -> bool:
        """Return whether a complete confidence interval is available."""
        return not self.issues and self.confidence_low_percent is not None and self.confidence_high_percent is not None


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
    inference: BenchmarkInference | None = None
    precision: PrecisionPlan | None = None


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
    inference_policy: InferencePolicy = field(default_factory=InferencePolicy)
    design: ComparisonDesign = "independent"
    precision_policy: PrecisionPolicy = field(default_factory=PrecisionPolicy)

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
    inference_policy: InferencePolicy | None = None,
    precision_policy: PrecisionPolicy | None = None,
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
        inference_policy: Run-level uncertainty analysis to apply. A single
            run cannot produce a default bootstrap interval and is therefore
            inconclusive unless the legacy method is selected explicitly.
        precision_policy: Optional precision planning. Planning requires an
            explicitly paired design and is rejected for this single-run API.

    Returns:
        A deterministic comparison across both run matrices.
    """
    return compare_benchmark_run_groups(
        (baseline,),
        (candidate,),
        compatibility_policy=compatibility_policy,
        regression_policy=regression_policy,
        inference_policy=inference_policy,
        precision_policy=precision_policy,
        evidence_policy=EvidencePolicy(
            minimum_runs=1,
            minimum_samples_per_run=0,
            minimum_rounds_per_run=0,
            require_rounds=False,
            require_iterations=False,
            require_raw_samples_for_inference=False,
            minimum_tail_samples_per_run=0,
            require_tail_iterations_one=False,
        ),
    )


def compare_benchmark_run_groups(
    baselines: Sequence[BenchmarkRun],
    candidates: Sequence[BenchmarkRun],
    *,
    compatibility_policy: RunCompatibilityPolicy | None = None,
    regression_policy: RegressionPolicy | None = None,
    evidence_policy: EvidencePolicy | None = None,
    inference_policy: InferencePolicy | None = None,
    precision_policy: PrecisionPolicy | None = None,
) -> BenchmarkRunComparison:
    """Compare repeated baseline and candidate runs as two evidence groups.

    Each cell uses the median of its per-run metric values. By default,
    run-level BCa bootstrap intervals quantify uncertainty and a Bonferroni
    adjustment controls the matrix-wide family-wise error rate. Practical
    thresholds then distinguish improvements, regressions, equivalence, and
    inconclusive intervals.

    Args:
        baselines: Repeated reference benchmark runs.
        candidates: Repeated candidate benchmark runs.
        compatibility_policy: Environment checks applied across every run.
        regression_policy: Percentage thresholds for classifying changes.
        evidence_policy: Minimum repeated-run and sample evidence.
        inference_policy: Statistical inference and multiplicity controls.
        precision_policy: Optional paired fixed-design planning target. It
            must remain disabled for independent groups.

    Returns:
        A matrix comparison with per-side trust diagnostics.

    Raises:
        ValueError: If either run group is empty.
        TypeError: If a group contains a value other than ``BenchmarkRun``.
    """
    return _compare_benchmark_run_groups(
        baselines,
        candidates,
        compatibility_policy=compatibility_policy,
        regression_policy=regression_policy,
        evidence_policy=evidence_policy,
        inference_policy=inference_policy,
        precision_policy=precision_policy,
        design="independent",
    )


def compare_paired_benchmark_run_groups(
    baselines: Sequence[BenchmarkRun],
    candidates: Sequence[BenchmarkRun],
    *,
    pair_strata: Sequence[str] | None = None,
    precision_pair_count_multiple: int = 2,
    compatibility_policy: RunCompatibilityPolicy | None = None,
    regression_policy: RegressionPolicy | None = None,
    evidence_policy: EvidencePolicy | None = None,
    inference_policy: InferencePolicy | None = None,
    precision_policy: PrecisionPolicy | None = None,
) -> BenchmarkRunComparison:
    """Compare explicitly matched baseline/candidate process-run pairs.

    The values at each position must come from one adjacent collection block.
    Complete pairs, rather than individual run files, are the independent
    experimental units. Pairing is explicit in this API and is never inferred
    from filenames or timestamps.

    Args:
        baselines: Baseline members in pair order.
        candidates: Candidate members in the same pair order.
        pair_strata: Optional fixed-design stratum label for each pair, such
            as its recorded ``AB`` or ``BA`` command orientation. When given,
            paired resampling preserves the observed count in every stratum.
        precision_pair_count_multiple: Divisibility constraint for a future
            confirmatory collection. Paired designs default to an even count;
            manifest-backed collections pass their complete joint design
            supercycle.
        compatibility_policy: Environment checks applied across every run.
        regression_policy: Percentage thresholds for classifying changes.
        evidence_policy: Minimum complete-pair and sample evidence.
        inference_policy: Statistical inference and multiplicity controls.
        precision_policy: Optional fixed-design precision target for a fresh
            future paired collection.

    Returns:
        A paired matrix comparison with per-side trust diagnostics.

    Raises:
        ValueError: If the sequences are empty or have different lengths.
        TypeError: If either sequence contains a non-``BenchmarkRun`` value.
    """
    if len(baselines) != len(candidates):
        raise ValueError("Paired baseline and candidate groups must contain the same number of runs.")
    return _compare_benchmark_run_groups(
        baselines,
        candidates,
        compatibility_policy=compatibility_policy,
        regression_policy=regression_policy,
        evidence_policy=evidence_policy,
        inference_policy=inference_policy,
        precision_policy=precision_policy,
        design="paired",
        pair_strata=pair_strata,
        precision_pair_count_multiple=precision_pair_count_multiple,
    )


def _compare_benchmark_run_groups(
    baselines: Sequence[BenchmarkRun],
    candidates: Sequence[BenchmarkRun],
    *,
    compatibility_policy: RunCompatibilityPolicy | None,
    regression_policy: RegressionPolicy | None,
    evidence_policy: EvidencePolicy | None,
    inference_policy: InferencePolicy | None,
    precision_policy: PrecisionPolicy | None,
    design: ComparisonDesign,
    pair_strata: Sequence[str] | None = None,
    precision_pair_count_multiple: int = 1,
) -> BenchmarkRunComparison:
    """Implement independent or explicitly paired repeated-run inference."""
    baseline_runs = _validate_run_group(baselines, field_name="baselines")
    candidate_runs = _validate_run_group(candidates, field_name="candidates")
    resolved_compatibility_policy = compatibility_policy or RunCompatibilityPolicy()
    resolved_regression_policy = regression_policy or RegressionPolicy()
    resolved_evidence_policy = evidence_policy or EvidencePolicy()
    resolved_inference_policy = inference_policy or InferencePolicy()
    resolved_precision_policy = precision_policy or PrecisionPolicy()
    resolved_pair_strata = _validate_pair_strata(
        pair_strata,
        pair_count=len(baseline_runs),
        design=design,
    )
    if (
        isinstance(precision_pair_count_multiple, bool)
        or not isinstance(precision_pair_count_multiple, int)
        or precision_pair_count_multiple <= 0
    ):
        raise ValueError("precision_pair_count_multiple must be a positive integer.")
    if design == "paired" and precision_pair_count_multiple % 2 != 0:
        raise ValueError("precision_pair_count_multiple must preserve an even AB/BA allocation.")
    if design == "independent" and resolved_precision_policy.enabled:
        raise ValueError("Precision planning requires an explicitly paired comparison design.")
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
    family_size = sum(
        _is_inference_family_member(
            key,
            tuple(rows.get(key) for rows in baseline_maps),
            tuple(rows.get(key) for rows in candidate_maps),
            environment_compatible=compatibility.is_compatible,
            design=design,
        )
        for key in keys
    )
    # Inference is skipped when the family is empty, but each result object
    # still requires a positive recorded family size.
    recorded_family_size = max(1, family_size)
    comparisons = tuple(
        _compare_repeated_cell(
            key,
            tuple(rows.get(key) for rows in baseline_maps),
            tuple(rows.get(key) for rows in candidate_maps),
            environment_compatible=compatibility.is_compatible,
            regression_policy=resolved_regression_policy,
            evidence_policy=resolved_evidence_policy,
            inference_policy=resolved_inference_policy,
            family_size=recorded_family_size,
            design=design,
            precision_policy=resolved_precision_policy,
            pair_strata=resolved_pair_strata,
            precision_pair_count_multiple=precision_pair_count_multiple,
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
        inference_policy=resolved_inference_policy,
        design=design,
        precision_policy=resolved_precision_policy,
    )


def _row_key(row: ParsedBenchmarkRow) -> _CellKey:
    """Return the matrix identity for a parsed row."""
    return (row.implementation_name, row.case_name, row.metric_name)


def _sort_key(key: _CellKey) -> tuple[str, str, str]:
    """Return a stable ordering key for matrix cells."""
    implementation_name, case_name, metric_name = key
    return (implementation_name, case_name, metric_name)


def _is_inference_family_member(
    key: _CellKey,
    baseline_rows: tuple[ParsedBenchmarkRow | None, ...],
    candidate_rows: tuple[ParsedBenchmarkRow | None, ...],
    *,
    environment_compatible: bool,
    design: ComparisonDesign,
) -> bool:
    """Return whether a cell defines a structurally valid hypothesis."""
    if not environment_compatible:
        return False
    if design == "paired" and any(
        baseline_row is None or candidate_row is None
        for baseline_row, candidate_row in zip(baseline_rows, candidate_rows, strict=True)
    ):
        return False
    metric_name = key[2]
    _, derived_key, _, default_unit = _metric_policy(metric_name)
    baseline_observed = tuple(row for row in baseline_rows if row is not None)
    candidate_observed = tuple(row for row in candidate_rows if row is not None)
    if not baseline_observed or not candidate_observed:
        return False
    values = tuple(_row_value(row, derived_key) for row in (*baseline_observed, *candidate_observed))
    if any(value is None or value <= 0.0 for value in values):
        return False
    baseline_unit = _first_unit(baseline_observed, default_unit)
    candidate_unit = _first_unit(candidate_observed, default_unit)
    return (
        _repeated_incompatibility_reason(
            (*baseline_observed, *candidate_observed),
            baseline_unit=baseline_unit,
            candidate_unit=candidate_unit,
        )
        is None
    )


def _compare_repeated_cell(
    key: _CellKey,
    baseline_rows: tuple[ParsedBenchmarkRow | None, ...],
    candidate_rows: tuple[ParsedBenchmarkRow | None, ...],
    *,
    environment_compatible: bool,
    regression_policy: RegressionPolicy,
    evidence_policy: EvidencePolicy,
    inference_policy: InferencePolicy,
    family_size: int,
    design: ComparisonDesign,
    precision_policy: PrecisionPolicy,
    pair_strata: tuple[str, ...] | None,
    precision_pair_count_multiple: int,
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
    baseline_evidence = _analyze_evidence(baseline_rows, evidence_policy, metric_name=metric_name)
    candidate_evidence = _analyze_evidence(candidate_rows, evidence_policy, metric_name=metric_name)
    baseline_values = tuple(_row_value(row, derived_key) for row in baseline_observed)
    candidate_values = tuple(_row_value(row, derived_key) for row in candidate_observed)
    baseline_numeric_values = tuple(value for value in baseline_values if value is not None)
    candidate_numeric_values = tuple(value for value in candidate_values if value is not None)
    paired_numeric_values = (
        tuple(
            (baseline_value, candidate_value)
            for baseline_row, candidate_row in zip(baseline_rows, candidate_rows, strict=True)
            if baseline_row is not None
            and candidate_row is not None
            and (baseline_value := _row_value(baseline_row, derived_key)) is not None
            and (candidate_value := _row_value(candidate_row, derived_key)) is not None
        )
        if design == "paired"
        else ()
    )
    inference_baseline_values = (
        tuple(value[0] for value in paired_numeric_values) if design == "paired" else baseline_numeric_values
    )
    inference_candidate_values = (
        tuple(value[1] for value in paired_numeric_values) if design == "paired" else candidate_numeric_values
    )

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

    baseline_value = _median_or_none(inference_baseline_values)
    candidate_value = _median_or_none(inference_candidate_values)
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
    if design == "paired" and len(paired_numeric_values) != len(baseline_rows):
        reason = reason or "Paired inference requires this cell in both members of every complete run pair."

    if reason is None and any(value <= 0.0 for value in (*baseline_numeric_values, *candidate_numeric_values)):
        reason = f"Every row must contain a positive {derived_key!r} derived value for ratio inference."

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
    pairwise_improvements = _observed_improvements(
        inference_baseline_values,
        inference_candidate_values,
        direction=direction,
        design=design,
    )
    improvement_low = min(pairwise_improvements) if pairwise_improvements else None
    improvement_high = max(pairwise_improvements) if pairwise_improvements else None
    evidence_adequate = baseline_evidence.adequate and candidate_evidence.adequate
    inference: BenchmarkInference | None = None
    if inference_policy.method == "legacy_consistency":
        regression = _classify_repeated_regression(
            improvement_percent,
            improvement_low=improvement_low,
            improvement_high=improvement_high,
            threshold_percent=threshold_percent,
            environment_compatible=environment_compatible,
            evidence_adequate=evidence_adequate,
        )
    elif not environment_compatible:
        regression = "not_comparable"
    else:
        inference = _infer_repeated_effect(
            key,
            inference_baseline_values,
            inference_candidate_values,
            direction=direction,
            family_size=family_size,
            evidence_adequate=evidence_adequate,
            policy=inference_policy,
            design=design,
            pair_strata=pair_strata,
        )
        regression = _classify_inference(
            inference,
            threshold_percent=threshold_percent,
        )
    precision: PrecisionPlan | None = None
    precision_target = precision_policy.target_half_width_percent
    if design == "paired" and precision_target is not None:
        precision = plan_paired_precision(
            inference_baseline_values,
            inference_candidate_values,
            lower_is_better=direction == "lower_is_better",
            target_half_width_percent=precision_target,
            confidence_level=inference_policy.confidence_level,
            family_size=family_size,
            multiplicity=inference_policy.multiplicity,
            strata=pair_strata,
            minimum_pairs=evidence_policy.minimum_runs,
            pair_count_multiple=precision_pair_count_multiple,
        )
        if not environment_compatible:
            precision = replace(
                precision,
                critical_value=None,
                unconstrained_required_pairs=None,
                required_pairs=None,
                additional_pairs=None,
                issues=(
                    *precision.issues,
                    "run-environment compatibility was blocked; precision planning is unavailable",
                ),
            )
        if not evidence_adequate:
            precision = replace(
                precision,
                warnings=(
                    *precision.warnings,
                    "The pilot does not satisfy the evidence policy; treat this planning estimate as provisional.",
                ),
            )
    comparison_reason = _classification_reason(
        regression,
        baseline_evidence=baseline_evidence,
        candidate_evidence=candidate_evidence,
        improvement_low=improvement_low,
        improvement_high=improvement_high,
        threshold_percent=threshold_percent,
        inference=inference,
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
        inference=inference,
        precision=precision,
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
    *,
    metric_name: MetricName,
) -> BenchmarkEvidence:
    """Compute trust diagnostics for one side of a matrix cell."""
    rounds = tuple(_positive_int_stat(row, "rounds") for row in rows)
    iterations = tuple(_positive_int_stat(row, "iterations") for row in rows)
    sample_counts = tuple(0 if row is None else len(row.samples) for row in rows)
    samples = tuple(sample for row in rows if row is not None for sample in row.samples)
    run_samples = tuple(() if row is None else row.samples for row in rows)
    run_iqrs = tuple(_sample_iqr(values) for values in run_samples)
    run_coefficients_of_variation = tuple(_coefficient_of_variation(values) for values in run_samples)
    run_outlier_counts = tuple(_tukey_outlier_count(values) for values in run_samples)
    run_outlier_fractions = tuple(
        None if count is None or not values else count / len(values)
        for count, values in zip(run_outlier_counts, run_samples, strict=True)
    )
    observed_indices = tuple(index for index, row in enumerate(rows) if row is not None)
    issues: list[str] = []

    if len(observed_indices) < policy.minimum_runs:
        issues.append(f"only {len(observed_indices)} run(s) contain the cell; {policy.minimum_runs} required")
    missing_count = len(rows) - len(observed_indices)
    if missing_count:
        issues.append(f"cell is missing from {missing_count} provided run(s)")

    for index in observed_indices:
        run_rounds = rounds[index]
        run_iterations = iterations[index]
        run_sample_count = sample_counts[index]
        minimum_samples = policy.minimum_samples_per_run
        if metric_name == METRIC_TAIL_LATENCY:
            minimum_samples = max(minimum_samples, policy.minimum_tail_samples_per_run)
        if run_sample_count < minimum_samples:
            issues.append(f"run {index} has {run_sample_count} sample(s); " + f"{minimum_samples} required")
        if policy.require_raw_samples_for_inference and run_sample_count == 0:
            issues.append(f"run {index} does not contain raw round-duration observations")
        if policy.require_rounds and run_rounds is None:
            issues.append(f"run {index} does not report positive rounds")
        if run_rounds is not None and run_rounds < policy.minimum_rounds_per_run:
            issues.append(f"run {index} reports {run_rounds} round(s); " + f"{policy.minimum_rounds_per_run} required")
        if run_rounds is not None and run_sample_count and run_rounds != run_sample_count:
            issues.append(
                f"run {index} reports {run_rounds} round(s) but contains "
                + f"{run_sample_count} round-duration observation(s)"
            )
        if policy.require_iterations and run_iterations is None:
            issues.append(f"run {index} does not report positive iterations")
        if metric_name == METRIC_TAIL_LATENCY and policy.require_tail_iterations_one and run_iterations != 1:
            reported = "no positive iteration count" if run_iterations is None else f"{run_iterations} iterations"
            issues.append(f"run {index} reports {reported}; tail latency requires one iteration")
        run_cv = run_coefficients_of_variation[index]
        if policy.maximum_cv is not None:
            if run_cv is None:
                issues.append(f"run {index} coefficient of variation is unavailable")
            elif run_cv > policy.maximum_cv:
                issues.append(f"run {index} coefficient of variation {run_cv:.4f} exceeds {policy.maximum_cv:.4f}")
        run_outlier_fraction = run_outlier_fractions[index]
        if policy.maximum_outlier_fraction is not None:
            if run_outlier_fraction is None:
                issues.append(f"run {index} outlier fraction is unavailable")
            elif run_outlier_fraction > policy.maximum_outlier_fraction:
                issues.append(
                    f"run {index} outlier fraction {run_outlier_fraction:.4f} exceeds "
                    + f"{policy.maximum_outlier_fraction:.4f}"
                )

    iqr = _sample_iqr(samples)
    coefficient_of_variation = _coefficient_of_variation(samples)
    outlier_count = _tukey_outlier_count(samples)
    outlier_fraction = None if outlier_count is None or not samples else outlier_count / len(samples)
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
        run_iqrs=run_iqrs,
        run_coefficients_of_variation=run_coefficients_of_variation,
        run_outlier_counts=run_outlier_counts,
        run_outlier_fractions=run_outlier_fractions,
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


def _observed_improvements(
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    *,
    direction: ComparisonDirection,
    design: ComparisonDesign,
) -> tuple[float, ...]:
    """Return finite observed effects under the declared comparison design."""
    improvements: list[float] = []
    if design == "paired":
        value_pairs = zip(baseline_values, candidate_values, strict=True)
    else:
        value_pairs = (
            (baseline_value, candidate_value)
            for baseline_value in baseline_values
            for candidate_value in candidate_values
        )
    for baseline_value, candidate_value in value_pairs:
        if baseline_value == 0.0:
            continue
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
    inference: BenchmarkInference | None,
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
    if inference is not None and inference.issues:
        return "Statistical inference unavailable: " + "; ".join(inference.issues) + "."
    if (
        inference is not None
        and inference.confidence_low_percent is not None
        and inference.confidence_high_percent is not None
    ):
        return (
            "The adjusted confidence interval crosses a practical-effect boundary at "
            + f"±{threshold_percent:.2f}% "
            + f"({inference.confidence_low_percent:+.2f}% to "
            + f"{inference.confidence_high_percent:+.2f}%)."
        )
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


def _infer_repeated_effect(
    key: _CellKey,
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    *,
    direction: ComparisonDirection,
    family_size: int,
    evidence_adequate: bool,
    policy: InferencePolicy,
    design: ComparisonDesign,
    pair_strata: tuple[str, ...] | None,
) -> BenchmarkInference:
    """Return deterministic run-level uncertainty for one matrix cell."""
    adjusted_confidence_level = _adjusted_confidence_level(
        policy.confidence_level,
        family_size=family_size,
        multiplicity=policy.multiplicity,
    )
    cell_seed = _cell_random_seed(policy.random_seed, key)
    if not evidence_adequate:
        return BenchmarkInference(
            method="bca_bootstrap",
            estimand="direction-aware percentage ratio of median per-run statistics",
            design=design,
            confidence_level=policy.confidence_level,
            adjusted_confidence_level=adjusted_confidence_level,
            multiplicity=policy.multiplicity,
            family_size=family_size,
            resamples=policy.resamples,
            random_seed=cell_seed,
            estimate_percent=None,
            confidence_low_percent=None,
            confidence_high_percent=None,
            issues=("evidence policy was not satisfied",),
            pair_count=len(baseline_values) if design == "paired" else None,
            strata_count=_paired_strata_count(pair_strata) if design == "paired" else None,
        )

    if design == "paired":
        interval = bootstrap_paired_median_ratio_interval(
            baseline_values,
            candidate_values,
            lower_is_better=direction == "lower_is_better",
            confidence_level=adjusted_confidence_level,
            resamples=policy.resamples,
            random_seed=cell_seed,
            strata=pair_strata,
        )
    else:
        interval = bootstrap_median_ratio_interval(
            baseline_values,
            candidate_values,
            lower_is_better=direction == "lower_is_better",
            confidence_level=adjusted_confidence_level,
            resamples=policy.resamples,
            random_seed=cell_seed,
        )
    warnings = list(interval.warnings)
    if policy.multiplicity == "none":
        warnings.append(
            "Multiplicity correction is disabled; this interval is exploratory and does not control "
            + "matrix-wide error."
        )
    expected_tail_resamples = policy.resamples * (1.0 - adjusted_confidence_level) / 2.0
    if expected_tail_resamples < 10.0:
        warnings.append(
            "The adjusted interval has fewer than 10 expected bootstrap estimates in each tail; "
            + "increase inference resamples for better tail resolution."
        )
    return BenchmarkInference(
        method=cast(IntervalMethod, interval.method),
        estimand="direction-aware percentage ratio of median per-run statistics",
        design=design,
        confidence_level=policy.confidence_level,
        adjusted_confidence_level=adjusted_confidence_level,
        multiplicity=policy.multiplicity,
        family_size=family_size,
        resamples=policy.resamples,
        random_seed=cell_seed,
        estimate_percent=interval.estimate,
        confidence_low_percent=interval.low,
        confidence_high_percent=interval.high,
        warnings=tuple(warnings),
        issues=interval.issues,
        pair_count=len(baseline_values) if design == "paired" else None,
        strata_count=_paired_strata_count(pair_strata) if design == "paired" else None,
    )


def _adjusted_confidence_level(
    confidence_level: float,
    *,
    family_size: int,
    multiplicity: MultiplicityCorrection,
) -> float:
    """Return the simultaneous per-cell confidence level."""
    if multiplicity == "none":
        return confidence_level
    family_alpha = 1.0 - confidence_level
    return 1.0 - family_alpha / family_size


def _cell_random_seed(random_seed: int, key: _CellKey) -> int:
    """Derive a stable cell-specific bootstrap seed."""
    payload = "\0".join((str(random_seed), *key)).encode()
    return int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)


def _classify_inference(
    inference: BenchmarkInference,
    *,
    threshold_percent: float,
) -> RegressionClassification:
    """Classify an effect interval against practical-equivalence bounds."""
    low = inference.confidence_low_percent
    high = inference.confidence_high_percent
    if not inference.adequate or low is None or high is None:
        return "inconclusive"
    if high < -threshold_percent:
        return "regressed"
    if low > threshold_percent:
        return "improved"
    if low >= -threshold_percent and high <= threshold_percent:
        return "unchanged"
    return "inconclusive"


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


def _validate_pair_strata(
    strata: Sequence[str] | None,
    *,
    pair_count: int,
    design: ComparisonDesign,
) -> tuple[str, ...] | None:
    """Validate optional fixed-design labels for paired resampling."""
    if strata is None:
        return None
    if design != "paired":
        raise ValueError("Pair strata require an explicitly paired comparison design.")
    resolved = tuple(strata)
    if len(resolved) != pair_count:
        raise ValueError("pair_strata must contain one label for every complete pair.")
    if any(not isinstance(label, str) or not label for label in resolved):
        raise ValueError("pair_strata labels must be non-empty strings.")
    return resolved


def _paired_strata_count(strata: tuple[str, ...] | None) -> int:
    """Return the number of fixed resampling strata represented by pairs."""
    return 1 if strata is None else len(set(strata))


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
