"""Run-level statistical inference for benchmark comparisons."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

_NORMAL = statistics.NormalDist()
_MINIMUM_GROUP_SIZE = 2
_MINIMUM_STABLE_PILOT_SIZE = 5
_MAXIMUM_PLANNED_PAIRS = 2_147_483_647

MultiplicityCorrection = Literal["bonferroni", "none"]


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    """One deterministic bootstrap effect estimate and confidence interval."""

    estimate: float | None
    low: float | None
    high: float | None
    method: str
    warnings: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    @property
    def adequate(self) -> bool:
        """Return whether the interval was calculated successfully."""
        return not self.issues and self.estimate is not None and self.low is not None and self.high is not None


@dataclass(frozen=True, slots=True)
class PrecisionPlan:
    """Fixed-design pair-count plan derived from pilot paired log ratios.

    The planning estimand is the mean signed paired log ratio, a variance-based
    proxy rather than the ratio-of-marginal-medians estimand used by formal BCa
    inference. This is a precision calculation, not power analysis. Its
    pair-count result assumes that pilot variability is representative and that
    a fresh confirmatory collection uses the complete planned pair count fixed
    before examining its results. ``additional_pairs`` is only the arithmetic
    difference from the pilot size; it does not endorse reusing pilot outcomes.
    """

    method: Literal["paired_log_ratio_t"]
    pilot_pairs: int
    target_half_width_percent: float
    confidence_level: float
    adjusted_confidence_level: float
    multiplicity: MultiplicityCorrection
    family_size: int
    pilot_log_ratio_standard_deviation: float | None
    critical_value: float | None
    required_pairs: int | None
    additional_pairs: int | None
    assumptions: tuple[str, ...]
    minimum_pairs: int = _MINIMUM_GROUP_SIZE
    pair_count_multiple: int = 1
    unconstrained_required_pairs: int | None = None
    strata_count: int = 1
    warnings: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and normalize a precision plan."""
        if self.method != "paired_log_ratio_t":
            raise ValueError(f"Unsupported precision-planning method: {self.method!r}.")
        if isinstance(self.pilot_pairs, bool) or not isinstance(self.pilot_pairs, int) or self.pilot_pairs < 0:
            raise ValueError("PrecisionPlan.pilot_pairs must be a non-negative integer.")
        if not math.isfinite(self.target_half_width_percent) or self.target_half_width_percent <= 0.0:
            raise ValueError("PrecisionPlan.target_half_width_percent must be finite and positive.")
        for field_name, value in (
            ("confidence_level", self.confidence_level),
            ("adjusted_confidence_level", self.adjusted_confidence_level),
        ):
            if not math.isfinite(value) or not 0.0 < value < 1.0:
                raise ValueError(f"PrecisionPlan.{field_name} must be finite and between zero and one.")
        if self.adjusted_confidence_level < self.confidence_level:
            raise ValueError("Adjusted confidence level must not be lower than the nominal confidence level.")
        if self.multiplicity not in {"bonferroni", "none"}:
            raise ValueError(f"Unsupported multiplicity correction: {self.multiplicity!r}.")
        if isinstance(self.family_size, bool) or not isinstance(self.family_size, int) or self.family_size <= 0:
            raise ValueError("PrecisionPlan.family_size must be a positive integer.")
        if (
            isinstance(self.minimum_pairs, bool)
            or not isinstance(self.minimum_pairs, int)
            or self.minimum_pairs < _MINIMUM_GROUP_SIZE
        ):
            raise ValueError(f"PrecisionPlan.minimum_pairs must be at least {_MINIMUM_GROUP_SIZE}.")
        if (
            isinstance(self.pair_count_multiple, bool)
            or not isinstance(self.pair_count_multiple, int)
            or self.pair_count_multiple <= 0
        ):
            raise ValueError("PrecisionPlan.pair_count_multiple must be a positive integer.")
        if isinstance(self.strata_count, bool) or not isinstance(self.strata_count, int) or self.strata_count < 0:
            raise ValueError("PrecisionPlan.strata_count must be a non-negative integer.")
        if self.multiplicity == "none" and self.adjusted_confidence_level != self.confidence_level:
            raise ValueError("Unadjusted precision plans must use the nominal confidence level.")
        if self.pilot_log_ratio_standard_deviation is not None and (
            not math.isfinite(self.pilot_log_ratio_standard_deviation) or self.pilot_log_ratio_standard_deviation < 0.0
        ):
            raise ValueError("PrecisionPlan pilot variability must be finite and non-negative or None.")
        if self.critical_value is not None and (not math.isfinite(self.critical_value) or self.critical_value <= 0.0):
            raise ValueError("PrecisionPlan.critical_value must be finite and positive or None.")
        unconstrained_required_pairs = self.unconstrained_required_pairs
        if self.required_pairs is not None and unconstrained_required_pairs is None:
            # Preserve compatibility for callers that constructed the original
            # value object directly. Planner-created values always persist the
            # independently calculated unconstrained count.
            unconstrained_required_pairs = self.required_pairs
            object.__setattr__(self, "unconstrained_required_pairs", unconstrained_required_pairs)
        result_fields = (
            self.critical_value,
            unconstrained_required_pairs,
            self.required_pairs,
            self.additional_pairs,
        )
        if any(value is not None for value in result_fields) and not all(value is not None for value in result_fields):
            raise ValueError("PrecisionPlan critical value and pair-count results must be present together.")
        if self.required_pairs is not None:
            if self.strata_count <= 0:
                raise ValueError("Complete PrecisionPlan results require at least one fitted stratum.")
            if self.pilot_log_ratio_standard_deviation is None or self.pilot_log_ratio_standard_deviation == 0.0:
                raise ValueError("Complete PrecisionPlan results require positive pilot residual variability.")
            minimum_estimable_pairs = self.strata_count + 1
            if (
                isinstance(unconstrained_required_pairs, bool)
                or not isinstance(unconstrained_required_pairs, int)
                or unconstrained_required_pairs < max(_MINIMUM_GROUP_SIZE, minimum_estimable_pairs)
            ):
                raise ValueError(
                    "PrecisionPlan.unconstrained_required_pairs must leave positive residual degrees of freedom."
                )
            if (
                isinstance(self.required_pairs, bool)
                or not isinstance(self.required_pairs, int)
                or self.required_pairs < max(_MINIMUM_GROUP_SIZE, minimum_estimable_pairs)
            ):
                raise ValueError("PrecisionPlan.required_pairs must leave positive residual degrees of freedom.")
            expected_required = _round_up_to_multiple(
                max(unconstrained_required_pairs, self.minimum_pairs),
                self.pair_count_multiple,
            )
            if self.required_pairs != expected_required:
                raise ValueError(
                    "PrecisionPlan.required_pairs is inconsistent with the unconstrained count and design constraints."
                )
            expected_unconstrained = _required_pairs_for_precision(
                self.pilot_log_ratio_standard_deviation,
                target_log_half_width=math.log1p(self.target_half_width_percent / 100.0),
                confidence_level=self.adjusted_confidence_level,
                strata_count=self.strata_count,
            )
            if unconstrained_required_pairs != expected_unconstrained:
                raise ValueError(
                    "PrecisionPlan.unconstrained_required_pairs is inconsistent with its variability and target."
                )
            expected_critical = _student_t_critical(
                self.adjusted_confidence_level,
                degrees_of_freedom=self.required_pairs - self.strata_count,
            )
            critical_value = self.critical_value
            if critical_value is None or not math.isclose(
                critical_value,
                expected_critical,
                rel_tol=1e-12,
                abs_tol=0.0,
            ):
                raise ValueError(
                    "PrecisionPlan.critical_value is inconsistent with confidence and residual degrees of freedom."
                )
            expected_additional = max(0, self.required_pairs - self.pilot_pairs)
            if self.additional_pairs != expected_additional:
                raise ValueError("PrecisionPlan.additional_pairs is inconsistent with the pilot and required counts.")
        assumptions = tuple(self.assumptions)
        warnings = tuple(self.warnings)
        issues = tuple(self.issues)
        if not assumptions or any(not isinstance(item, str) or not item for item in assumptions):
            raise ValueError("PrecisionPlan.assumptions must contain non-empty strings.")
        if any(not isinstance(item, str) or not item for item in (*warnings, *issues)):
            raise ValueError("PrecisionPlan warnings and issues must contain non-empty strings.")
        object.__setattr__(self, "assumptions", assumptions)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "issues", issues)

    @property
    def adequate(self) -> bool:
        """Return whether a complete fixed-design pair-count estimate exists."""
        return not self.issues and self.required_pairs is not None and self.additional_pairs is not None


