"""Tests for run-level benchmark statistical inference."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Literal, cast

import pytest

import benchmatrix.bench_statistics as statistics_module
from benchmatrix.bench_statistics import (
    BootstrapInterval,
    bootstrap_median_ratio_interval,
    bootstrap_paired_median_ratio_interval,
    plan_paired_precision,
)

pytestmark = pytest.mark.unit


def _bounds(interval: BootstrapInterval) -> tuple[float, float]:
    """Return complete interval bounds for assertions."""
    assert interval.low is not None
    assert interval.high is not None
    return (interval.low, interval.high)


def test_bca_interval_is_deterministic_and_contains_observed_effect() -> None:
    first = bootstrap_median_ratio_interval(
        (0.99, 1.0, 1.01, 1.02, 1.03),
        (1.08, 1.09, 1.1, 1.11, 1.12),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=5_000,
        random_seed=17,
    )
    second = bootstrap_median_ratio_interval(
        (0.99, 1.0, 1.01, 1.02, 1.03),
        (1.08, 1.09, 1.1, 1.11, 1.12),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=5_000,
        random_seed=17,
    )

    assert first == second
    assert first.adequate
    assert first.method == "bca_bootstrap"
    assert first.estimate is not None
    assert first.estimate == pytest.approx(-8.910891089108919)
    low, high = _bounds(first)
    assert low < first.estimate
    assert high > first.estimate


def test_seeded_interval_is_invariant_to_run_order() -> None:
    baseline = (0.99, 1.0, 1.01, 1.02, 1.03)
    candidate = (1.08, 1.09, 1.1, 1.11, 1.12)
    ordered = bootstrap_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=19,
    )
    permuted = bootstrap_median_ratio_interval(
        tuple(reversed(baseline)),
        (candidate[2], candidate[4], candidate[0], candidate[3], candidate[1]),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=19,
    )

    assert permuted == ordered


def test_interval_effect_is_scale_invariant() -> None:
    original = bootstrap_median_ratio_interval(
        (10.0, 11.0, 12.0, 13.0, 14.0),
        (9.0, 10.0, 11.0, 12.0, 13.0),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=3,
    )
    scaled = bootstrap_median_ratio_interval(
        (10_000.0, 11_000.0, 12_000.0, 13_000.0, 14_000.0),
        (9_000.0, 10_000.0, 11_000.0, 12_000.0, 13_000.0),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=3,
    )

    assert scaled.estimate == pytest.approx(original.estimate)
    assert scaled.low == pytest.approx(original.low)
    assert scaled.high == pytest.approx(original.high)


def test_direction_changes_the_effect_sign() -> None:
    lower = bootstrap_median_ratio_interval(
        (10.0, 11.0, 12.0, 13.0, 14.0),
        (9.0, 10.0, 11.0, 12.0, 13.0),
        lower_is_better=True,
        confidence_level=0.9,
        resamples=1_000,
        random_seed=11,
    )
    higher = bootstrap_median_ratio_interval(
        (10.0, 11.0, 12.0, 13.0, 14.0),
        (9.0, 10.0, 11.0, 12.0, 13.0),
        lower_is_better=False,
        confidence_level=0.9,
        resamples=1_000,
        random_seed=11,
    )

    assert lower.estimate is not None
    assert higher.estimate is not None
    lower_low, lower_high = _bounds(lower)
    higher_low, higher_high = _bounds(higher)
    assert lower.estimate == pytest.approx(-higher.estimate)
    assert lower_low == pytest.approx(-higher_high)
    assert lower_high == pytest.approx(-higher_low)


def test_unequal_group_bca_matches_frozen_independent_oracle() -> None:
    # This fixture is deliberately unequal and skewed. A pooled delete-one
    # acceleration gives approximately (-57.01, 4.31), so these frozen values
    # detect that incorrect shortcut. The expected interval uses the standard
    # independent multi-sample acceleration and R-7 interpolation.
    baseline = (65.132, 78.714, 100.035, 100.552, 107.697, 122.651, 127.78, 144.66)
    candidate = (
        84.892,
        99.466,
        103.97,
        104.953,
        105.603,
        111.085,
        112.064,
        113.995,
        119.824,
        120.55,
        123.407,
        123.585,
        128.723,
        138.069,
        144.071,
        208.652,
        323.099,
    )

    interval = bootstrap_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=50_000,
        random_seed=47,
    )

    assert interval.method == "bca_bootstrap"
    assert interval.estimate == pytest.approx(-15.077623421961196)
    low, high = _bounds(interval)
    assert low == pytest.approx(-63.53253550829587)
    assert high == pytest.approx(3.550280445239384)


def test_bonferroni_confidence_can_change_a_practical_decision() -> None:
    baseline = (96.73, 100.13, 102.34, 102.87, 104.07)
    candidate = (108.95, 108.98, 109.68, 109.88, 110.3)
    per_cell = bootstrap_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=50_000,
        random_seed=47,
    )
    family_of_ten = bootstrap_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.995,
        resamples=50_000,
        random_seed=47,
    )

    per_cell_low, per_cell_high = _bounds(per_cell)
    family_low, family_high = _bounds(family_of_ten)
    assert per_cell.estimate == pytest.approx(-7.172171194059018)
    assert (per_cell_low, per_cell_high) == pytest.approx(
        (-13.387780419725015, -5.390602479100615),
    )
    assert (family_low, family_high) == pytest.approx(
        (-14.028739791171297, -4.689151532622282),
    )
    assert per_cell_high < -5.0
    assert family_high >= -5.0
    assert family_low <= per_cell_low
    assert family_high >= per_cell_high


def test_degenerate_data_uses_percentile_fallback() -> None:
    interval = bootstrap_median_ratio_interval(
        (1.0,) * 5,
        (1.1,) * 5,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1_000,
        random_seed=0,
    )

    assert interval.adequate
    assert interval.method == "percentile_bootstrap"
    assert interval.estimate == pytest.approx(-10.0)
    assert interval.low == pytest.approx(-10.0)
    assert interval.high == pytest.approx(-10.0)
    assert interval.warnings


@pytest.mark.parametrize(
    ("baseline", "candidate", "message"),
    [
        ((1.0,), (1.0, 1.1), "baseline has 1 run"),
        ((1.0, 1.1), (1.0,), "candidate has 1 run"),
        ((0.0, 1.0), (1.0, 1.1), "baseline run statistics"),
        ((1.0, 1.1), (float("inf"), 1.0), "candidate run statistics"),
        (
            cast(tuple[float, ...], ("invalid", 1.0)),
            (1.0, 1.1),
            "finite numeric values",
        ),
    ],
)
def test_invalid_measurements_return_explicit_issues(
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
    message: str,
) -> None:
    interval = bootstrap_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1_000,
        random_seed=0,
    )

    assert not interval.adequate
    assert interval.estimate is None
    assert any(message in issue for issue in interval.issues)


@pytest.mark.parametrize(
    ("confidence_level", "resamples", "message"),
    [
        (0.0, 1_000, "confidence level"),
        (1.0, 1_000, "confidence level"),
        (float("nan"), 1_000, "confidence level"),
        (0.95, 0, "resamples"),
        (0.95, cast(int, True), "resamples"),
    ],
)
def test_invalid_inference_controls_return_explicit_issues(
    confidence_level: float,
    resamples: int,
    message: str,
) -> None:
    interval = bootstrap_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=confidence_level,
        resamples=resamples,
        random_seed=0,
    )

    assert not interval.adequate
    assert any(message in issue for issue in interval.issues)


def test_nonfinite_ratio_effect_returns_an_issue() -> None:
    interval = bootstrap_median_ratio_interval(
        (5e-324, 5e-324),
        (1e308, 1e308),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1_000,
        random_seed=0,
    )

    assert not interval.adequate
    assert interval.estimate is None
    assert interval.issues == ("observed median-ratio effect is not finite",)


def test_extreme_independent_resample_returns_nonfinite_effect_issue() -> None:
    interval = bootstrap_median_ratio_interval(
        (5e-324, 1.0, 1.0),
        (1.0, 1.0, 1e308),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=1,
    )

    assert not interval.adequate
    assert interval.issues == ("bootstrap median-ratio effect is not finite",)


def test_overflowing_point_estimates_return_explicit_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def overflow(*_args: object, **_kwargs: object) -> float:
        raise OverflowError

    monkeypatch.setattr(statistics_module, "_median_ratio_effect", overflow)
    independent = bootstrap_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )
    monkeypatch.setattr(statistics_module, "_paired_median_ratio_effect", overflow)
    paired = bootstrap_paired_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )

    assert independent.issues == ("observed median-ratio effect is not finite",)
    assert paired.issues == ("observed paired median-ratio effect is not finite",)


def test_overflowing_bootstrap_estimates_return_explicit_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    independent_calls = 0

    def independent_overflows_after_point(*_args: object, **_kwargs: object) -> float:
        nonlocal independent_calls
        independent_calls += 1
        if independent_calls > 1:
            raise OverflowError
        return 0.0

    paired_calls = 0

    def paired_overflows_after_point(*_args: object, **_kwargs: object) -> float:
        nonlocal paired_calls
        paired_calls += 1
        if paired_calls > 1:
            raise OverflowError
        return 0.0

    monkeypatch.setattr(
        statistics_module,
        "_median_ratio_effect",
        independent_overflows_after_point,
    )
    independent = bootstrap_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )
    monkeypatch.setattr(
        statistics_module,
        "_paired_median_ratio_effect",
        paired_overflows_after_point,
    )
    paired = bootstrap_paired_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )

    assert independent.issues == ("bootstrap median-ratio effect is not finite",)
    assert paired.issues == ("bootstrap paired median-ratio effect is not finite",)


def test_overflowing_jackknife_uses_percentile_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def overflow(*_args: object, **_kwargs: object) -> float:
        raise OverflowError

    monkeypatch.setattr(statistics_module, "_jackknife_estimates", overflow)
    monkeypatch.setattr(statistics_module, "_paired_jackknife_estimates", overflow)
    independent = bootstrap_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )
    paired = bootstrap_paired_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )

    assert independent.method == "percentile_bootstrap"
    assert paired.method == "percentile_bootstrap"


def test_nonfinite_jackknife_uses_percentile_fallback_and_exact_quantile() -> None:
    baseline = (5e-324, 1.0, 1.0)
    candidate = (1.0, 1.0, 1e308)
    independent = bootstrap_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )
    paired = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )

    assert independent.method == "percentile_bootstrap"
    assert paired.method == "percentile_bootstrap"
    assert _bounds(independent) == pytest.approx((-0.0, -0.0))
    assert _bounds(paired) == pytest.approx((-0.0, -0.0))


def test_interval_bounds_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quantiles = iter((2.0, 1.0, 4.0, 3.0))

    def reversed_quantile(*_args: object, **_kwargs: object) -> float:
        return next(quantiles)

    monkeypatch.setattr(statistics_module, "_quantile", reversed_quantile)
    independent = bootstrap_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )
    paired = bootstrap_paired_median_ratio_interval(
        (1.0, 1.1),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )

    assert _bounds(independent) == (1.0, 2.0)
    assert _bounds(paired) == (3.0, 4.0)


def test_paired_bca_matches_frozen_blocked_oracle() -> None:
    baseline = (80.0, 90.0, 100.0, 110.0, 120.0, 130.0, 140.0)
    candidate = (75.0, 84.0, 93.0, 101.0, 112.0, 119.0, 133.0)

    paired = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=50_000,
        random_seed=47,
    )
    independent = bootstrap_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=50_000,
        random_seed=47,
    )

    assert paired.method == "bca_bootstrap"
    assert paired.estimate == pytest.approx(8.18181818181818)
    assert _bounds(paired) == pytest.approx((6.666666666666665, 8.461538461538465))
    assert paired.low is not None
    assert paired.high is not None
    assert independent.low is not None
    assert independent.high is not None
    assert paired.low <= 8.0 <= paired.high
    assert paired.high - paired.low < independent.high - independent.low


def test_paired_interval_is_deterministic_and_invariant_to_pair_order() -> None:
    baseline = (80.0, 90.0, 100.0, 110.0, 120.0, 130.0, 140.0)
    candidate = (75.0, 84.0, 93.0, 101.0, 112.0, 119.0, 133.0)
    first = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=19,
    )
    permutation = (3, 0, 6, 2, 5, 1, 4)
    permuted = bootstrap_paired_median_ratio_interval(
        tuple(baseline[index] for index in permutation),
        tuple(candidate[index] for index in permutation),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=19,
    )

    assert first == permuted


def test_unstratified_paired_interval_reports_exchangeability_assumption() -> None:
    interval = bootstrap_paired_median_ratio_interval(
        (80.0, 90.0, 100.0, 110.0),
        (75.0, 84.0, 93.0, 101.0),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1_000,
        random_seed=19,
    )

    assert interval.adequate
    assert any("exchangeable" in warning for warning in interval.warnings)


def test_stratified_paired_bootstrap_preserves_fixed_orientation_counts() -> None:
    baseline = (100.0,) * 8
    candidate = (90.0,) * 4 + (110.0,) * 4
    strata = ("AB",) * 4 + ("BA",) * 4

    stratified = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=5_000,
        random_seed=7,
        strata=strata,
    )
    exchangeable = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=5_000,
        random_seed=7,
    )

    assert stratified.adequate
    assert stratified.estimate == pytest.approx(0.0)
    assert _bounds(stratified) == pytest.approx((0.0, 0.0))
    assert not any("exchangeable" in warning for warning in stratified.warnings)
    exchangeable_low, exchangeable_high = _bounds(exchangeable)
    assert exchangeable_low < 0.0 < exchangeable_high


def test_stratified_paired_interval_is_invariant_to_labeled_pair_order() -> None:
    baseline = (80.0, 90.0, 100.0, 110.0, 120.0, 130.0, 140.0, 150.0)
    candidate = (75.0, 84.0, 93.0, 101.0, 112.0, 119.0, 133.0, 141.0)
    strata = ("AB", "BA", "AB", "BA", "AB", "BA", "AB", "BA")
    first = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=29,
        strata=strata,
    )
    permutation = (3, 0, 6, 2, 7, 5, 1, 4)
    permuted = bootstrap_paired_median_ratio_interval(
        tuple(baseline[index] for index in permutation),
        tuple(candidate[index] for index in permutation),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=29,
        strata=tuple(strata[index] for index in permutation),
    )

    assert permuted == first


@pytest.mark.parametrize(
    ("strata", "message"),
    [
        (("AB",), "one label per complete pair"),
        (("AB", "", "AB", "BA"), "non-empty strings"),
        (("AB", "AB", "AB", "BA"), "at least 2 complete pairs"),
        (cast(Sequence[str], "ABBA"), "not one string"),
    ],
)
def test_stratified_paired_interval_validates_strata(
    strata: Sequence[str],
    message: str,
) -> None:
    interval = bootstrap_paired_median_ratio_interval(
        (100.0,) * 4,
        (95.0, 96.0, 97.0, 98.0),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1_000,
        random_seed=0,
        strata=strata,
    )

    assert not interval.adequate
    assert any(message in issue for issue in interval.issues)


def test_paired_interval_preserves_pair_identity() -> None:
    baseline = (80.0, 90.0, 100.0, 110.0, 120.0, 130.0, 140.0)
    candidate = (75.0, 84.0, 93.0, 101.0, 112.0, 119.0, 133.0)
    matched = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=5_000,
        random_seed=23,
    )
    mismatched = bootstrap_paired_median_ratio_interval(
        baseline,
        tuple(reversed(candidate)),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=5_000,
        random_seed=23,
    )

    assert matched.estimate == pytest.approx(mismatched.estimate)
    assert _bounds(matched) != pytest.approx(_bounds(mismatched))


def test_paired_interval_direction_reverses_effect_and_bounds() -> None:
    baseline = (80.0, 90.0, 100.0, 110.0, 120.0, 130.0, 140.0)
    candidate = (75.0, 84.0, 93.0, 101.0, 112.0, 119.0, 133.0)
    lower = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=31,
    )
    higher = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=False,
        confidence_level=0.95,
        resamples=2_000,
        random_seed=31,
    )

    assert lower.estimate == pytest.approx(-cast(float, higher.estimate))
    assert lower.low == pytest.approx(-cast(float, higher.high))
    assert lower.high == pytest.approx(-cast(float, higher.low))


def test_degenerate_paired_data_uses_percentile_fallback() -> None:
    interval = bootstrap_paired_median_ratio_interval(
        (10.0, 20.0, 30.0, 40.0, 50.0),
        (9.0, 18.0, 27.0, 36.0, 45.0),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1_000,
        random_seed=0,
    )

    assert interval.adequate
    assert interval.method == "percentile_bootstrap"
    assert interval.estimate == pytest.approx(10.0)
    assert interval.low == pytest.approx(10.0)
    assert interval.high == pytest.approx(10.0)
    assert interval.warnings


@pytest.mark.parametrize(
    ("baseline", "candidate", "confidence", "resamples", "random_seed", "message"),
    [
        ((1.0, 1.1), (1.0,), 0.95, 1_000, 0, "equal lengths"),
        ((1.0,), (1.0,), 0.95, 1_000, 0, "at least 2"),
        ((0.0, 1.0), (1.0, 1.1), 0.95, 1_000, 0, "baseline run statistics"),
        ((1.0, 1.1), (1.0, float("nan")), 0.95, 1_000, 0, "candidate run statistics"),
        ((1.0, 1.1), (1.0, 1.1), 0.0, 1_000, 0, "confidence level"),
        ((1.0, 1.1), (1.0, 1.1), 0.95, 0, 0, "resamples"),
        ((1.0, 1.1), (1.0, 1.1), 0.95, 1_000, -1, "random seed"),
        ((1.0, 1.1), (1.0, 1.1), 0.95, 1_000, cast(int, True), "random seed"),
    ],
)
def test_invalid_paired_inputs_return_explicit_issues(
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
    confidence: float,
    resamples: int,
    random_seed: int,
    message: str,
) -> None:
    interval = bootstrap_paired_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=confidence,
        resamples=resamples,
        random_seed=random_seed,
    )

    assert not interval.adequate
    assert any(message in issue for issue in interval.issues)


def test_non_numeric_paired_input_returns_an_explicit_issue() -> None:
    interval = bootstrap_paired_median_ratio_interval(
        cast(tuple[float, ...], ("invalid", 1.0)),
        (1.0, 1.1),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1_000,
        random_seed=0,
    )

    assert not interval.adequate
    assert interval.issues == ("paired run statistics must be finite numeric values",)


def test_extreme_paired_resample_returns_nonfinite_effect_issue() -> None:
    interval = bootstrap_paired_median_ratio_interval(
        (5e-324, 1.0, 1.0),
        (1e308, 1.0, 1.0),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1_000,
        random_seed=0,
    )

    assert not interval.adequate
    assert interval.issues == ("bootstrap paired median-ratio effect is not finite",)


def test_nonfinite_paired_point_estimate_returns_an_issue() -> None:
    interval = bootstrap_paired_median_ratio_interval(
        (5e-324, 5e-324),
        (1e308, 1e308),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=1,
        random_seed=0,
    )

    assert not interval.adequate
    assert interval.issues == ("observed paired median-ratio effect is not finite",)


def test_nonfinite_bca_pseudovalues_use_percentile_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def extreme_jackknife(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[tuple[float, ...], tuple[float, ...]]:
        extreme_group = (1e308, -1e308, 0.0)
        return (extreme_group, extreme_group)

    monkeypatch.setattr(statistics_module, "_jackknife_estimates", extreme_jackknife)
    interval = bootstrap_median_ratio_interval(
        (1.0, 1.1, 1.2),
        (1.0, 1.1, 1.2),
        lower_is_better=True,
        confidence_level=0.95,
        resamples=10,
        random_seed=0,
    )

    assert interval.adequate
    assert interval.method == "percentile_bootstrap"
    assert interval.warnings == ("BCa adjustment was degenerate; used a percentile bootstrap interval.",)


def _precision_pilot() -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return a paired pilot with an exactly known log-ratio spread."""
    baseline = (100.0,) * 5
    candidate = tuple(100.0 * math.exp(value) for value in (-0.1, -0.05, 0.0, 0.05, 0.1))
    return baseline, candidate


