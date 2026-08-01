"""Fixed-seed operating-characteristic checks for statistical inference."""

from __future__ import annotations

import math
import random
from typing import Literal, TypeAlias

import pytest

from benchmatrix.bench_statistics import (
    BootstrapInterval,
    bootstrap_median_ratio_interval,
    bootstrap_paired_median_ratio_interval,
)

pytestmark = pytest.mark.slow

_Decision: TypeAlias = Literal["regressed", "unchanged", "inconclusive"]


def _bounds(interval: BootstrapInterval) -> tuple[float, float]:
    """Return complete interval bounds from one simulated comparison."""
    assert interval.adequate
    assert interval.low is not None
    assert interval.high is not None
    return (interval.low, interval.high)


def _lognormal_interval(
    generator: random.Random,
    *,
    sample_size: int,
    sigma: float,
    candidate_ratio: float = 1.0,
    confidence_level: float = 0.95,
) -> BootstrapInterval:
    """Generate two run groups and return their seeded bootstrap interval."""
    baseline = tuple(generator.lognormvariate(0.0, sigma) for _ in range(sample_size))
    candidate = tuple(generator.lognormvariate(0.0, sigma) * candidate_ratio for _ in range(sample_size))
    return bootstrap_median_ratio_interval(
        baseline,
        candidate,
        lower_is_better=True,
        confidence_level=confidence_level,
        resamples=1_000,
        random_seed=generator.randrange(2**32),
    )


def _classify(interval: BootstrapInterval, *, threshold_percent: float) -> _Decision:
    """Apply the practical-effect interval rule used by comparisons."""
    low, high = _bounds(interval)
    if high < -threshold_percent:
        return "regressed"
    if low >= -threshold_percent and high <= threshold_percent:
        return "unchanged"
    return "inconclusive"


def test_bca_interval_has_reasonable_null_coverage() -> None:
    """Catch gross undercoverage without treating Monte Carlo as an oracle."""
    generator = random.Random(8128)
    covered = 0
    simulations = 80
    for _ in range(simulations):
        interval = _lognormal_interval(
            generator,
            sample_size=15,
            sigma=0.10,
        )
        low, high = _bounds(interval)
        covered += low <= 0.0 <= high

    # The fixed seed currently covers 77/80. The deliberately broad range
    # detects a badly calibrated implementation while tolerating harmless
    # changes to the deterministic resampling implementation.
    assert 70 <= covered <= simulations


def test_paired_bca_has_reasonable_blocked_design_coverage() -> None:
    """Catch gross paired undercoverage while retaining shared block noise."""
    generator = random.Random(8129)
    covered = 0
    simulations = 50
    for _ in range(simulations):
        baseline: list[float] = []
        candidate: list[float] = []
        for _ in range(30):
            shared_log_noise = generator.gauss(0.0, 0.35)
            candidate_log_noise = generator.gauss(0.0, 0.04)
            baseline.append(math.exp(shared_log_noise))
            candidate.append(0.95 * math.exp(shared_log_noise + candidate_log_noise))
        interval = bootstrap_paired_median_ratio_interval(
            baseline,
            candidate,
            lower_is_better=True,
            confidence_level=0.95,
            resamples=1_000,
            random_seed=generator.randrange(2**32),
        )
        low, high = _bounds(interval)
        covered += low <= 5.0 <= high

    # The fixed seed currently covers 44/50. This broad lower bound is an
    # implementation-regression check, not evidence of exact finite-sample
    # calibration for a non-smooth median-ratio estimator.
    assert 40 <= covered <= simulations


def test_stratified_paired_bca_preserves_fixed_orientation_design() -> None:
    """Exercise coverage and width when AB/BA effects are fixed by design."""
    generator = random.Random(9129)
    covered = 0
    stratified_narrower = 0
    simulations = 30
    for _ in range(simulations):
        baseline: list[float] = []
        candidate: list[float] = []
        strata: list[str] = []
        for pair_index in range(40):
            shared_log_noise = generator.gauss(0.0, 0.20)
            residual_log_noise = generator.gauss(0.0, 0.025)
            orientation_effect = -0.08 if pair_index % 2 == 0 else 0.08
            baseline.append(math.exp(shared_log_noise))
            candidate.append(0.95 * math.exp(shared_log_noise + orientation_effect + residual_log_noise))
            strata.append("AB" if pair_index % 2 == 0 else "BA")
        seed = generator.randrange(2**32)
        stratified = bootstrap_paired_median_ratio_interval(
            baseline,
            candidate,
            lower_is_better=True,
            confidence_level=0.95,
            resamples=800,
            random_seed=seed,
            strata=strata,
        )
        exchangeable = bootstrap_paired_median_ratio_interval(
            baseline,
            candidate,
            lower_is_better=True,
            confidence_level=0.95,
            resamples=800,
            random_seed=seed,
        )
        stratified_low, stratified_high = _bounds(stratified)
        exchangeable_low, exchangeable_high = _bounds(exchangeable)
        covered += stratified_low <= 5.0 <= stratified_high
        stratified_narrower += stratified_high - stratified_low < exchangeable_high - exchangeable_low

    # The fixed seed currently gives 28/30 for both checks. These deliberately
    # broad thresholds catch loss of design-preserving resampling; they do not
    # establish nominal finite-sample coverage for the median-ratio estimand.
    assert covered >= 24
    assert stratified_narrower >= 24


def test_bonferroni_intervals_control_null_family_errors_in_simulation() -> None:
    """Exercise family-wise rather than only per-cell null behavior."""
    generator = random.Random(4040)
    family_count = 30
    cells_per_family = 10
    false_direction_families = 0
    adjusted_confidence = 1.0 - (1.0 - 0.95) / cells_per_family

    for _ in range(family_count):
        family_has_false_direction = False
        for _ in range(cells_per_family):
            interval = _lognormal_interval(
                generator,
                sample_size=15,
                sigma=0.10,
                confidence_level=adjusted_confidence,
            )
            low, high = _bounds(interval)
            family_has_false_direction |= high < 0.0 or low > 0.0
        false_direction_families += family_has_false_direction

    # The fixed seed currently produces 2/30. This is a compact regression
    # check, not a claim that 30 simulated families can prove exact coverage.
    assert false_direction_families <= 3


@pytest.mark.parametrize(
    ("candidate_ratio", "expected", "minimum_count"),
    [
        (1.00, "unchanged", 36),
        (1.05, "inconclusive", 32),
        (1.10, "regressed", 36),
    ],
)
def test_equivalence_boundary_and_power_behave_as_expected(
    candidate_ratio: float,
    expected: _Decision,
    minimum_count: int,
) -> None:
    """Validate equivalence, boundary uncertainty, and useful power."""
    generator = random.Random(5000 + round(candidate_ratio * 100.0))
    counts: dict[_Decision, int] = {
        "regressed": 0,
        "unchanged": 0,
        "inconclusive": 0,
    }
    simulations = 40
    for _ in range(simulations):
        interval = _lognormal_interval(
            generator,
            sample_size=20,
            sigma=0.03,
            candidate_ratio=candidate_ratio,
        )
        decision = _classify(interval, threshold_percent=5.0)
        counts[decision] += 1

    assert counts[expected] >= minimum_count