def bootstrap_median_ratio_interval(
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    *,
    lower_is_better: bool,
    confidence_level: float,
    resamples: int,
    random_seed: int,
) -> BootstrapInterval:
    """Estimate a direction-aware median ratio with a run-level BCa interval.

    Each value is the statistic from one independently launched benchmark
    process. The two groups are resampled independently, so raw benchmark
    rounds within a process are never treated as independent observations.
    Input values are sorted before resampling to make seeded results invariant
    to the order in which run files were supplied.
    """
    try:
        baseline = tuple(sorted(float(value) for value in baseline_values))
        candidate = tuple(sorted(float(value) for value in candidate_values))
    except (OverflowError, TypeError, ValueError):
        return BootstrapInterval(
            estimate=None,
            low=None,
            high=None,
            method="bca_bootstrap",
            issues=("run statistics must be finite numeric values",),
        )
    issues = _validate_inputs(
        baseline,
        candidate,
        confidence_level=confidence_level,
        resamples=resamples,
    )
    if issues:
        return BootstrapInterval(
            estimate=None,
            low=None,
            high=None,
            method="bca_bootstrap",
            issues=issues,
        )

    try:
        estimate = _median_ratio_effect(
            baseline,
            candidate,
            lower_is_better=lower_is_better,
        )
    except OverflowError:
        estimate = math.inf
    if not math.isfinite(estimate):
        return BootstrapInterval(
            estimate=None,
            low=None,
            high=None,
            method="bca_bootstrap",
            issues=("observed median-ratio effect is not finite",),
        )
    # A deterministic pseudorandom stream is required for reproducible statistics; this is not cryptography.
    generator = random.Random(random_seed)  # nosec B311
    bootstrap_estimates_list: list[float] = []
    for _ in range(resamples):
        try:
            bootstrap_estimate = _median_ratio_effect(
                _resample(baseline, generator),
                _resample(candidate, generator),
                lower_is_better=lower_is_better,
            )
        except OverflowError:
            bootstrap_estimate = math.inf
        if not math.isfinite(bootstrap_estimate):
            return BootstrapInterval(
                estimate=None,
                low=None,
                high=None,
                method="bca_bootstrap",
                issues=("bootstrap median-ratio effect is not finite",),
            )
        bootstrap_estimates_list.append(bootstrap_estimate)
    bootstrap_estimates = tuple(bootstrap_estimates_list)
    lower_probability = (1.0 - confidence_level) / 2.0
    upper_probability = 1.0 - lower_probability
    try:
        jackknife = _jackknife_estimates(
            baseline,
            candidate,
            lower_is_better=lower_is_better,
        )
    except OverflowError:
        jackknife = ((), ())
    if not all(math.isfinite(value) for group in jackknife for value in group):
        jackknife = ((), ())
    adjusted = (
        None
        if not all(jackknife)
        else _bca_probabilities(
            bootstrap_estimates,
            estimate=estimate,
            jackknife_estimates=jackknife,
            lower_probability=lower_probability,
            upper_probability=upper_probability,
        )
    )
    warnings: tuple[str, ...] = ()
    method = "bca_bootstrap"
    if adjusted is None:
        adjusted = (lower_probability, upper_probability)
        method = "percentile_bootstrap"
        warnings = ("BCa adjustment was degenerate; used a percentile bootstrap interval.",)

    low = _quantile(bootstrap_estimates, adjusted[0])
    high = _quantile(bootstrap_estimates, adjusted[1])
    if low > high:
        low, high = high, low
    return BootstrapInterval(
        estimate=estimate,
        low=low,
        high=high,
        method=method,
        warnings=warnings,
    )