def test_precision_plan_matches_student_t_oracle() -> None:
    baseline, candidate = _precision_pilot()

    plan = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
        confidence_level=0.95,
    )

    assert plan.adequate
    assert plan.method == "paired_log_ratio_t"
    assert plan.pilot_pairs == 5
    assert plan.pilot_log_ratio_standard_deviation == pytest.approx(math.sqrt(0.00625))
    assert plan.critical_value == pytest.approx(2.16036865646279)
    assert plan.unconstrained_required_pairs == 13
    assert plan.required_pairs == 14
    assert plan.additional_pairs == 9
    assert plan.minimum_pairs == 2
    assert plan.pair_count_multiple == 2
    assert plan.strata_count == 1
    assert any("not power analysis" in assumption for assumption in plan.assumptions)
    assert any("fresh confirmatory collection" in assumption for assumption in plan.assumptions)


def test_precision_plan_is_scale_and_direction_invariant() -> None:
    baseline, candidate = _precision_pilot()
    original = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
    )
    scaled_and_reversed = plan_paired_precision(
        tuple(value * 1_000.0 for value in baseline),
        tuple(value * 1_000.0 for value in candidate),
        lower_is_better=True,
        target_half_width_percent=5.0,
    )

    assert scaled_and_reversed.required_pairs == original.required_pairs
    assert scaled_and_reversed.critical_value == pytest.approx(original.critical_value)
    assert scaled_and_reversed.pilot_log_ratio_standard_deviation == pytest.approx(
        original.pilot_log_ratio_standard_deviation
    )


def test_precision_plan_removes_fixed_orientation_effect_from_variability() -> None:
    baseline = (100.0,) * 6
    log_ratios = (-0.11, -0.10, -0.09, 0.09, 0.10, 0.11)
    candidate = tuple(100.0 * math.exp(value) for value in log_ratios)
    strata = ("AB",) * 3 + ("BA",) * 3

    stratified = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
        strata=strata,
    )
    exchangeable = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
    )

    assert stratified.adequate
    assert stratified.strata_count == 2
    assert stratified.pilot_log_ratio_standard_deviation == pytest.approx(0.01)
    assert stratified.unconstrained_required_pairs == 4
    assert stratified.required_pairs == 4
    # Two fitted stratum means leave 4 - 2 future residual degrees of freedom.
    assert stratified.critical_value == pytest.approx(4.302652729749456)
    assert exchangeable.pilot_log_ratio_standard_deviation == pytest.approx(0.10990905331227277)
    assert exchangeable.required_pairs == 22


def test_precision_plan_does_not_turn_pure_order_effect_into_false_precision() -> None:
    baseline = (100.0,) * 8
    candidate = (90.0,) * 4 + (110.0,) * 4

    stratified = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=True,
        target_half_width_percent=5.0,
        strata=("AB",) * 4 + ("BA",) * 4,
    )
    exchangeable = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=True,
        target_half_width_percent=5.0,
    )

    assert not stratified.adequate
    assert stratified.pilot_log_ratio_standard_deviation == 0.0
    assert any("zero variability" in issue for issue in stratified.issues)
    assert exchangeable.adequate
    assert exchangeable.required_pairs == 22