def bootstrap_paired_median_ratio_interval(
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    *,
    lower_is_better: bool,
    confidence_level: float,
    resamples: int,
    random_seed: int,
    strata: Sequence[str] | None = None,
) -> BootstrapInterval:
    """Estimate a median ratio with a paired run-level BCa interval.

    Values at the same position form one matched process-run pair. Complete
    pairs, rather than individual observations, are resampled with replacement.
    The point estimand remains the direction-aware ratio of the baseline and
    candidate marginal medians, matching independent-design inference. Pair
    tuples are sorted before seeded resampling, making results invariant to the
    order in which complete pairs were supplied without destroying pairing.

    When ``strata`` contains fixed collection-design labels such as ``"AB"``
    and ``"BA"``, resampling preserves the observed count in every stratum.
    The BCa acceleration then uses delete-one estimates grouped by stratum.
    Without labels, all complete pairs are treated as exchangeable and the
    returned interval carries an explicit warning about that assumption.
    """
    try:
        baseline = tuple(float(value) for value in baseline_values)
        candidate = tuple(float(value) for value in candidate_values)
    except (OverflowError, TypeError, ValueError):
        return BootstrapInterval(
            estimate=None,
            low=None,
            high=None,
            method="bca_bootstrap",
            issues=("paired run statistics must be finite numeric values",),
        )
    normalized_strata, strata_issues = _normalize_strata(
        strata,
        expected_length=len(baseline),
    )
    issues = (
        *_validate_paired_inputs(
            baseline,
            candidate,
            confidence_level=confidence_level,
            resamples=resamples,
            random_seed=random_seed,
        ),
        *strata_issues,
    )
    if issues:
        return BootstrapInterval(
            estimate=None,
            low=None,
            high=None,
            method="bca_bootstrap",
            issues=issues,
        )

    pairs = tuple(sorted(zip(baseline, candidate, strict=True)))
    pair_strata = (
        None
        if normalized_strata is None
        else _stratify_pairs(
            baseline,
            candidate,
            normalized_strata,
        )
    )
    try:
        estimate = _paired_median_ratio_effect(
            pairs,
            lower_is_better=lower_is_better,
        )
    except OverflowError:
        estimate = math.inf
    if not math.isfinite(estimate):
        return BootstrapInterval(
            estimate=None,
            low=None,
            high=None,
            method="bca_bootstrap",
            issues=("observed paired median-ratio effect is not finite",),
        )

    # A deterministic pseudorandom stream is required for reproducible statistics; this is not cryptography.
    generator = random.Random(random_seed)  # nosec B311
    bootstrap_estimates_list: list[float] = []
    for _ in range(resamples):
        try:
            bootstrap_pairs = (
                _resample_pairs(pairs, generator)
                if pair_strata is None
                else _resample_stratified_pairs(pair_strata, generator)
            )
            bootstrap_estimate = _paired_median_ratio_effect(
                bootstrap_pairs,
                lower_is_better=lower_is_better,
            )
        except OverflowError:
            bootstrap_estimate = math.inf
        if not math.isfinite(bootstrap_estimate):
            return BootstrapInterval(
                estimate=None,
                low=None,
                high=None,
                method="bca_bootstrap",
                issues=("bootstrap paired median-ratio effect is not finite",),
            )
        bootstrap_estimates_list.append(bootstrap_estimate)
    bootstrap_estimates = tuple(bootstrap_estimates_list)

    lower_probability = (1.0 - confidence_level) / 2.0
    upper_probability = 1.0 - lower_probability
    try:
        jackknife = (
            (
                _paired_jackknife_estimates(
                    pairs,
                    lower_is_better=lower_is_better,
                ),
            )
            if pair_strata is None
            else _stratified_paired_jackknife_estimates(
                pair_strata,
                lower_is_better=lower_is_better,
            )
        )
    except OverflowError:
        jackknife = ((),)
    if not all(math.isfinite(value) for group in jackknife for value in group):
        jackknife = ((),)
    adjusted = (
        None
        if not all(jackknife)
        else _bca_probabilities(
            bootstrap_estimates,
            estimate=estimate,
            jackknife_estimates=jackknife,
            lower_probability=lower_probability,
            upper_probability=upper_probability,
        )
    )
    warnings = (
        (
            "No orientation strata were supplied; paired bootstrap inference assumes all complete pairs are "
            "exchangeable and may treat fixed AB/BA order effects as random variation.",
        )
        if pair_strata is None
        else ()
    )
    method = "bca_bootstrap"
    if adjusted is None:
        adjusted = (lower_probability, upper_probability)
        method = "percentile_bootstrap"
        warnings = (
            *warnings,
            "Paired BCa adjustment was degenerate; used a percentile bootstrap interval.",
        )

    low = _quantile(bootstrap_estimates, adjusted[0])
    high = _quantile(bootstrap_estimates, adjusted[1])
    if low > high:
        low, high = high, low
    return BootstrapInterval(
        estimate=estimate,
        low=low,
        high=high,
        method=method,
        warnings=warnings,
    )