def test_precision_plan_applies_minimum_and_pair_count_multiple() -> None:
    baseline, candidate = _precision_pilot()

    plan = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
        minimum_pairs=17,
        pair_count_multiple=4,
    )
    unconstrained = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
        pair_count_multiple=1,
    )

    assert plan.unconstrained_required_pairs == 13
    assert plan.minimum_pairs == 17
    assert plan.pair_count_multiple == 4
    assert plan.required_pairs == 20
    assert plan.additional_pairs == 15
    assert unconstrained.required_pairs == 13


def test_precision_plan_applies_bonferroni_family_confidence() -> None:
    baseline, candidate = _precision_pilot()
    per_cell = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
        confidence_level=0.95,
        family_size=10,
        multiplicity="none",
    )
    family = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
        confidence_level=0.95,
        family_size=10,
        multiplicity="bonferroni",
    )

    assert per_cell.adjusted_confidence_level == pytest.approx(0.95)
    assert per_cell.unconstrained_required_pairs == 13
    assert per_cell.required_pairs == 14
    assert family.adjusted_confidence_level == pytest.approx(0.995)
    assert family.critical_value == pytest.approx(3.0781994605435195)
    assert family.required_pairs == 26
    assert family.additional_pairs == 21


def test_narrower_precision_target_requires_more_pairs() -> None:
    baseline, candidate = _precision_pilot()
    wide = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
    )
    narrow = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=2.5,
    )

    assert wide.required_pairs == 14
    assert narrow.required_pairs == 42


def test_precision_plan_rejects_degenerate_pilot_without_false_certainty() -> None:
    plan = plan_paired_precision(
        (10.0, 20.0, 30.0, 40.0, 50.0),
        (9.0, 18.0, 27.0, 36.0, 45.0),
        lower_is_better=True,
        target_half_width_percent=5.0,
    )

    assert not plan.adequate
    assert plan.pilot_log_ratio_standard_deviation == pytest.approx(0.0, abs=1e-15)
    assert plan.required_pairs is None
    assert any("zero variability" in issue for issue in plan.issues)


def test_small_precision_pilot_is_labeled_unstable() -> None:
    plan = plan_paired_precision(
        (100.0, 100.0),
        (95.0, 105.0),
        lower_is_better=True,
        target_half_width_percent=10.0,
    )

    assert plan.adequate
    assert any("fewer than 5 pairs" in warning for warning in plan.warnings)


@pytest.mark.parametrize(
    ("target", "confidence", "family_size", "multiplicity", "exception", "message"),
    [
        (0.0, 0.95, 1, "bonferroni", ValueError, "target_half_width_percent"),
        (float("nan"), 0.95, 1, "bonferroni", ValueError, "target_half_width_percent"),
        (cast(float, True), 0.95, 1, "bonferroni", TypeError, "target_half_width_percent"),
        (5.0, 1.0, 1, "bonferroni", ValueError, "confidence_level"),
        (5.0, cast(float, True), 1, "bonferroni", TypeError, "confidence_level"),
        (5.0, 0.95, 0, "bonferroni", ValueError, "family_size"),
        (5.0, 0.95, cast(int, True), "bonferroni", TypeError, "family_size"),
        (5.0, 0.95, 1, "invalid", ValueError, "multiplicity"),
        (5.0, 0.95, 2**60, "bonferroni", ValueError, "too large"),
    ],
)
def test_precision_plan_validates_controls(
    target: float,
    confidence: float,
    family_size: int,
    multiplicity: str,
    exception: type[Exception],
    message: str,
) -> None:
    with pytest.raises(exception, match=message):
        plan_paired_precision(
            (100.0, 100.0),
            (95.0, 105.0),
            lower_is_better=True,
            target_half_width_percent=target,
            confidence_level=confidence,
            family_size=family_size,
            multiplicity=cast(Literal["bonferroni", "none"], multiplicity),
        )