def plan_paired_precision(
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    *,
    lower_is_better: bool,
    target_half_width_percent: float,
    confidence_level: float = 0.95,
    family_size: int = 1,
    multiplicity: MultiplicityCorrection = "bonferroni",
    strata: Sequence[str] | None = None,
    minimum_pairs: int = _MINIMUM_GROUP_SIZE,
    pair_count_multiple: int = 2,
) -> PrecisionPlan:
    """Estimate a fixed confirmatory pair count from paired pilot runs.

    The planning approximation uses the residual standard deviation of signed
    paired log ratios. Positive signed log ratios mean improvement, regardless
    of metric direction. When fixed collection-design ``strata`` such as AB and
    BA are supplied, a separate mean is fitted for each stratum so a fixed
    orientation effect is not counted as future random variation. Student-t
    degrees of freedom account for those fitted means.

    The requested percentage half-width is converted to
    ``log1p(target / 100)``. This is a multiplicative mean-log-ratio proxy for
    the formal ratio-of-marginal-medians BCa estimand; the two targets are not
    identical. ``minimum_pairs`` and ``pair_count_multiple`` are then applied
    to the smallest unconstrained count. The default multiple of two keeps a
    direct AB/BA plan even. With ``bonferroni``, confidence is adjusted across
    ``family_size`` cells before calculating the count.

    ``required_pairs`` is the size of a fresh future confirmatory collection.
    ``additional_pairs`` is only its arithmetic difference from the pilot
    count, not a recommendation to append runs to the analyzed pilot. This
    calculation describes precision only: it does not estimate power, justify
    optional stopping, or update a confirmatory run count after results have
    been examined.
    """
    target = _validate_positive_number(
        target_half_width_percent,
        field_name="target_half_width_percent",
    )
    confidence = _validate_open_probability(
        confidence_level,
        field_name="confidence_level",
    )
    if isinstance(family_size, bool) or not isinstance(family_size, int):
        raise TypeError("family_size must be an integer.")
    if family_size <= 0:
        raise ValueError("family_size must be a positive integer.")
    if multiplicity not in {"bonferroni", "none"}:
        raise ValueError(f"Unsupported multiplicity correction: {multiplicity!r}.")
    if isinstance(minimum_pairs, bool) or not isinstance(minimum_pairs, int):
        raise TypeError("minimum_pairs must be an integer.")
    if minimum_pairs < _MINIMUM_GROUP_SIZE:
        raise ValueError(f"minimum_pairs must be at least {_MINIMUM_GROUP_SIZE}.")
    if isinstance(pair_count_multiple, bool) or not isinstance(pair_count_multiple, int):
        raise TypeError("pair_count_multiple must be an integer.")
    if pair_count_multiple <= 0:
        raise ValueError("pair_count_multiple must be a positive integer.")
    adjusted_confidence = 1.0 - (1.0 - confidence) / family_size if multiplicity == "bonferroni" else confidence
    if adjusted_confidence >= 1.0:
        raise ValueError("family_size is too large to represent the Bonferroni-adjusted confidence level.")

    assumptions = (
        "Pilot pairs are representative of the future fixed-design paired collection.",
        "Pairs are independent, while baseline and candidate observations remain dependent within each pair.",
        "The target is a multiplicative half-width for the mean signed paired log ratio; this is a variance-based "
        "proxy and is not the formal ratio-of-marginal-medians BCa estimand.",
        "Pilot residual log-ratio variability is representative of future residual variability; the Student-t "
        "proxy does not guarantee a BCa interval width.",
        *(
            (
                "Future collection uses a prespecified fixed stratum allocation compatible with the pair-count "
                "multiple; fitted stratum effects are not treated as random variation.",
            )
            if strata is not None
            else ("No fixed orientation strata are modeled, so all paired log ratios are treated as exchangeable.",)
        ),
        "Required pairs describe a fresh confirmatory collection; the additional-pairs field is descriptive "
        "arithmetic and does not justify reusing the pilot.",
        "The confirmatory pair count is fixed before collection; this is not power analysis or a sequential "
        "stopping rule.",
    )
    try:
        baseline = tuple(float(value) for value in baseline_values)
        candidate = tuple(float(value) for value in candidate_values)
    except (OverflowError, TypeError, ValueError):
        return _failed_precision_plan(
            pilot_pairs=0,
            target_half_width_percent=target,
            confidence_level=confidence,
            adjusted_confidence_level=adjusted_confidence,
            multiplicity=multiplicity,
            family_size=family_size,
            minimum_pairs=minimum_pairs,
            pair_count_multiple=pair_count_multiple,
            strata_count=0 if strata is not None else 1,
            assumptions=assumptions,
            issues=("paired pilot statistics must be finite numeric values",),
        )

    pilot_pairs = min(len(baseline), len(candidate))
    normalized_strata, strata_issues = _normalize_strata(
        strata,
        expected_length=len(baseline),
    )
    strata_count = 1 if normalized_strata is None and not strata_issues else 0
    if normalized_strata is not None:
        strata_count = len(set(normalized_strata))
    issues = (*_paired_measurement_issues(baseline, candidate), *strata_issues)
    if issues:
        return _failed_precision_plan(
            pilot_pairs=pilot_pairs,
            target_half_width_percent=target,
            confidence_level=confidence,
            adjusted_confidence_level=adjusted_confidence,
            multiplicity=multiplicity,
            family_size=family_size,
            minimum_pairs=minimum_pairs,
            pair_count_multiple=pair_count_multiple,
            strata_count=strata_count,
            assumptions=assumptions,
            issues=issues,
        )

    direction = -1.0 if lower_is_better else 1.0
    log_ratios = tuple(
        direction * (math.log(candidate_value) - math.log(baseline_value))
        for baseline_value, candidate_value in zip(baseline, candidate, strict=True)
    )
    try:
        variability = _residual_log_ratio_standard_deviation(
            log_ratios,
            strata=normalized_strata,
        )
    except (OverflowError, statistics.StatisticsError):
        variability = math.inf
    residual_degrees_of_freedom = pilot_pairs - strata_count
    warnings = (
        "Precision planning targets a multiplicative mean-log-ratio proxy; formal inference targets a ratio of "
        "marginal medians.",
        "The pair-count estimate treats pilot residual variability as representative and does not account for "
        "uncertainty in that estimated variability.",
        *(
            (
                "No orientation strata were supplied; planning treats fixed AB/BA order effects as random "
                "paired variation.",
            )
            if normalized_strata is None
            else ()
        ),
        *(
            (
                f"The pilot contains fewer than {_MINIMUM_STABLE_PILOT_SIZE} pairs; "
                + "its variability estimate is unstable.",
            )
            if pilot_pairs < _MINIMUM_STABLE_PILOT_SIZE
            else ()
        ),
        *(
            (
                f"The pilot has only {residual_degrees_of_freedom} residual degree(s) of freedom after fitting "
                f"{strata_count} stratum mean(s); its variability estimate is unstable.",
            )
            if normalized_strata is not None and residual_degrees_of_freedom < _MINIMUM_STABLE_PILOT_SIZE
            else ()
        ),
    )
    if not math.isfinite(variability):
        return _failed_precision_plan(
            pilot_pairs=pilot_pairs,
            target_half_width_percent=target,
            confidence_level=confidence,
            adjusted_confidence_level=adjusted_confidence,
            multiplicity=multiplicity,
            family_size=family_size,
            minimum_pairs=minimum_pairs,
            pair_count_multiple=pair_count_multiple,
            strata_count=strata_count,
            assumptions=assumptions,
            warnings=warnings,
            issues=("paired pilot log-ratio variability is not finite",),
        )
    if variability == 0.0:
        return _failed_precision_plan(
            pilot_pairs=pilot_pairs,
            target_half_width_percent=target,
            confidence_level=confidence,
            adjusted_confidence_level=adjusted_confidence,
            multiplicity=multiplicity,
            family_size=family_size,
            minimum_pairs=minimum_pairs,
            pair_count_multiple=pair_count_multiple,
            strata_count=strata_count,
            assumptions=assumptions,
            variability=variability,
            warnings=warnings,
            issues=("paired pilot residual log ratios have zero variability; required precision cannot be estimated",),
        )

    target_log_half_width = math.log1p(target / 100.0)
    unconstrained_required = _required_pairs_for_precision(
        variability,
        target_log_half_width=target_log_half_width,
        confidence_level=adjusted_confidence,
        strata_count=strata_count,
    )
    if unconstrained_required is None:
        return _failed_precision_plan(
            pilot_pairs=pilot_pairs,
            target_half_width_percent=target,
            confidence_level=confidence,
            adjusted_confidence_level=adjusted_confidence,
            multiplicity=multiplicity,
            family_size=family_size,
            minimum_pairs=minimum_pairs,
            pair_count_multiple=pair_count_multiple,
            strata_count=strata_count,
            assumptions=assumptions,
            variability=variability,
            warnings=warnings,
            issues=(f"estimated required pair count exceeds {_MAXIMUM_PLANNED_PAIRS:,}",),
        )
    required = _round_up_to_multiple(
        max(unconstrained_required, minimum_pairs),
        pair_count_multiple,
    )
    if required > _MAXIMUM_PLANNED_PAIRS:
        return _failed_precision_plan(
            pilot_pairs=pilot_pairs,
            target_half_width_percent=target,
            confidence_level=confidence,
            adjusted_confidence_level=adjusted_confidence,
            multiplicity=multiplicity,
            family_size=family_size,
            minimum_pairs=minimum_pairs,
            pair_count_multiple=pair_count_multiple,
            strata_count=strata_count,
            assumptions=assumptions,
            variability=variability,
            warnings=warnings,
            issues=(f"design-constrained required pair count exceeds {_MAXIMUM_PLANNED_PAIRS:,}",),
        )
    critical_value = _student_t_critical(
        adjusted_confidence,
        degrees_of_freedom=required - strata_count,
    )
    return PrecisionPlan(
        method="paired_log_ratio_t",
        pilot_pairs=pilot_pairs,
        target_half_width_percent=target,
        confidence_level=confidence,
        adjusted_confidence_level=adjusted_confidence,
        multiplicity=multiplicity,
        family_size=family_size,
        pilot_log_ratio_standard_deviation=variability,
        critical_value=critical_value,
        required_pairs=required,
        additional_pairs=max(0, required - pilot_pairs),
        assumptions=assumptions,
        minimum_pairs=minimum_pairs,
        pair_count_multiple=pair_count_multiple,
        unconstrained_required_pairs=unconstrained_required,
        strata_count=strata_count,
        warnings=warnings,
    )