@pytest.mark.parametrize(
    ("minimum_pairs", "pair_count_multiple", "exception", "message"),
    [
        (1, 2, ValueError, "minimum_pairs"),
        (cast(int, True), 2, TypeError, "minimum_pairs"),
        (2, 0, ValueError, "pair_count_multiple"),
        (2, cast(int, True), TypeError, "pair_count_multiple"),
    ],
)
def test_precision_plan_validates_design_constraints(
    minimum_pairs: int,
    pair_count_multiple: int,
    exception: type[Exception],
    message: str,
) -> None:
    with pytest.raises(exception, match=message):
        plan_paired_precision(
            (100.0, 100.0),
            (95.0, 105.0),
            lower_is_better=True,
            target_half_width_percent=5.0,
            minimum_pairs=minimum_pairs,
            pair_count_multiple=pair_count_multiple,
        )


@pytest.mark.parametrize(
    ("strata", "message"),
    [
        (("AB",), "one label per complete pair"),
        (("AB", "BA", "AB", "BA"), "one label per complete pair"),
        (("AB", "AB", "BA"), "at least 2 complete pairs"),
        (cast(Sequence[str], "AB"), "not one string"),
    ],
)
def test_precision_plan_returns_strata_issues(
    strata: Sequence[str],
    message: str,
) -> None:
    plan = plan_paired_precision(
        (100.0, 100.0, 100.0),
        (95.0, 100.0, 105.0),
        lower_is_better=True,
        target_half_width_percent=5.0,
        strata=strata,
    )

    assert not plan.adequate
    assert any(message in issue for issue in plan.issues)


@pytest.mark.parametrize(
    ("baseline", "candidate", "message"),
    [
        ((1.0,), (1.0,), "at least 2"),
        ((1.0, 1.1), (1.0,), "equal lengths"),
        ((0.0, 1.0), (1.0, 1.1), "baseline run statistics"),
        ((1.0, 1.1), (1.0, float("inf")), "candidate run statistics"),
    ],
)
def test_precision_plan_returns_pilot_data_issues(
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
    message: str,
) -> None:
    plan = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=True,
        target_half_width_percent=5.0,
    )

    assert not plan.adequate
    assert any(message in issue for issue in plan.issues)


def test_precision_plan_returns_non_numeric_pilot_issue() -> None:
    plan = plan_paired_precision(
        cast(tuple[float, ...], ("invalid", 1.0)),
        (1.0, 1.1),
        lower_is_better=True,
        target_half_width_percent=5.0,
    )

    assert not plan.adequate
    assert plan.pilot_pairs == 0
    assert plan.issues == ("paired pilot statistics must be finite numeric values",)


def test_precision_plan_reports_unsupported_large_pair_count() -> None:
    baseline, candidate = _precision_pilot()
    plan = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5e-324,
    )

    assert not plan.adequate
    assert plan.required_pairs is None
    assert any("exceeds" in issue for issue in plan.issues)