def _validate_inputs(
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
    *,
    confidence_level: float,
    resamples: int,
) -> tuple[str, ...]:
    """Return fatal bootstrap-input validation issues."""
    issues: list[str] = []
    if len(baseline) < _MINIMUM_GROUP_SIZE:
        issues.append(f"baseline has {len(baseline)} run(s); at least {_MINIMUM_GROUP_SIZE} required for inference")
    if len(candidate) < _MINIMUM_GROUP_SIZE:
        issues.append(f"candidate has {len(candidate)} run(s); at least {_MINIMUM_GROUP_SIZE} required for inference")
    if any(not math.isfinite(value) or value <= 0.0 for value in baseline):
        issues.append("baseline run statistics must be finite and positive for ratio inference")
    if any(not math.isfinite(value) or value <= 0.0 for value in candidate):
        issues.append("candidate run statistics must be finite and positive for ratio inference")
    if not math.isfinite(confidence_level) or not 0.0 < confidence_level < 1.0:
        issues.append("confidence level must be finite and between zero and one")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples <= 0:
        issues.append("bootstrap resamples must be a positive integer")
    return tuple(issues)


def _validate_paired_inputs(
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
    *,
    confidence_level: float,
    resamples: int,
    random_seed: int,
) -> tuple[str, ...]:
    """Return fatal paired-bootstrap input validation issues."""
    issues = list(_paired_measurement_issues(baseline, candidate))
    if not math.isfinite(confidence_level) or not 0.0 < confidence_level < 1.0:
        issues.append("confidence level must be finite and between zero and one")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples <= 0:
        issues.append("bootstrap resamples must be a positive integer")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed < 0:
        issues.append("random seed must be a non-negative integer")
    return tuple(issues)