def test_precision_plan_reports_nonfinite_variability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def overflow(*_args: object, **_kwargs: object) -> float:
        raise OverflowError

    monkeypatch.setattr(statistics_module.statistics, "stdev", overflow)
    baseline, candidate = _precision_pilot()
    plan = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
    )

    assert not plan.adequate
    assert plan.pilot_log_ratio_standard_deviation is None
    assert plan.issues == ("paired pilot log-ratio variability is not finite",)


def test_student_t_kernel_handles_domain_boundaries_and_symmetry() -> None:
    with pytest.raises(ValueError, match="degrees_of_freedom"):
        statistics_module._student_t_cdf(1.0, degrees_of_freedom=0)

    assert statistics_module._student_t_cdf(0.0, degrees_of_freedom=5) == 0.5
    positive = statistics_module._student_t_cdf(1.5, degrees_of_freedom=5)
    negative = statistics_module._student_t_cdf(-1.5, degrees_of_freedom=5)
    assert negative == pytest.approx(1.0 - positive)
    assert statistics_module._regularized_incomplete_beta(0.0, 2.0, 3.0) == 0.0
    assert statistics_module._regularized_incomplete_beta(1.0, 2.0, 3.0) == 1.0


def test_precision_plan_value_object_rejects_inconsistent_additional_count() -> None:
    baseline, candidate = _precision_pilot()
    plan = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
        multiplicity="none",
    )

    assert plan.additional_pairs is not None
    with pytest.raises(ValueError, match="inconsistent"):
        replace(plan, additional_pairs=plan.additional_pairs - 1)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"method": "invalid"}, "method"),
        ({"pilot_pairs": -1}, "pilot_pairs"),
        ({"target_half_width_percent": 0.0}, "target_half_width_percent"),
        ({"confidence_level": 0.0}, "confidence_level"),
        ({"adjusted_confidence_level": 1.0}, "adjusted_confidence_level"),
        ({"adjusted_confidence_level": 0.9}, "lower"),
        ({"multiplicity": "invalid"}, "multiplicity"),
        ({"family_size": 0}, "family_size"),
        ({"adjusted_confidence_level": 0.99}, "Unadjusted"),
        ({"pilot_log_ratio_standard_deviation": -0.1}, "variability"),
        ({"critical_value": 0.0}, "critical_value"),
        ({"critical_value": None}, "present together"),
        ({"required_pairs": 1, "additional_pairs": 0}, "required_pairs"),
        ({"minimum_pairs": 1}, "minimum_pairs"),
        ({"pair_count_multiple": 0}, "pair_count_multiple"),
        ({"strata_count": -1}, "strata_count"),
        ({"strata_count": 0}, "fitted stratum"),
        ({"unconstrained_required_pairs": 1}, "residual degrees"),
        ({"unconstrained_required_pairs": 12}, "design constraints"),
        ({"minimum_pairs": 15}, "design constraints"),
        ({"assumptions": ()}, "assumptions"),
        ({"warnings": ("",)}, "warnings"),
    ],
)
def test_precision_plan_value_object_validates_fields(updates: dict[str, object], message: str) -> None:
    baseline, candidate = _precision_pilot()
    plan = plan_paired_precision(
        baseline,
        candidate,
        lower_is_better=False,
        target_half_width_percent=5.0,
        multiplicity="none",
    )

    with pytest.raises(ValueError, match=message):
        replace(plan, **updates)