def _paired_measurement_issues(
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
) -> tuple[str, ...]:
    """Return validation issues shared by paired inference and planning."""
    issues: list[str] = []
    if len(baseline) != len(candidate):
        issues.append(
            "paired baseline and candidate statistics must have equal lengths; "
            f"got {len(baseline)} and {len(candidate)}"
        )
    if min(len(baseline), len(candidate)) < _MINIMUM_GROUP_SIZE:
        issues.append(
            f"paired inference has {min(len(baseline), len(candidate))} complete pair(s); "
            f"at least {_MINIMUM_GROUP_SIZE} required"
        )
    if any(not math.isfinite(value) or value <= 0.0 for value in baseline):
        issues.append("paired baseline run statistics must be finite and positive for ratio inference")
    if any(not math.isfinite(value) or value <= 0.0 for value in candidate):
        issues.append("paired candidate run statistics must be finite and positive for ratio inference")
    return tuple(issues)


def _normalize_strata(
    strata: Sequence[str] | None,
    *,
    expected_length: int,
) -> tuple[tuple[str, ...] | None, tuple[str, ...]]:
    """Return validated fixed-design stratum labels and any issues."""
    if strata is None:
        return (None, ())
    if isinstance(strata, (str, bytes)):
        return (None, ("strata must be a sequence of labels, not one string",))
    try:
        labels = tuple(strata)
    except TypeError:
        return (None, ("strata must be a sequence of non-empty string labels",))
    issues: list[str] = []
    if len(labels) != expected_length:
        issues.append(
            f"strata must contain one label per complete pair; got {len(labels)} labels for {expected_length} pairs"
        )
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        issues.append("strata labels must be non-empty strings")
    if issues:
        return (None, tuple(issues))
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    undersized = tuple(sorted(label for label, count in counts.items() if count < _MINIMUM_GROUP_SIZE))
    if undersized:
        joined = ", ".join(repr(label) for label in undersized)
        return (
            labels,
            (f"each stratum requires at least {_MINIMUM_GROUP_SIZE} complete pairs; undersized: {joined}",),
        )
    return (labels, ())


def _validate_positive_number(value: float, *, field_name: str) -> float:
    """Return one finite positive planning control."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric.")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{field_name} must be finite and positive.")
    return result


def _validate_open_probability(value: float, *, field_name: str) -> float:
    """Return one finite probability strictly between zero and one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric.")
    result = float(value)
    if not math.isfinite(result) or not 0.0 < result < 1.0:
        raise ValueError(f"{field_name} must be finite and between zero and one.")
    return result


def _failed_precision_plan(
    *,
    pilot_pairs: int,
    target_half_width_percent: float,
    confidence_level: float,
    adjusted_confidence_level: float,
    multiplicity: MultiplicityCorrection,
    family_size: int,
    minimum_pairs: int,
    pair_count_multiple: int,
    strata_count: int,
    assumptions: tuple[str, ...],
    issues: tuple[str, ...],
    variability: float | None = None,
    warnings: tuple[str, ...] = (),
) -> PrecisionPlan:
    """Build an incomplete precision plan with explicit issues."""
    return PrecisionPlan(
        method="paired_log_ratio_t",
        pilot_pairs=pilot_pairs,
        target_half_width_percent=target_half_width_percent,
        confidence_level=confidence_level,
        adjusted_confidence_level=adjusted_confidence_level,
        multiplicity=multiplicity,
        family_size=family_size,
        pilot_log_ratio_standard_deviation=variability,
        critical_value=None,
        required_pairs=None,
        additional_pairs=None,
        assumptions=assumptions,
        minimum_pairs=minimum_pairs,
        pair_count_multiple=pair_count_multiple,
        unconstrained_required_pairs=None,
        strata_count=strata_count,
        warnings=warnings,
        issues=issues,
    )


def _median_ratio_effect(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    lower_is_better: bool,
) -> float:
    """Return direction-aware percentage change between two medians."""
    baseline_median = float(statistics.median(baseline))
    candidate_median = float(statistics.median(candidate))
    percent_change = (candidate_median / baseline_median - 1.0) * 100.0
    return -percent_change if lower_is_better else percent_change


def _paired_median_ratio_effect(
    pairs: Sequence[tuple[float, float]],
    *,
    lower_is_better: bool,
) -> float:
    """Return the median-ratio effect while retaining matched pairs."""
    return _median_ratio_effect(
        tuple(pair[0] for pair in pairs),
        tuple(pair[1] for pair in pairs),
        lower_is_better=lower_is_better,
    )


def _resample(values: tuple[float, ...], generator: random.Random) -> tuple[float, ...]:
    """Resample one complete group of process-run statistics."""
    return tuple(values[generator.randrange(len(values))] for _ in values)


def _resample_pairs(
    pairs: tuple[tuple[float, float], ...],
    generator: random.Random,
) -> tuple[tuple[float, float], ...]:
    """Resample complete matched process-run pairs."""
    return tuple(pairs[generator.randrange(len(pairs))] for _ in pairs)


def _stratify_pairs(
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
    strata: tuple[str, ...],
) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Group sorted matched pairs by a fixed-design stratum."""
    grouped: dict[str, list[tuple[float, float]]] = {}
    for baseline_value, candidate_value, stratum in zip(
        baseline,
        candidate,
        strata,
        strict=True,
    ):
        grouped.setdefault(stratum, []).append((baseline_value, candidate_value))
    return tuple(tuple(sorted(grouped[label])) for label in sorted(grouped))


def _resample_stratified_pairs(
    pair_strata: tuple[tuple[tuple[float, float], ...], ...],
    generator: random.Random,
) -> tuple[tuple[float, float], ...]:
    """Resample complete pairs within strata while preserving stratum counts."""
    return tuple(pair for stratum in pair_strata for pair in _resample_pairs(stratum, generator))


def _jackknife_estimates(
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
    *,
    lower_is_better: bool,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return leave-one-run-out estimates separately for both groups."""
    baseline_estimates = tuple(
        _median_ratio_effect(
            (*baseline[:index], *baseline[index + 1 :]),
            candidate,
            lower_is_better=lower_is_better,
        )
        for index in range(len(baseline))
    )
    candidate_estimates = tuple(
        _median_ratio_effect(
            baseline,
            (*candidate[:index], *candidate[index + 1 :]),
            lower_is_better=lower_is_better,
        )
        for index in range(len(candidate))
    )
    return (baseline_estimates, candidate_estimates)


def _paired_jackknife_estimates(
    pairs: tuple[tuple[float, float], ...],
    *,
    lower_is_better: bool,
) -> tuple[float, ...]:
    """Return leave-one-complete-pair-out estimates."""
    return tuple(
        _paired_median_ratio_effect(
            (*pairs[:index], *pairs[index + 1 :]),
            lower_is_better=lower_is_better,
        )
        for index in range(len(pairs))
    )


def _stratified_paired_jackknife_estimates(
    pair_strata: tuple[tuple[tuple[float, float], ...], ...],
    *,
    lower_is_better: bool,
) -> tuple[tuple[float, ...], ...]:
    """Return delete-one-pair estimates grouped by fixed-design stratum."""
    groups: list[tuple[float, ...]] = []
    for stratum_index, stratum in enumerate(pair_strata):
        groups.append(
            tuple(
                _paired_median_ratio_effect(
                    tuple(
                        pair
                        for group_index, group in enumerate(pair_strata)
                        for pair_index, pair in enumerate(group)
                        if group_index != stratum_index or pair_index != deleted_index
                    ),
                    lower_is_better=lower_is_better,
                )
                for deleted_index in range(len(stratum))
            )
        )
    return tuple(groups)


def _bca_probabilities(
    bootstrap_estimates: Sequence[float],
    *,
    estimate: float,
    jackknife_estimates: Sequence[Sequence[float]],
    lower_probability: float,
    upper_probability: float,
) -> tuple[float, float] | None:
    """Return bias-corrected and accelerated bootstrap probabilities.

    For independent inference, the acceleration follows the multi-sample
    jackknife used by SciPy: each group's delete-one estimates are centered
    within that group, converted to pseudovalues, and weighted by the group's
    own size. Paired inference supplies one group of delete-one-pair estimates,
    which reduces to the standard one-sample acceleration.
    """
    count_below = sum(value < estimate for value in bootstrap_estimates)
    count_equal = sum(value == estimate for value in bootstrap_estimates)
    proportion = (count_below + 0.5 * count_equal) / len(bootstrap_estimates)
    epsilon = 0.5 / len(bootstrap_estimates)
    proportion = min(1.0 - epsilon, max(epsilon, proportion))
    bias_correction = _NORMAL.inv_cdf(proportion)

    pseudovalue_groups: list[tuple[float, ...]] = []
    for group in jackknife_estimates:
        group_size = len(group)
        group_mean = statistics.fmean(group)
        pseudovalues = tuple((group_size - 1) * (group_mean - value) for value in group)
        if any(not math.isfinite(value) for value in pseudovalues):
            return None
        pseudovalue_groups.append(pseudovalues)

    # Scale both moments by the same value. The scale cancels from the BCa
    # acceleration but prevents otherwise-valid, extreme ratios from
    # overflowing while cubing the jackknife pseudovalues.
    scale = max(
        (abs(value) for group in pseudovalue_groups for value in group),
        default=0.0,
    )
    if scale == 0.0 or not math.isfinite(scale):
        return None
    numerator = math.fsum(
        math.fsum((value / scale) ** 3 for value in group) / len(group) ** 3 for group in pseudovalue_groups
    )
    squared_sum = math.fsum(
        math.fsum((value / scale) ** 2 for value in group) / len(group) ** 2 for group in pseudovalue_groups
    )
    if squared_sum == 0.0 or not math.isfinite(squared_sum):
        return None
    acceleration = numerator / (6.0 * squared_sum**1.5)
    if not math.isfinite(acceleration):
        return None

    adjusted: list[float] = []
    for probability in (lower_probability, upper_probability):
        normal_quantile = _NORMAL.inv_cdf(probability)
        denominator = 1.0 - acceleration * (bias_correction + normal_quantile)
        if denominator == 0.0 or not math.isfinite(denominator):
            return None
        value = _NORMAL.cdf(
            bias_correction + (bias_correction + normal_quantile) / denominator,
        )
        if not math.isfinite(value):
            return None
        adjusted.append(min(1.0, max(0.0, value)))
    if adjusted[0] > adjusted[1]:
        return None
    return (adjusted[0], adjusted[1])


def _required_pairs_for_precision(
    variability: float,
    *,
    target_log_half_width: float,
    confidence_level: float,
    strata_count: int,
) -> int | None:
    """Return the smallest fixed pair count meeting a Student-t half-width."""

    def meets_target(pair_count: int) -> bool:
        critical = _student_t_critical(
            confidence_level,
            degrees_of_freedom=pair_count - strata_count,
        )
        return critical * variability / math.sqrt(pair_count) <= target_log_half_width

    minimum_estimable_pairs = max(_MINIMUM_GROUP_SIZE, strata_count + 1)
    upper = minimum_estimable_pairs
    while upper < _MAXIMUM_PLANNED_PAIRS and not meets_target(upper):
        upper = min(_MAXIMUM_PLANNED_PAIRS, upper * 2)
    if not meets_target(upper):
        return None

    lower = minimum_estimable_pairs
    while lower < upper:
        middle = (lower + upper) // 2
        if meets_target(middle):
            upper = middle
        else:
            lower = middle + 1
    return lower


def _residual_log_ratio_standard_deviation(
    log_ratios: tuple[float, ...],
    *,
    strata: tuple[str, ...] | None,
) -> float:
    """Return pooled residual variability after fitting stratum means."""
    if strata is None:
        return float(statistics.stdev(log_ratios))
    grouped: dict[str, list[float]] = {}
    for value, label in zip(log_ratios, strata, strict=True):
        grouped.setdefault(label, []).append(value)
    residual_sum_of_squares = math.fsum(
        (value - statistics.fmean(values)) ** 2 for values in grouped.values() for value in values
    )
    residual_degrees_of_freedom = len(log_ratios) - len(grouped)
    return math.sqrt(residual_sum_of_squares / residual_degrees_of_freedom)


def _round_up_to_multiple(value: int, multiple: int) -> int:
    """Return an integer rounded upward to one positive multiple."""
    return ((value + multiple - 1) // multiple) * multiple


def _student_t_critical(
    confidence_level: float,
    *,
    degrees_of_freedom: int,
) -> float:
    """Return a two-sided Student-t critical value without external dependencies."""
    target_probability = (1.0 + confidence_level) / 2.0
    lower = 0.0
    upper = 1.0
    while _student_t_cdf(upper, degrees_of_freedom=degrees_of_freedom) < target_probability:
        upper *= 2.0
        if not math.isfinite(upper):
            return math.inf
    for _ in range(80):
        middle = (lower + upper) / 2.0
        if _student_t_cdf(middle, degrees_of_freedom=degrees_of_freedom) < target_probability:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0


def _student_t_cdf(value: float, *, degrees_of_freedom: int) -> float:
    """Return the Student-t cumulative probability for a non-negative value."""
    if degrees_of_freedom <= 0:
        raise ValueError("degrees_of_freedom must be positive.")
    if value == 0.0:
        return 0.5
    if value < 0.0:
        return 1.0 - _student_t_cdf(-value, degrees_of_freedom=degrees_of_freedom)
    freedom = float(degrees_of_freedom)
    beta_argument = freedom / (freedom + value * value)
    tail_probability = 0.5 * _regularized_incomplete_beta(
        beta_argument,
        freedom / 2.0,
        0.5,
    )
    return 1.0 - tail_probability


def _regularized_incomplete_beta(value: float, alpha: float, beta: float) -> float:
    """Return the regularized incomplete beta using a continued fraction."""
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    log_scale = (
        math.lgamma(alpha + beta)
        - math.lgamma(alpha)
        - math.lgamma(beta)
        + alpha * math.log(value)
        + beta * math.log1p(-value)
    )
    scale = math.exp(log_scale)
    if value < (alpha + 1.0) / (alpha + beta + 2.0):
        return scale * _beta_continued_fraction(value, alpha, beta) / alpha
    return 1.0 - scale * _beta_continued_fraction(1.0 - value, beta, alpha) / beta


def _beta_continued_fraction(value: float, alpha: float, beta: float) -> float:
    """Evaluate the incomplete-beta continued fraction."""
    maximum_iterations = 200
    epsilon = 3e-14
    minimum = 1e-300
    alpha_plus_beta = alpha + beta
    alpha_plus_one = alpha + 1.0
    alpha_minus_one = alpha - 1.0
    denominator_factor = 1.0 - alpha_plus_beta * value / alpha_plus_one
    if abs(denominator_factor) < minimum:
        denominator_factor = minimum
    denominator_factor = 1.0 / denominator_factor
    numerator_factor = 1.0
    fraction = denominator_factor
    for iteration in range(1, maximum_iterations + 1):
        doubled = 2 * iteration
        coefficient = iteration * (beta - iteration) * value / ((alpha_minus_one + doubled) * (alpha + doubled))
        denominator_factor = 1.0 + coefficient * denominator_factor
        if abs(denominator_factor) < minimum:
            denominator_factor = minimum
        numerator_factor = 1.0 + coefficient / numerator_factor
        if abs(numerator_factor) < minimum:
            numerator_factor = minimum
        denominator_factor = 1.0 / denominator_factor
        fraction *= denominator_factor * numerator_factor

        coefficient = (
            -(alpha + iteration)
            * (alpha_plus_beta + iteration)
            * value
            / ((alpha + doubled) * (alpha_plus_one + doubled))
        )
        denominator_factor = 1.0 + coefficient * denominator_factor
        if abs(denominator_factor) < minimum:
            denominator_factor = minimum
        numerator_factor = 1.0 + coefficient / numerator_factor
        if abs(numerator_factor) < minimum:
            numerator_factor = minimum
        denominator_factor = 1.0 / denominator_factor
        delta = denominator_factor * numerator_factor
        fraction *= delta
        if abs(delta - 1.0) <= epsilon:
            break
    return fraction


def _quantile(values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated quantile from finite values."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    upper_weight = position - lower_index
    return ordered[lower_index] * (1.0 - upper_weight) + ordered[upper_index] * upper_weight
