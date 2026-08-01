"""Versioned, loadable comparison report documents."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeAlias, cast

from ._schema import (
    COMPARISON_REPORT_KIND,
    COMPARISON_REPORT_SCHEMA_READ_VERSIONS,
    COMPARISON_REPORT_SCHEMA_VERSION,
    KNOWN_METRICS,
    PRODUCER,
    JsonValue,
    MetricName,
)
from .bench_collection import (
    BenchmarkCell,
    BenchmarkPairedRunGroup,
    BenchmarkPairedRunRecord,
    BenchmarkRunGroup,
    BenchmarkRunRecord,
    CollectionRunStatus,
    balanced_order_supercycle_length,
    make_paired_ab_ba_schedule,
)
from .bench_compare import (
    BenchmarkComparison,
    BenchmarkEvidence,
    BenchmarkInference,
    BenchmarkRunComparison,
    ComparisonDesign,
    ComparisonDirection,
    ComparisonStatus,
    CompatibilityMode,
    CompatibilitySeverity,
    EvidencePolicy,
    InferencePolicy,
    PrecisionPolicy,
    RegressionClassification,
    RegressionPolicy,
    RegressionThresholdScope,
    RunCompatibilityFinding,
    RunCompatibilityPolicy,
    RunCompatibilityReport,
)
from .bench_statistics import PrecisionPlan
from .exceptions import BenchmarkJsonError

PolicySelection: TypeAlias = Literal["defaults", "disabled", "discovered", "explicit"]
ThresholdOrigin: TypeAlias = Literal["built_in", "configuration", "cli"]

_ROOT_KEYS_V1 = frozenset(
    {
        "producer",
        "kind",
        "schema_version",
        "baseline",
        "candidate",
        "baselines",
        "candidates",
        "baseline_collections",
        "candidate_collections",
        "passed",
        "comparison_passed",
        "is_comparable",
        "has_regressions",
        "compatibility",
        "summary",
        "evidence_policy",
        "policy",
        "comparisons",
    }
)
_ROOT_KEYS_V2 = _ROOT_KEYS_V1 | {"inference_policy"}
_ROOT_KEYS_V3 = _ROOT_KEYS_V2 | {
    "design",
    "precision_policy",
    "paired_collections",
}
_COLLECTION_KEYS = frozenset(
    {
        "manifest",
        "created_at",
        "command",
        "cwd",
        "commit",
        "environment_fingerprint",
        "requested_runs",
        "attempted_runs",
        "successful_runs",
        "failed_runs",
        "complete",
        "expected_cells",
        "runs",
    }
)
_RECORD_KEYS = frozenset(
    {
        "index",
        "status",
        "path",
        "returncode",
        "started_at",
        "duration_seconds",
        "error",
        "warnings",
        "commit",
        "environment_fingerprint",
    }
)
_PAIRED_COLLECTION_KEYS = frozenset(
    {
        "manifest",
        "created_at",
        "baseline_command",
        "candidate_command",
        "baseline_cwd",
        "candidate_cwd",
        "baseline_commit",
        "candidate_commit",
        "baseline_environment_fingerprint",
        "candidate_environment_fingerprint",
        "requested_pairs",
        "random_seed",
        "automatic_pairs",
        "attempted_commands",
        "successful_commands",
        "failed_commands",
        "complete_pairs",
        "orphan_successes",
        "complete",
        "expected_cells",
        "runs",
    }
)
_PAIRED_RECORD_KEYS = frozenset(
    {
        "index",
        "pair_index",
        "block_attempt",
        "variant",
        "pair_order",
        "order_position",
        "cell_order_index",
        "status",
        "path",
        "returncode",
        "started_at",
        "duration_seconds",
        "error",
        "warnings",
        "commit",
        "environment_fingerprint",
    }
)
_CELL_KEYS = frozenset({"implementation_name", "case_name", "metric_name"})
_POLICY_KEYS = frozenset(
    {
        "selection",
        "configuration_file",
        "configured_fields",
        "cli_overrides",
        "regression",
    }
)
_REGRESSION_POLICY_KEYS = frozenset(
    {
        "default_threshold_percent",
        "by_metric",
        "by_implementation",
        "by_case",
        "by_cell",
    }
)
_POLICY_CELL_KEYS = frozenset({"implementation", "case", "metric", "threshold_percent"})
_COMPATIBILITY_KEYS = frozenset({"mode", "is_compatible", "pairs_checked", "findings"})
_FINDING_KEYS = frozenset(
    {
        "field",
        "severity",
        "reason",
        "baseline_value",
        "candidate_value",
        "baseline_run",
        "candidate_run",
    }
)
_EVIDENCE_POLICY_KEYS_V1 = frozenset(
    {
        "minimum_runs",
        "minimum_samples_per_run",
        "require_rounds",
        "require_iterations",
        "maximum_cv",
        "maximum_outlier_fraction",
    }
)
_EVIDENCE_POLICY_KEYS_V2 = _EVIDENCE_POLICY_KEYS_V1 | {
    "minimum_rounds_per_run",
    "require_raw_samples_for_inference",
    "minimum_tail_samples_per_run",
    "require_tail_iterations_one",
}
_INFERENCE_POLICY_KEYS = frozenset(
    {
        "method",
        "confidence_level",
        "resamples",
        "random_seed",
        "multiplicity",
    }
)
_PRECISION_POLICY_KEYS = frozenset({"target_half_width_percent"})
_COMPARISON_KEYS_V1 = frozenset(
    {
        "implementation_name",
        "case_name",
        "metric_name",
        "statistic",
        "direction",
        "status",
        "regression",
        "baseline_value",
        "candidate_value",
        "ratio",
        "percent_change",
        "improvement_percent",
        "improvement_low_percent",
        "improvement_high_percent",
        "threshold_percent",
        "threshold_source",
        "unit",
        "reason",
        "baseline_evidence",
        "candidate_evidence",
    }
)
_COMPARISON_KEYS_V2 = _COMPARISON_KEYS_V1 | {"inference"}
_COMPARISON_KEYS_V3 = _COMPARISON_KEYS_V2 | {"precision"}
_THRESHOLD_SOURCE_KEYS = frozenset({"scope", "origin", "field"})
_EVIDENCE_KEYS_V1 = frozenset(
    {
        "provided_run_count",
        "observed_run_count",
        "rounds",
        "iterations",
        "sample_counts",
        "sample_count",
        "iqr",
        "coefficient_of_variation",
        "outlier_count",
        "outlier_fraction",
        "adequate",
        "issues",
    }
)
_EVIDENCE_KEYS_V2 = _EVIDENCE_KEYS_V1 | {
    "run_iqrs",
    "run_coefficients_of_variation",
    "run_outlier_counts",
    "run_outlier_fractions",
}
_INFERENCE_KEYS_V2 = frozenset(
    {
        "method",
        "estimand",
        "design",
        "confidence_level",
        "adjusted_confidence_level",
        "multiplicity",
        "family_size",
        "resamples",
        "random_seed",
        "estimate_percent",
        "confidence_low_percent",
        "confidence_high_percent",
        "warnings",
        "issues",
        "adequate",
    }
)
_INFERENCE_KEYS_V3 = _INFERENCE_KEYS_V2 | {"pair_count", "strata_count"}
_PRECISION_PLAN_KEYS = frozenset(
    {
        "method",
        "pilot_pairs",
        "target_half_width_percent",
        "confidence_level",
        "adjusted_confidence_level",
        "multiplicity",
        "family_size",
        "pilot_log_ratio_standard_deviation",
        "critical_value",
        "minimum_pairs",
        "pair_count_multiple",
        "unconstrained_required_pairs",
        "required_pairs",
        "additional_pairs",
        "strata_count",
        "assumptions",
        "warnings",
        "issues",
        "adequate",
    }
)
_SUMMARY_KEYS = frozenset({"improved", "unchanged", "regressed", "inconclusive", "not_comparable"})


@dataclass(frozen=True, slots=True)
class BenchmarkPolicyProvenance:
    """Configuration provenance embedded in a comparison report."""

    selection: PolicySelection
    configuration_file: str | None = None
    configured_fields: tuple[str, ...] = ()
    cli_overrides: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and normalize policy provenance."""
        if self.selection not in {"defaults", "disabled", "discovered", "explicit"}:
            raise ValueError(f"Unsupported policy selection: {self.selection!r}.")
        if self.configuration_file is not None and (
            not isinstance(self.configuration_file, str) or not self.configuration_file
        ):
            raise ValueError("configuration_file must be a non-empty string or None.")
        configured_fields = tuple(self.configured_fields)
        cli_overrides = tuple(self.cli_overrides)
        if any(not isinstance(field, str) or not field for field in (*configured_fields, *cli_overrides)):
            raise ValueError("Policy provenance fields must be non-empty strings.")
        object.__setattr__(self, "configured_fields", configured_fields)
        object.__setattr__(self, "cli_overrides", cli_overrides)


@dataclass(frozen=True, slots=True)
class BenchmarkThresholdProvenance:
    """Rule scope and origin supplying one reported cell threshold."""

    scope: RegressionThresholdScope
    origin: ThresholdOrigin
    field: str

    def __post_init__(self) -> None:
        """Validate threshold provenance."""
        if self.scope not in {"cell", "case", "implementation", "metric", "default"}:
            raise ValueError(f"Unsupported threshold scope: {self.scope!r}.")
        if self.origin not in {"built_in", "configuration", "cli"}:
            raise ValueError(f"Unsupported threshold origin: {self.origin!r}.")
        if not isinstance(self.field, str) or not self.field:
            raise ValueError("Threshold provenance field must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class BenchmarkCollectionSnapshot:
    """Portable collection provenance embedded in a comparison report."""

    manifest: str
    created_at: str
    command: tuple[str, ...]
    cwd: str
    commit: str | None
    environment_fingerprint: str | None
    requested_runs: int
    expected_cells: tuple[BenchmarkCell, ...]
    records: tuple[BenchmarkRunRecord, ...]

    def __post_init__(self) -> None:
        """Validate and normalize the portable collection snapshot."""
        if not isinstance(self.manifest, str) or not self.manifest:
            raise ValueError("Collection manifest must be a non-empty string.")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("Collection created_at must be a non-empty string.")
        command = tuple(self.command)
        if not command or any(not isinstance(argument, str) or not argument for argument in command):
            raise ValueError("Collection command must contain non-empty strings.")
        if not isinstance(self.cwd, str) or not self.cwd:
            raise ValueError("Collection cwd must be a non-empty string.")
        if self.commit is not None and (not isinstance(self.commit, str) or not self.commit):
            raise ValueError("Collection commit must be a non-empty string or None.")
        if self.environment_fingerprint is not None and (
            not isinstance(self.environment_fingerprint, str) or not self.environment_fingerprint
        ):
            raise ValueError("Collection environment fingerprint must be a non-empty string or None.")
        if (
            isinstance(self.requested_runs, bool)
            or not isinstance(self.requested_runs, int)
            or self.requested_runs <= 0
        ):
            raise ValueError("Collection requested_runs must be a positive integer.")
        expected_cells = tuple(self.expected_cells)
        records = tuple(self.records)
        if tuple(record.index for record in records) != tuple(range(1, len(records) + 1)):
            raise ValueError("Collection record indexes must be contiguous and one-based.")
        successful_runs = sum(record.status == "succeeded" for record in records)
        if successful_runs > self.requested_runs:
            raise ValueError("Collection has more successful runs than requested.")
        if len(set(expected_cells)) != len(expected_cells):
            raise ValueError("Collection expected_cells must not contain duplicates.")
        for implementation, case, metric in expected_cells:
            if not implementation or not case or metric not in KNOWN_METRICS:
                raise ValueError(f"Invalid collection expected cell: {(implementation, case, metric)!r}.")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "expected_cells", expected_cells)
        object.__setattr__(self, "records", records)

    @classmethod
    def from_group(cls, group: BenchmarkRunGroup) -> BenchmarkCollectionSnapshot:
        """Create a portable snapshot from a loaded run group."""
        return cls(
            manifest=str(group.manifest_path),
            created_at=group.created_at,
            command=group.command,
            cwd=str(group.cwd),
            commit=group.commit,
            environment_fingerprint=group.environment_fingerprint,
            requested_runs=group.requested_runs,
            expected_cells=group.expected_cells,
            records=group.records,
        )

    @property
    def attempted_runs(self) -> int:
        """Return the number of completed collection attempts."""
        return len(self.records)

    @property
    def successful_runs(self) -> int:
        """Return the number of accepted collection attempts."""
        return sum(record.status == "succeeded" for record in self.records)

    @property
    def failed_runs(self) -> int:
        """Return the number of failed collection attempts."""
        return sum(record.status == "failed" for record in self.records)

    @property
    def pending_runs(self) -> int:
        """Return initial collection slots that were never attempted."""
        return max(0, self.requested_runs - self.attempted_runs)

    @property
    def retry_attempts(self) -> int:
        """Return attempts appended after the initial collection slots."""
        return max(0, self.attempted_runs - self.requested_runs)

    @property
    def remaining_runs(self) -> int:
        """Return additional successful runs needed for completeness."""
        return self.requested_runs - self.successful_runs

    @property
    def complete(self) -> bool:
        """Return whether the requested successful-run target was reached."""
        return self.successful_runs == self.requested_runs

    def to_dict(self) -> dict[str, JsonValue]:
        """Return the stable JSON representation of this collection."""
        return {
            "manifest": self.manifest,
            "created_at": self.created_at,
            "command": list(self.command),
            "cwd": self.cwd,
            "commit": self.commit,
            "environment_fingerprint": self.environment_fingerprint,
            "requested_runs": self.requested_runs,
            "attempted_runs": self.attempted_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "complete": self.complete,
            "expected_cells": [
                {
                    "implementation_name": implementation,
                    "case_name": case,
                    "metric_name": metric,
                }
                for implementation, case, metric in self.expected_cells
            ],
            "runs": [_record_dict(record) for record in self.records],
        }


@dataclass(frozen=True, slots=True)
class BenchmarkPairedCollectionSnapshot:
    """Portable paired AB/BA collection provenance embedded in a report."""

    manifest: str
    created_at: str
    baseline_command: tuple[str, ...]
    candidate_command: tuple[str, ...]
    baseline_cwd: str
    candidate_cwd: str
    baseline_commit: str | None
    candidate_commit: str | None
    baseline_environment_fingerprint: str | None
    candidate_environment_fingerprint: str | None
    requested_pairs: int
    random_seed: int
    expected_cells: tuple[BenchmarkCell, ...]
    records: tuple[BenchmarkPairedRunRecord, ...]
    automatic_pairs: bool = False

    def __post_init__(self) -> None:
        """Validate and normalize the portable paired snapshot."""
        if not isinstance(self.manifest, str) or not self.manifest:
            raise ValueError("Paired collection manifest must be a non-empty string.")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("Paired collection created_at must be a non-empty string.")
        baseline_command = tuple(self.baseline_command)
        candidate_command = tuple(self.candidate_command)
        for name, command in (
            ("baseline_command", baseline_command),
            ("candidate_command", candidate_command),
        ):
            if not command or any(not isinstance(argument, str) or not argument for argument in command):
                raise ValueError(f"Paired collection {name} must contain non-empty strings.")
        for name, cwd in (("baseline_cwd", self.baseline_cwd), ("candidate_cwd", self.candidate_cwd)):
            if not isinstance(cwd, str) or not cwd:
                raise ValueError(f"Paired collection {name} must be a non-empty string.")
        for name, value in (
            ("baseline_commit", self.baseline_commit),
            ("candidate_commit", self.candidate_commit),
            ("baseline_environment_fingerprint", self.baseline_environment_fingerprint),
            ("candidate_environment_fingerprint", self.candidate_environment_fingerprint),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"Paired collection {name} must be a non-empty string or None.")
        if (
            isinstance(self.requested_pairs, bool)
            or not isinstance(self.requested_pairs, int)
            or self.requested_pairs <= 0
        ):
            raise ValueError("Paired collection requested_pairs must be a positive integer.")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int) or self.random_seed < 0:
            raise ValueError("Paired collection random_seed must be a non-negative integer.")
        if not isinstance(self.automatic_pairs, bool):
            raise TypeError("Paired collection automatic_pairs must be a boolean.")

        expected_cells = tuple(self.expected_cells)
        records = tuple(self.records)
        if len(set(expected_cells)) != len(expected_cells):
            raise ValueError("Paired collection expected_cells must not contain duplicates.")
        for implementation, case, metric in expected_cells:
            if not implementation or not case or metric not in KNOWN_METRICS:
                raise ValueError(f"Invalid paired collection expected cell: {(implementation, case, metric)!r}.")
        if any(not isinstance(record, BenchmarkPairedRunRecord) for record in records):
            raise TypeError("Paired collection records must contain BenchmarkPairedRunRecord values.")
        if tuple(record.index for record in records) != tuple(range(1, len(records) + 1)):
            raise ValueError("Paired collection record indexes must be contiguous and one-based.")
        canonical_paths = tuple(record.path.resolve() for record in records)
        if len(set(canonical_paths)) != len(canonical_paths):
            raise ValueError("Paired collection record paths must be unique.")

        successful_records = tuple(record for record in records if record.status == "succeeded")
        if successful_records and not expected_cells:
            raise ValueError("Paired collection with successful records requires expected cells.")
        if expected_cells and not successful_records:
            raise ValueError("Paired collection without successful records cannot define expected cells.")
        if self.automatic_pairs:
            if expected_cells:
                supercycle = balanced_order_supercycle_length(len(expected_cells))
                minimum_pairs = EvidencePolicy().minimum_runs
                expected_pair_target = ((minimum_pairs + supercycle - 1) // supercycle) * supercycle
                if self.requested_pairs != expected_pair_target:
                    raise ValueError(
                        "Automatic paired collection target must be the smallest complete joint-design "
                        "supercycle at or above the evidence minimum."
                    )
            elif self.requested_pairs != 6:
                raise ValueError("Automatic paired collection without successful records must retain target 6.")

        schedule = {
            entry.pair_index: entry
            for entry in make_paired_ab_ba_schedule(
                self.requested_pairs,
                random_seed=self.random_seed,
                cell_count=(len(expected_cells) if expected_cells else None),
            )
        }
        block_variants: dict[tuple[int, int], set[str]] = {}
        attempts_by_pair: dict[int, set[int]] = {}
        latest_attempt_by_pair: dict[int, int] = {}
        first_seen_pairs: set[int] = set()
        matrix_anchor_seen = False
        for record in records:
            if record.pair_index > self.requested_pairs:
                raise ValueError("Paired collection record pair_index exceeds requested_pairs.")
            if record.pair_index not in first_seen_pairs:
                expected_pair_index = len(first_seen_pairs) + 1
                if record.pair_index != expected_pair_index:
                    raise ValueError("Paired collection target pairs must first appear as a one-based prefix.")
                first_seen_pairs.add(record.pair_index)
            if record.pair_index > 1 and not matrix_anchor_seen:
                raise ValueError("Paired collection cannot start later target pairs before a successful matrix exists.")
            expected = schedule[record.pair_index]
            if record.pair_order != expected.pair_order or record.cell_order_index != expected.cell_order_index:
                raise ValueError("Paired collection record differs from its deterministic schedule.")
            previous_attempt = latest_attempt_by_pair.get(record.pair_index, record.block_attempt)
            if record.block_attempt < previous_attempt:
                raise ValueError("Paired collection block attempts must be chronological per pair.")
            latest_attempt_by_pair[record.pair_index] = record.block_attempt
            key = (record.pair_index, record.block_attempt)
            variants = block_variants.setdefault(key, set())
            if record.variant in variants:
                raise ValueError("Paired collection block attempts cannot repeat a variant.")
            variants.add(record.variant)
            attempts_by_pair.setdefault(record.pair_index, set()).add(record.block_attempt)
            matrix_anchor_seen = matrix_anchor_seen or record.status == "succeeded"
        records_by_block: dict[tuple[int, int], list[BenchmarkPairedRunRecord]] = {}
        for record in records:
            records_by_block.setdefault((record.pair_index, record.block_attempt), []).append(record)
        for (pair_index, _block_attempt), block_records in records_by_block.items():
            scheduled_variants = schedule[pair_index].variants
            observed_variants = tuple(record.variant for record in block_records)
            if observed_variants != scheduled_variants[: len(observed_variants)]:
                raise ValueError("Paired collection block records are not in scheduled AB/BA order.")
            if len(block_records) == 2 and block_records[1].index != block_records[0].index + 1:
                raise ValueError("Paired collection block members must be adjacent records.")
            if len(block_records) == 1 and block_records[0].index < len(records):
                following = records[block_records[0].index]
                if following.pair_index != pair_index or following.block_attempt != block_records[0].block_attempt + 1:
                    raise ValueError("Paired collection a partial block must be followed by a retry of the same pair.")
        for pair_index, attempts in attempts_by_pair.items():
            if sorted(attempts) != list(range(1, max(attempts) + 1)):
                raise ValueError("Paired collection block attempts must be contiguous per pair.")
            complete_attempts = sum(
                {
                    record.variant
                    for record in records
                    if record.pair_index == pair_index
                    and record.block_attempt == block_attempt
                    and record.status == "succeeded"
                }
                == {"baseline", "candidate"}
                for block_attempt in attempts
            )
            if complete_attempts > 1:
                raise ValueError("Paired collection cannot contain two complete blocks for one pair.")
            complete_attempt = next(
                (
                    block_attempt
                    for block_attempt in attempts
                    if {
                        record.variant
                        for record in records
                        if record.pair_index == pair_index
                        and record.block_attempt == block_attempt
                        and record.status == "succeeded"
                    }
                    == {"baseline", "candidate"}
                ),
                None,
            )
            if complete_attempt is not None and any(attempt > complete_attempt for attempt in attempts):
                raise ValueError("Paired collection cannot retry a pair after a complete block.")

        for variant, commit, fingerprint in (
            (
                "baseline",
                self.baseline_commit,
                self.baseline_environment_fingerprint,
            ),
            (
                "candidate",
                self.candidate_commit,
                self.candidate_environment_fingerprint,
            ),
        ):
            variant_records = tuple(record for record in successful_records if record.variant == variant)
            if not variant_records:
                if commit is not None or fingerprint is not None:
                    raise ValueError(f"Paired collection {variant} anchors require a successful record.")
                continue
            if variant_records[0].environment_fingerprint != fingerprint:
                raise ValueError(f"First successful {variant} fingerprint does not match the collection anchor.")
            if any(record.commit != commit for record in variant_records):
                raise ValueError(f"Successful {variant} commits do not match the collection anchor.")

        object.__setattr__(self, "baseline_command", baseline_command)
        object.__setattr__(self, "candidate_command", candidate_command)
        object.__setattr__(self, "expected_cells", expected_cells)
        object.__setattr__(self, "records", records)

    @classmethod
    def from_group(cls, group: BenchmarkPairedRunGroup) -> BenchmarkPairedCollectionSnapshot:
        """Create a portable snapshot from a loaded paired run group."""
        return cls(
            manifest=str(group.manifest_path),
            created_at=group.created_at,
            baseline_command=group.baseline_command,
            candidate_command=group.candidate_command,
            baseline_cwd=str(group.baseline_cwd),
            candidate_cwd=str(group.candidate_cwd),
            baseline_commit=group.baseline_commit,
            candidate_commit=group.candidate_commit,
            baseline_environment_fingerprint=group.baseline_environment_fingerprint,
            candidate_environment_fingerprint=group.candidate_environment_fingerprint,
            requested_pairs=group.requested_pairs,
            random_seed=group.random_seed,
            expected_cells=group.expected_cells,
            records=group.records,
            automatic_pairs=group.automatic_pairs,
        )

    @property
    def attempted_commands(self) -> int:
        """Return the number of completed command attempts."""
        return len(self.records)

    @property
    def successful_commands(self) -> int:
        """Return the number of accepted command attempts."""
        return sum(record.status == "succeeded" for record in self.records)

    @property
    def failed_commands(self) -> int:
        """Return the number of failed command attempts."""
        return sum(record.status == "failed" for record in self.records)

    @property
    def complete_pair_count(self) -> int:
        """Return the number of target pairs with one complete atomic block."""
        return len(self.complete_pair_records)

    @property
    def complete_pair_records(
        self,
    ) -> tuple[tuple[BenchmarkPairedRunRecord, BenchmarkPairedRunRecord], ...]:
        """Return baseline/candidate records for complete blocks in pair order."""
        successful = {
            (record.pair_index, record.block_attempt, record.variant): record
            for record in self.records
            if record.status == "succeeded"
        }
        pairs: list[tuple[BenchmarkPairedRunRecord, BenchmarkPairedRunRecord]] = []
        for pair_index in range(1, self.requested_pairs + 1):
            attempts = sorted(
                block_attempt
                for pair, block_attempt, variant in successful
                if pair == pair_index and variant == "baseline"
            )
            for block_attempt in attempts:
                baseline = successful.get((pair_index, block_attempt, "baseline"))
                candidate = successful.get((pair_index, block_attempt, "candidate"))
                if baseline is not None and candidate is not None:
                    pairs.append((baseline, candidate))
                    break
        return tuple(pairs)

    @property
    def baseline_sources(self) -> tuple[str, ...]:
        """Return complete-block baseline paths in target-pair order."""
        return tuple(str(baseline.path) for baseline, _candidate in self.complete_pair_records)

    @property
    def candidate_sources(self) -> tuple[str, ...]:
        """Return complete-block candidate paths in target-pair order."""
        return tuple(str(candidate.path) for _baseline, candidate in self.complete_pair_records)

    @property
    def orphan_success_count(self) -> int:
        """Return successful commands excluded from complete pairs."""
        return self.successful_commands - 2 * self.complete_pair_count

    @property
    def complete(self) -> bool:
        """Return whether every requested pair has a complete block."""
        return self.complete_pair_count == self.requested_pairs

    def to_dict(self) -> dict[str, JsonValue]:
        """Return the stable JSON representation of this paired collection."""
        return {
            "manifest": self.manifest,
            "created_at": self.created_at,
            "baseline_command": list(self.baseline_command),
            "candidate_command": list(self.candidate_command),
            "baseline_cwd": self.baseline_cwd,
            "candidate_cwd": self.candidate_cwd,
            "baseline_commit": self.baseline_commit,
            "candidate_commit": self.candidate_commit,
            "baseline_environment_fingerprint": self.baseline_environment_fingerprint,
            "candidate_environment_fingerprint": self.candidate_environment_fingerprint,
            "requested_pairs": self.requested_pairs,
            "random_seed": self.random_seed,
            "automatic_pairs": self.automatic_pairs,
            "attempted_commands": self.attempted_commands,
            "successful_commands": self.successful_commands,
            "failed_commands": self.failed_commands,
            "complete_pairs": self.complete_pair_count,
            "orphan_successes": self.orphan_success_count,
            "complete": self.complete,
            "expected_cells": [
                {
                    "implementation_name": implementation,
                    "case_name": case,
                    "metric_name": metric,
                }
                for implementation, case, metric in self.expected_cells
            ],
            "runs": [_paired_record_dict(record) for record in self.records],
        }


@dataclass(frozen=True, slots=True)
class BenchmarkComparisonReport:
    """One portable, versioned benchmark comparison result."""

    baselines: tuple[str, ...]
    candidates: tuple[str, ...]
    baseline_collections: tuple[BenchmarkCollectionSnapshot, ...]
    candidate_collections: tuple[BenchmarkCollectionSnapshot, ...]
    compatibility: RunCompatibilityReport
    evidence_policy: EvidencePolicy
    regression_policy: RegressionPolicy
    policy_provenance: BenchmarkPolicyProvenance
    comparisons: tuple[BenchmarkComparison, ...]
    threshold_provenance: tuple[BenchmarkThresholdProvenance, ...]
    inference_policy: InferencePolicy = field(
        default_factory=lambda: InferencePolicy(method="legacy_consistency", multiplicity="none")
    )
    design: ComparisonDesign = "independent"
    precision_policy: PrecisionPolicy = field(default_factory=PrecisionPolicy)
    paired_collections: tuple[BenchmarkPairedCollectionSnapshot, ...] = ()

    def __post_init__(self) -> None:
        """Validate and normalize report containers."""
        baselines = tuple(self.baselines)
        candidates = tuple(self.candidates)
        baseline_collections = tuple(self.baseline_collections)
        candidate_collections = tuple(self.candidate_collections)
        paired_collections = tuple(self.paired_collections)
        comparisons = tuple(self.comparisons)
        threshold_provenance = tuple(self.threshold_provenance)
        if not baselines or any(not isinstance(source, str) or not source for source in baselines):
            raise ValueError("Report baselines must contain non-empty source strings.")
        if not candidates or any(not isinstance(source, str) or not source for source in candidates):
            raise ValueError("Report candidates must contain non-empty source strings.")
        if len(comparisons) != len(threshold_provenance):
            raise ValueError("Every reported comparison requires threshold provenance.")
        if any(
            not isinstance(item, BenchmarkCollectionSnapshot)
            for item in (*baseline_collections, *candidate_collections)
        ):
            raise TypeError("Report collections must contain BenchmarkCollectionSnapshot values.")
        if any(not isinstance(item, BenchmarkPairedCollectionSnapshot) for item in paired_collections):
            raise TypeError("Report paired_collections must contain BenchmarkPairedCollectionSnapshot values.")
        if any(not isinstance(item, BenchmarkComparison) for item in comparisons):
            raise TypeError("Report comparisons must contain BenchmarkComparison values.")
        if any(not isinstance(item, BenchmarkThresholdProvenance) for item in threshold_provenance):
            raise TypeError("Report threshold_provenance must contain BenchmarkThresholdProvenance values.")
        if not isinstance(self.compatibility, RunCompatibilityReport):
            raise TypeError("Report compatibility must be a RunCompatibilityReport.")
        if not isinstance(self.evidence_policy, EvidencePolicy):
            raise TypeError("Report evidence_policy must be an EvidencePolicy.")
        if not isinstance(self.regression_policy, RegressionPolicy):
            raise TypeError("Report regression_policy must be a RegressionPolicy.")
        if not isinstance(self.inference_policy, InferencePolicy):
            raise TypeError("Report inference_policy must be an InferencePolicy.")
        if self.design not in {"independent", "paired"}:
            raise ValueError(f"Unsupported report comparison design: {self.design!r}.")
        if not isinstance(self.precision_policy, PrecisionPolicy):
            raise TypeError("Report precision_policy must be a PrecisionPolicy.")
        if not isinstance(self.policy_provenance, BenchmarkPolicyProvenance):
            raise TypeError("Report policy_provenance must be BenchmarkPolicyProvenance.")
        paired_strata_count: int | None = None
        paired_supercycle_multiple: int | None = None
        if self.design == "independent":
            if self.precision_policy.enabled:
                raise ValueError("Independent reports cannot enable paired precision planning.")
            if paired_collections:
                raise ValueError("Independent reports cannot include paired collection provenance.")
        else:
            if baseline_collections or candidate_collections:
                raise ValueError("Paired reports cannot include independent collection provenance.")
            if len(baselines) != len(candidates):
                raise ValueError("Paired reports require equal baseline and candidate source counts.")
            evidence_paths = tuple(Path(source).resolve() for source in (*baselines, *candidates))
            if len(set(evidence_paths)) != len(evidence_paths):
                raise ValueError("Paired report complete-pair sources cannot reuse a file as independent evidence.")
            if paired_collections:
                supercycle_multiples = {
                    balanced_order_supercycle_length(len(collection.expected_cells))
                    for collection in paired_collections
                }
                if len(supercycle_multiples) != 1:
                    raise ValueError("Paired collection provenance has conflicting joint-design supercycles.")
                paired_supercycle_multiple = next(iter(supercycle_multiples))
                paired_strata_count = len(
                    {
                        baseline.pair_order
                        for collection in paired_collections
                        for baseline, _candidate in collection.complete_pair_records
                    }
                )
                expected_baselines = tuple(
                    source for collection in paired_collections for source in collection.baseline_sources
                )
                expected_candidates = tuple(
                    source for collection in paired_collections for source in collection.candidate_sources
                )
                if baselines != expected_baselines or candidates != expected_candidates:
                    raise ValueError("Paired report sources must match complete same-block record paths in pair order.")
        object.__setattr__(self, "baselines", baselines)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "baseline_collections", baseline_collections)
        object.__setattr__(self, "candidate_collections", candidate_collections)
        object.__setattr__(self, "paired_collections", paired_collections)
        object.__setattr__(self, "comparisons", comparisons)
        object.__setattr__(self, "threshold_provenance", threshold_provenance)
        for cell, threshold in zip(comparisons, threshold_provenance, strict=True):
            _validate_threshold_provenance(
                cell,
                threshold,
                regression_policy=self.regression_policy,
                policy_provenance=self.policy_provenance,
            )
            _validate_cell_inference(
                cell,
                inference_policy=self.inference_policy,
                environment_compatible=self.compatibility.is_compatible,
                design=self.design,
                expected_pair_count=(len(baselines) if self.design == "paired" else None),
                expected_strata_count=paired_strata_count,
            )
            _validate_cell_precision(
                cell,
                precision_policy=self.precision_policy,
                inference_policy=self.inference_policy,
                evidence_policy=self.evidence_policy,
                design=self.design,
                expected_pair_count=(len(baselines) if self.design == "paired" else None),
                expected_strata_count=paired_strata_count,
                expected_pair_count_multiple=paired_supercycle_multiple,
            )
        inferences = tuple(cell.inference for cell in comparisons if cell.inference is not None)
        if inferences:
            family_sizes = {inference.family_size for inference in inferences}
            if len(family_sizes) != 1 or next(iter(family_sizes)) != len(inferences):
                raise ValueError("Reported inference family size is inconsistent with inferred cells.")
        plans = tuple(cell.precision for cell in comparisons if cell.precision is not None)
        if plans:
            family_sizes = {plan.family_size for plan in plans}
            if len(family_sizes) != 1:
                raise ValueError("Reported precision-plan family sizes are inconsistent across cells.")
            if self.compatibility.is_compatible and next(iter(family_sizes)) != len(plans):
                raise ValueError("Reported precision-plan family size is inconsistent with planned cells.")

    @classmethod
    def from_comparison(
        cls,
        comparison: BenchmarkRunComparison,
        *,
        baselines: Sequence[str | Path],
        candidates: Sequence[str | Path],
        policy_provenance: BenchmarkPolicyProvenance,
        threshold_provenance: Sequence[BenchmarkThresholdProvenance],
        baseline_collections: Sequence[BenchmarkRunGroup] = (),
        candidate_collections: Sequence[BenchmarkRunGroup] = (),
        paired_collections: Sequence[BenchmarkPairedRunGroup] = (),
    ) -> BenchmarkComparisonReport:
        """Create a portable report from a live comparison result."""
        return cls(
            baselines=tuple(str(source) for source in baselines),
            candidates=tuple(str(source) for source in candidates),
            baseline_collections=tuple(BenchmarkCollectionSnapshot.from_group(group) for group in baseline_collections),
            candidate_collections=tuple(
                BenchmarkCollectionSnapshot.from_group(group) for group in candidate_collections
            ),
            paired_collections=tuple(
                BenchmarkPairedCollectionSnapshot.from_group(group) for group in paired_collections
            ),
            compatibility=comparison.compatibility,
            evidence_policy=comparison.evidence_policy,
            regression_policy=comparison.regression_policy,
            policy_provenance=policy_provenance,
            comparisons=comparison.comparisons,
            threshold_provenance=tuple(threshold_provenance),
            inference_policy=comparison.inference_policy,
            design=comparison.design,
            precision_policy=comparison.precision_policy,
        )

    @property
    def producer(self) -> str:
        """Return the comparison report producer identifier."""
        return PRODUCER

    @property
    def kind(self) -> str:
        """Return the comparison report document kind."""
        return COMPARISON_REPORT_KIND

    @property
    def schema_version(self) -> int:
        """Return the comparison report schema version."""
        return COMPARISON_REPORT_SCHEMA_VERSION

    @property
    def baseline(self) -> str:
        """Return the primary baseline source."""
        return self.baselines[0]

    @property
    def candidate(self) -> str:
        """Return the primary candidate source."""
        return self.candidates[0]

    @property
    def improved(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells classified as improvements."""
        return tuple(cell for cell in self.comparisons if cell.regression == "improved")

    @property
    def unchanged(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells classified as unchanged."""
        return tuple(cell for cell in self.comparisons if cell.regression == "unchanged")

    @property
    def regressed(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells classified as regressions."""
        return tuple(cell for cell in self.comparisons if cell.regression == "regressed")

    @property
    def inconclusive(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells with inconclusive evidence."""
        return tuple(cell for cell in self.comparisons if cell.regression == "inconclusive")

    @property
    def not_comparable(self) -> tuple[BenchmarkComparison, ...]:
        """Return cells without a trustworthy comparison."""
        return tuple(cell for cell in self.comparisons if cell.regression == "not_comparable")

    @property
    def comparison_passed(self) -> bool:
        """Return whether the benchmark comparison itself passed."""
        complete = all(cell.status == "matched" for cell in self.comparisons)
        comparable = self.compatibility.is_compatible and complete and not self.not_comparable
        return comparable and not self.regressed and not self.inconclusive

    @property
    def passed(self) -> bool:
        """Return whether comparison and collection lifecycle gates passed."""
        collections = (*self.baseline_collections, *self.candidate_collections, *self.paired_collections)
        return self.comparison_passed and all(collection.complete for collection in collections)

    @property
    def is_comparable(self) -> bool:
        """Return whether all report cells and environments are comparable."""
        complete = all(cell.status == "matched" for cell in self.comparisons)
        return self.compatibility.is_compatible and complete and not self.not_comparable

    @property
    def has_regressions(self) -> bool:
        """Return whether any matrix cell regressed."""
        return bool(self.regressed)

    def to_dict(self) -> dict[str, JsonValue]:
        """Return the complete stable comparison report document."""
        return {
            "producer": self.producer,
            "kind": self.kind,
            "schema_version": self.schema_version,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "baselines": list(self.baselines),
            "candidates": list(self.candidates),
            "baseline_collections": [collection.to_dict() for collection in self.baseline_collections],
            "candidate_collections": [collection.to_dict() for collection in self.candidate_collections],
            "paired_collections": [collection.to_dict() for collection in self.paired_collections],
            "design": self.design,
            "passed": self.passed,
            "comparison_passed": self.comparison_passed,
            "is_comparable": self.is_comparable,
            "has_regressions": self.has_regressions,
            "compatibility": _compatibility_dict(self.compatibility),
            "summary": {
                "improved": len(self.improved),
                "unchanged": len(self.unchanged),
                "regressed": len(self.regressed),
                "inconclusive": len(self.inconclusive),
                "not_comparable": len(self.not_comparable),
            },
            "evidence_policy": _evidence_policy_dict(self.evidence_policy),
            "inference_policy": _inference_policy_dict(self.inference_policy),
            "precision_policy": _precision_policy_dict(self.precision_policy),
            "policy": _policy_dict(self.policy_provenance, self.regression_policy),
            "comparisons": [
                _comparison_dict(cell, threshold)
                for cell, threshold in zip(
                    self.comparisons,
                    self.threshold_provenance,
                    strict=True,
                )
            ],
        }


def load_comparison_report(path: str | Path) -> BenchmarkComparisonReport:
    """Load and strictly validate a versioned comparison report.

    Args:
        path: JSON report written by ``benchmatrix compare --format json`` or
            :func:`write_comparison_report`.

    Returns:
        A portable typed comparison report.

    Raises:
        BenchmarkJsonError: If the file is unreadable, malformed, unsupported,
            or inconsistent with the report schema.
    """
    source = Path(path)
    try:
        payload = cast(object, json.loads(source.read_text(encoding="utf-8")))
    except OSError as exc:
        raise BenchmarkJsonError(f"Could not read benchmark comparison report: {source}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkJsonError(f"Invalid JSON in benchmark comparison report: {source}") from exc
    return _parse_report(payload)


def write_comparison_report(report: BenchmarkComparisonReport, path: str | Path) -> None:
    """Write a comparison report as deterministic strict JSON.

    Args:
        report: Portable report to serialize.
        path: Destination JSON path.

    Raises:
        TypeError: If ``report`` is not a ``BenchmarkComparisonReport``.
        OSError: If the destination cannot be written.
    """
    if not isinstance(report, BenchmarkComparisonReport):
        raise TypeError("report must be a BenchmarkComparisonReport.")
    destination = Path(path)
    destination.write_text(
        json.dumps(report.to_dict(), allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def format_comparison_report_markdown(report: BenchmarkComparisonReport) -> str:
    """Render a comparison report as deterministic GitHub-flavored Markdown.

    Args:
        report: Portable comparison report to render.

    Returns:
        A complete Markdown document ending with a newline.

    Raises:
        TypeError: If ``report`` is not a ``BenchmarkComparisonReport``.
    """
    if not isinstance(report, BenchmarkComparisonReport):
        raise TypeError("report must be a BenchmarkComparisonReport.")

    overall = "PASS" if report.passed else "FAIL"
    comparison = "PASS" if report.comparison_passed else "FAIL"
    compatibility = "compatible" if report.compatibility.is_compatible else "blocked"
    lines = [
        "# Benchmark comparison",
        "",
        f"**Overall:** {overall}  ",
        f"**Comparison decision:** {comparison}  ",
        f"**Environment compatibility:** {compatibility}  ",
        f"**Comparison design:** `{report.design}`  ",
        f"**Report schema:** `{report.kind}` version {report.schema_version}",
        "",
        "## Inputs",
        "",
        "| Side | Sources | Collections |",
        "| --- | --- | ---: |",
        (f"| Baseline | {_markdown_sources(report.baselines)} | " + f"{len(report.baseline_collections)} |"),
        (f"| Candidate | {_markdown_sources(report.candidates)} | " + f"{len(report.candidate_collections)} |"),
        "",
    ]
    collections = (*report.baseline_collections, *report.candidate_collections)
    if collections:
        lines.extend(
            [
                "### Collection lifecycle",
                "",
                "| Manifest | Target | Attempts | Successful | Failed | Retries | Complete |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for collection in collections:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown_text(collection.manifest),
                        str(collection.requested_runs),
                        str(collection.attempted_runs),
                        str(collection.successful_runs),
                        str(collection.failed_runs),
                        str(collection.retry_attempts),
                        "yes" if collection.complete else "no",
                    )
                )
                + " |"
            )
        lines.append("")
    if report.paired_collections:
        lines.extend(
            [
                "### Paired AB/BA collection lifecycle",
                "",
                (
                    "| Manifest | Pair target | Command attempts | Complete pairs | "
                    + "Failed commands | Orphan successes | Complete |"
                ),
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for collection in report.paired_collections:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown_text(collection.manifest),
                        str(collection.requested_pairs),
                        str(collection.attempted_commands),
                        str(collection.complete_pair_count),
                        str(collection.failed_commands),
                        str(collection.orphan_success_count),
                        "yes" if collection.complete else "no",
                    )
                )
                + " |"
            )
        lines.append("")

    lines.extend(
        [
            "## Summary",
            "",
            "| Improved | Unchanged | Regressed | Inconclusive | Not comparable |",
            "| ---: | ---: | ---: | ---: | ---: |",
            (
                f"| {len(report.improved)} | {len(report.unchanged)} | "
                + f"{len(report.regressed)} | {len(report.inconclusive)} | "
                + f"{len(report.not_comparable)} |"
            ),
            "",
            "## Matrix results",
            "",
            (
                "| Implementation | Case | Metric | Result | Baseline | Candidate | "
                + "Improvement | Confidence interval | Observed pairwise range | Threshold | Evidence |"
            ),
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for cell, threshold in zip(
        report.comparisons,
        report.threshold_provenance,
        strict=True,
    ):
        result = cell.regression if cell.status == "matched" else cell.status
        effect_range = _markdown_effect_range(
            cell.improvement_low_percent,
            cell.improvement_high_percent,
        )
        confidence_interval = _markdown_confidence_interval(cell.inference)
        evidence = _markdown_evidence_state(
            cell.baseline_evidence,
            cell.candidate_evidence,
        )
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_text(cell.implementation_name),
                    _markdown_text(cell.case_name),
                    _markdown_text(cell.metric_name),
                    _markdown_text(result),
                    _markdown_number(cell.baseline_value),
                    _markdown_number(cell.candidate_value),
                    _markdown_percent(cell.improvement_percent),
                    confidence_interval,
                    effect_range,
                    (
                        f"{cell.threshold_percent:.2f}% "
                        + f"({_markdown_text(threshold.scope)}/{_markdown_text(threshold.origin)})"
                    ),
                    evidence,
                )
            )
            + " |"
        )
    lines.append("")

    lines.extend(
        [
            "## Environment compatibility",
            "",
            (
                f"{report.compatibility.pairs_checked} environment pair(s) checked; "
                + f"{len(report.compatibility.blocking)} blocking finding(s); "
                + f"{len(report.compatibility.warnings)} warning(s)."
            ),
            "",
        ]
    )
    if report.compatibility.findings:
        lines.extend(
            [
                "| Severity | Field | Baseline | Candidate | Reason |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for finding in report.compatibility.findings:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown_text(finding.severity),
                        _markdown_text(finding.field),
                        _markdown_text(_compact_json(finding.baseline_value)),
                        _markdown_text(_compact_json(finding.candidate_value)),
                        _markdown_text(finding.reason),
                    )
                )
                + " |"
            )
        lines.append("")
    else:
        lines.extend(["No environment differences were reported.", ""])

    lines.extend(
        [
            "## Evidence and diagnostics",
            "",
        ]
    )
    for cell in report.comparisons:
        lines.extend(
            [
                (
                    "### "
                    + " / ".join(
                        (
                            _markdown_text(cell.implementation_name),
                            _markdown_text(cell.case_name),
                            _markdown_text(cell.metric_name),
                        )
                    )
                ),
                "",
                f"- Baseline: {_markdown_evidence_detail(cell.baseline_evidence)}",
                f"- Candidate: {_markdown_evidence_detail(cell.candidate_evidence)}",
                f"- Inference: {_markdown_inference_detail(cell.inference)}",
                f"- Precision planning: {_markdown_precision_detail(cell.precision)}",
            ]
        )
        if cell.reason is not None:
            lines.append(f"- Diagnostic: {_markdown_text(cell.reason)}")
        lines.append("")

    policy = report.regression_policy
    provenance = report.policy_provenance
    lines.extend(
        [
            "## Effective policy",
            "",
            f"- Selection: `{provenance.selection}`",
            (
                "- Configuration: "
                + (
                    _markdown_text(provenance.configuration_file)
                    if provenance.configuration_file is not None
                    else "built-in defaults"
                )
            ),
            (
                "- Configured fields: "
                + (
                    ", ".join(f"`{_markdown_code(field)}`" for field in provenance.configured_fields)
                    if provenance.configured_fields
                    else "none"
                )
            ),
            (
                "- CLI overrides: "
                + (
                    ", ".join(f"`{_markdown_code(field)}`" for field in provenance.cli_overrides)
                    if provenance.cli_overrides
                    else "none"
                )
            ),
            f"- Compatibility mode: `{report.compatibility.policy.mode}`",
            f"- Minimum runs: {report.evidence_policy.minimum_runs}",
            f"- Minimum samples per run: {report.evidence_policy.minimum_samples_per_run}",
            f"- Minimum rounds per run: {report.evidence_policy.minimum_rounds_per_run}",
            (
                "- Require raw samples for inference: "
                + ("yes" if report.evidence_policy.require_raw_samples_for_inference else "no")
            ),
            f"- Minimum tail samples per run: {report.evidence_policy.minimum_tail_samples_per_run}",
            (
                "- Require one iteration for tail latency: "
                + ("yes" if report.evidence_policy.require_tail_iterations_one else "no")
            ),
            f"- Inference method: `{report.inference_policy.method}`",
            f"- Confidence level: {report.inference_policy.confidence_level * 100.0:.2f}%",
            f"- Bootstrap resamples: {report.inference_policy.resamples}",
            f"- Random seed: {report.inference_policy.random_seed}",
            f"- Multiplicity correction: `{report.inference_policy.multiplicity}`",
            (
                "- Precision target: disabled"
                if report.precision_policy.target_half_width_percent is None
                else f"- Precision target half-width: {report.precision_policy.target_half_width_percent:.2f}%"
            ),
            f"- Default regression threshold: {policy.default_threshold_percent:.2f}%",
            (
                "- Selector thresholds: "
                + f"{len(policy.by_metric)} metric, "
                + f"{len(policy.by_implementation)} implementation, "
                + f"{len(policy.by_case)} case, {len(policy.by_cell)} exact cell"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_comparison_report_markdown(
    report: BenchmarkComparisonReport,
    path: str | Path,
) -> None:
    """Write a comparison report as deterministic Markdown.

    Args:
        report: Portable report to render.
        path: Destination Markdown path.

    Raises:
        TypeError: If ``report`` is not a ``BenchmarkComparisonReport``.
        OSError: If the destination cannot be written.
    """
    Path(path).write_text(format_comparison_report_markdown(report), encoding="utf-8")


def _markdown_sources(sources: Sequence[str]) -> str:
    """Return escaped source names for a Markdown table cell."""
    return "<br>".join(_markdown_text(source) for source in sources)


def _markdown_text(value: str) -> str:
    """Escape text embedded in a Markdown table or paragraph."""
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _markdown_code(value: str) -> str:
    """Escape text embedded in an inline code span."""
    return value.replace("`", "\\`")


def _markdown_number(value: float | None) -> str:
    """Format an optional comparison value."""
    return "-" if value is None else f"{value:.6g}"


def _markdown_percent(value: float | None) -> str:
    """Format an optional signed percentage."""
    return "-" if value is None else f"{value:+.2f}%"


def _markdown_effect_range(low: float | None, high: float | None) -> str:
    """Format the descriptive observed pairwise-effect range."""
    if low is None or high is None:
        return "-"
    return f"{low:+.2f}% to {high:+.2f}%"


def _markdown_confidence_interval(inference: BenchmarkInference | None) -> str:
    """Format one formal confidence interval."""
    if inference is None or inference.confidence_low_percent is None or inference.confidence_high_percent is None:
        return "-"
    return f"{inference.confidence_low_percent:+.2f}% to " + f"{inference.confidence_high_percent:+.2f}%"


def _markdown_evidence_state(
    baseline: BenchmarkEvidence | None,
    candidate: BenchmarkEvidence | None,
) -> str:
    """Return a compact two-sided evidence state."""
    if baseline is None or candidate is None:
        return "unavailable"
    return "adequate" if baseline.adequate and candidate.adequate else "inadequate"


def _markdown_evidence_detail(evidence: BenchmarkEvidence | None) -> str:
    """Return one side's complete compact evidence diagnostics."""
    if evidence is None:
        return "not available"
    rounds = ",".join("-" if value is None else str(value) for value in evidence.rounds)
    iterations = ",".join("-" if value is None else str(value) for value in evidence.iterations)
    sample_counts = ",".join(str(value) for value in evidence.sample_counts)
    issues = "; ".join(_markdown_text(issue) for issue in evidence.issues) or "none"
    return (
        f"{'adequate' if evidence.adequate else 'inadequate'}; "
        + f"runs {evidence.observed_run_count}/{evidence.provided_run_count}; "
        + f"rounds [{rounds}]; iterations [{iterations}]; "
        + f"round-duration observation counts [{sample_counts}]; "
        + f"total observations {evidence.sample_count}; "
        + f"pooled IQR {_markdown_number(evidence.iqr)}; "
        + f"pooled CV {_markdown_fraction(evidence.coefficient_of_variation)}; "
        + f"pooled outliers {evidence.outlier_count if evidence.outlier_count is not None else '-'}; "
        + f"issues {issues}"
    )


def _markdown_inference_detail(inference: BenchmarkInference | None) -> str:
    """Return one cell's complete compact inference diagnostics."""
    if inference is None:
        return "not available (legacy or non-comparable result)"
    warnings = "; ".join(_markdown_text(item) for item in inference.warnings) or "none"
    issues = "; ".join(_markdown_text(item) for item in inference.issues) or "none"
    interval = _markdown_confidence_interval(inference)
    pair_count = "" if inference.pair_count is None else f"; complete pairs {inference.pair_count}"
    strata_count = "" if inference.strata_count is None else f"; AB/BA strata {inference.strata_count}"
    return (
        f"{'adequate' if inference.adequate else 'inadequate'}; "
        + f"{inference.method}; {inference.estimand}; design {inference.design}; "
        + f"interval {interval}; nominal confidence {inference.confidence_level * 100.0:.2f}%; "
        + f"adjusted confidence {inference.adjusted_confidence_level * 100.0:.2f}%; "
        + f"multiplicity {inference.multiplicity} across {inference.family_size} cell(s); "
        + f"resamples {inference.resamples}; seed {inference.random_seed}{pair_count}{strata_count}; "
        + f"warnings {warnings}; issues {issues}"
    )


def _markdown_precision_detail(plan: PrecisionPlan | None) -> str:
    """Return one cell's fixed-design precision-planning summary."""
    if plan is None:
        return "disabled or unavailable"
    warnings = "; ".join(_markdown_text(item) for item in plan.warnings) or "none"
    issues = "; ".join(_markdown_text(item) for item in plan.issues) or "none"
    required = "-" if plan.required_pairs is None else str(plan.required_pairs)
    unconstrained = "-" if plan.unconstrained_required_pairs is None else str(plan.unconstrained_required_pairs)
    additional = "-" if plan.additional_pairs is None else str(plan.additional_pairs)
    return (
        f"{'adequate' if plan.adequate else 'unavailable'}; {plan.method}; "
        + f"pilot pairs {plan.pilot_pairs}; target half-width {plan.target_half_width_percent:.2f}%; "
        + f"unconstrained pairs {unconstrained}; minimum {plan.minimum_pairs}; "
        + f"pair-count multiple {plan.pair_count_multiple}; AB/BA strata {plan.strata_count}; "
        + f"fresh fixed-design pairs {required}; descriptive difference from pilot {additional}; "
        + f"adjusted confidence {plan.adjusted_confidence_level * 100.0:.2f}%; "
        + f"warnings {warnings}; issues {issues}"
    )


def _markdown_fraction(value: float | None) -> str:
    """Format an optional fraction as a percentage."""
    return "-" if value is None else f"{value * 100.0:.2f}%"


def _compact_json(value: object) -> str:
    """Return one compatibility value as compact deterministic JSON."""
    return json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _parse_report(value: object) -> BenchmarkComparisonReport:
    """Parse one in-memory report document."""
    root = _mapping(value, path="report")
    if _string(root.get("producer"), path="report.producer") != PRODUCER:
        raise BenchmarkJsonError("Unsupported benchmark comparison report producer.")
    if _string(root.get("kind"), path="report.kind") != COMPARISON_REPORT_KIND:
        raise BenchmarkJsonError("Unsupported benchmark comparison report kind.")
    schema_version = _integer(root.get("schema_version"), path="report.schema_version")
    if schema_version not in COMPARISON_REPORT_SCHEMA_READ_VERSIONS:
        raise BenchmarkJsonError("Unsupported benchmark comparison report schema version.")
    if schema_version == 1:
        root_keys = _ROOT_KEYS_V1
    elif schema_version == 2:
        root_keys = _ROOT_KEYS_V2
    else:
        root_keys = _ROOT_KEYS_V3
    _exact_keys(root, root_keys, path="report")

    baselines = tuple(_string_list(root["baselines"], path="report.baselines", non_empty=True))
    candidates = tuple(_string_list(root["candidates"], path="report.candidates", non_empty=True))
    if _non_empty_string(root["baseline"], path="report.baseline") != baselines[0]:
        raise BenchmarkJsonError("report.baseline must equal the first baselines entry.")
    if _non_empty_string(root["candidate"], path="report.candidate") != candidates[0]:
        raise BenchmarkJsonError("report.candidate must equal the first candidates entry.")

    baseline_collections = tuple(
        _parse_collection(item, path=f"report.baseline_collections[{index}]")
        for index, item in enumerate(_list(root["baseline_collections"], path="report.baseline_collections"))
    )
    candidate_collections = tuple(
        _parse_collection(item, path=f"report.candidate_collections[{index}]")
        for index, item in enumerate(_list(root["candidate_collections"], path="report.candidate_collections"))
    )
    paired_collections = (
        ()
        if schema_version < 3
        else tuple(
            _parse_paired_collection(item, path=f"report.paired_collections[{index}]")
            for index, item in enumerate(_list(root["paired_collections"], path="report.paired_collections"))
        )
    )
    compatibility = _parse_compatibility(root["compatibility"])
    evidence_policy = _parse_evidence_policy(root["evidence_policy"], schema_version=schema_version)
    if schema_version == 1:
        inference_policy = InferencePolicy(method="legacy_consistency", multiplicity="none")
    else:
        inference_policy = _parse_inference_policy(root["inference_policy"])
    design: ComparisonDesign = (
        "independent"
        if schema_version < 3
        else cast(
            ComparisonDesign,
            _enum_string(root["design"], {"independent", "paired"}, path="report.design"),
        )
    )
    precision_policy = PrecisionPolicy() if schema_version < 3 else _parse_precision_policy(root["precision_policy"])
    provenance, regression_policy = _parse_policy(root["policy"])
    comparison_payloads = _list(root["comparisons"], path="report.comparisons")
    comparisons: list[BenchmarkComparison] = []
    threshold_provenance: list[BenchmarkThresholdProvenance] = []
    for index, item in enumerate(comparison_payloads):
        cell, threshold = _parse_comparison(
            item,
            path=f"report.comparisons[{index}]",
            schema_version=schema_version,
        )
        comparisons.append(cell)
        threshold_provenance.append(threshold)

    try:
        report = BenchmarkComparisonReport(
            baselines=baselines,
            candidates=candidates,
            baseline_collections=baseline_collections,
            candidate_collections=candidate_collections,
            compatibility=compatibility,
            evidence_policy=evidence_policy,
            regression_policy=regression_policy,
            policy_provenance=provenance,
            comparisons=tuple(comparisons),
            threshold_provenance=tuple(threshold_provenance),
            inference_policy=inference_policy,
            design=design,
            precision_policy=precision_policy,
            paired_collections=paired_collections,
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid benchmark comparison report: {exc}") from exc

    for cell, threshold in zip(
        report.comparisons,
        report.threshold_provenance,
        strict=True,
    ):
        _validate_threshold_provenance(
            cell,
            threshold,
            regression_policy=report.regression_policy,
            policy_provenance=report.policy_provenance,
        )

    for key in ("passed", "comparison_passed", "is_comparable", "has_regressions"):
        _ = _boolean(root[key], path=f"report.{key}")
    summary = _mapping(root["summary"], path="report.summary")
    _exact_keys(summary, _SUMMARY_KEYS, path="report.summary")
    for key in _SUMMARY_KEYS:
        _ = _non_negative_integer(summary[key], path=f"report.summary.{key}")
    if schema_version == 1:
        serialized = _v1_report_dict(report)
    elif schema_version == 2:
        serialized = _v2_report_dict(report)
    else:
        serialized = report.to_dict()
    if serialized != dict(root):
        raise BenchmarkJsonError("Benchmark comparison report contains inconsistent derived values.")
    return report


def _record_dict(record: BenchmarkRunRecord) -> dict[str, JsonValue]:
    """Return the stable representation of one collection attempt."""
    return {
        "index": record.index,
        "status": record.status,
        "path": str(record.path),
        "returncode": record.returncode,
        "started_at": record.started_at,
        "duration_seconds": record.duration_seconds,
        "error": record.error,
        "warnings": list(record.warnings),
        "commit": record.commit,
        "environment_fingerprint": record.environment_fingerprint,
    }


def _paired_record_dict(record: BenchmarkPairedRunRecord) -> dict[str, JsonValue]:
    """Return the stable representation of one paired command attempt."""
    return {
        "index": record.index,
        "pair_index": record.pair_index,
        "block_attempt": record.block_attempt,
        "variant": record.variant,
        "pair_order": record.pair_order,
        "order_position": record.order_position,
        "cell_order_index": record.cell_order_index,
        "status": record.status,
        "path": str(record.path),
        "returncode": record.returncode,
        "started_at": record.started_at,
        "duration_seconds": record.duration_seconds,
        "error": record.error,
        "warnings": list(record.warnings),
        "commit": record.commit,
        "environment_fingerprint": record.environment_fingerprint,
    }


def _v1_report_dict(report: BenchmarkComparisonReport) -> dict[str, JsonValue]:
    """Return the frozen schema-v1 representation used only for validation."""
    return {
        "producer": report.producer,
        "kind": report.kind,
        "schema_version": 1,
        "baseline": report.baseline,
        "candidate": report.candidate,
        "baselines": list(report.baselines),
        "candidates": list(report.candidates),
        "baseline_collections": [collection.to_dict() for collection in report.baseline_collections],
        "candidate_collections": [collection.to_dict() for collection in report.candidate_collections],
        "passed": report.passed,
        "comparison_passed": report.comparison_passed,
        "is_comparable": report.is_comparable,
        "has_regressions": report.has_regressions,
        "compatibility": _compatibility_dict(report.compatibility),
        "summary": {
            "improved": len(report.improved),
            "unchanged": len(report.unchanged),
            "regressed": len(report.regressed),
            "inconclusive": len(report.inconclusive),
            "not_comparable": len(report.not_comparable),
        },
        "evidence_policy": _v1_evidence_policy_dict(report.evidence_policy),
        "policy": _policy_dict(report.policy_provenance, report.regression_policy),
        "comparisons": [
            _v1_comparison_dict(cell, threshold)
            for cell, threshold in zip(
                report.comparisons,
                report.threshold_provenance,
                strict=True,
            )
        ],
    }


def _v2_report_dict(report: BenchmarkComparisonReport) -> dict[str, JsonValue]:
    """Return the frozen schema-v2 representation used only for validation."""
    return {
        "producer": report.producer,
        "kind": report.kind,
        "schema_version": 2,
        "baseline": report.baseline,
        "candidate": report.candidate,
        "baselines": list(report.baselines),
        "candidates": list(report.candidates),
        "baseline_collections": [collection.to_dict() for collection in report.baseline_collections],
        "candidate_collections": [collection.to_dict() for collection in report.candidate_collections],
        "passed": report.passed,
        "comparison_passed": report.comparison_passed,
        "is_comparable": report.is_comparable,
        "has_regressions": report.has_regressions,
        "compatibility": _compatibility_dict(report.compatibility),
        "summary": {
            "improved": len(report.improved),
            "unchanged": len(report.unchanged),
            "regressed": len(report.regressed),
            "inconclusive": len(report.inconclusive),
            "not_comparable": len(report.not_comparable),
        },
        "evidence_policy": _evidence_policy_dict(report.evidence_policy),
        "inference_policy": _inference_policy_dict(report.inference_policy),
        "policy": _policy_dict(report.policy_provenance, report.regression_policy),
        "comparisons": [
            _v2_comparison_dict(cell, threshold)
            for cell, threshold in zip(
                report.comparisons,
                report.threshold_provenance,
                strict=True,
            )
        ],
    }


def _compatibility_dict(report: RunCompatibilityReport) -> dict[str, JsonValue]:
    """Return the stable compatibility report representation."""
    return {
        "mode": report.policy.mode,
        "is_compatible": report.is_compatible,
        "pairs_checked": report.pairs_checked,
        "findings": [
            {
                "field": finding.field,
                "severity": finding.severity,
                "reason": finding.reason,
                "baseline_value": _json_value(
                    finding.baseline_value,
                    path="compatibility.finding.baseline_value",
                ),
                "candidate_value": _json_value(
                    finding.candidate_value,
                    path="compatibility.finding.candidate_value",
                ),
                "baseline_run": finding.baseline_run,
                "candidate_run": finding.candidate_run,
            }
            for finding in report.findings
        ],
    }


def _evidence_policy_dict(policy: EvidencePolicy) -> dict[str, JsonValue]:
    """Return the stable evidence policy representation."""
    return {
        "minimum_runs": policy.minimum_runs,
        "minimum_samples_per_run": policy.minimum_samples_per_run,
        "minimum_rounds_per_run": policy.minimum_rounds_per_run,
        "require_rounds": policy.require_rounds,
        "require_iterations": policy.require_iterations,
        "require_raw_samples_for_inference": policy.require_raw_samples_for_inference,
        "minimum_tail_samples_per_run": policy.minimum_tail_samples_per_run,
        "require_tail_iterations_one": policy.require_tail_iterations_one,
        "maximum_cv": policy.maximum_cv,
        "maximum_outlier_fraction": policy.maximum_outlier_fraction,
    }


def _v1_evidence_policy_dict(policy: EvidencePolicy) -> dict[str, JsonValue]:
    """Return the frozen schema-v1 evidence policy representation."""
    return {
        "minimum_runs": policy.minimum_runs,
        "minimum_samples_per_run": policy.minimum_samples_per_run,
        "require_rounds": policy.require_rounds,
        "require_iterations": policy.require_iterations,
        "maximum_cv": policy.maximum_cv,
        "maximum_outlier_fraction": policy.maximum_outlier_fraction,
    }


def _inference_policy_dict(policy: InferencePolicy) -> dict[str, JsonValue]:
    """Return the stable inference policy representation."""
    return {
        "method": policy.method,
        "confidence_level": policy.confidence_level,
        "resamples": policy.resamples,
        "random_seed": policy.random_seed,
        "multiplicity": policy.multiplicity,
    }


def _precision_policy_dict(policy: PrecisionPolicy) -> dict[str, JsonValue]:
    """Return the stable precision-planning policy representation."""
    return {"target_half_width_percent": policy.target_half_width_percent}


def _policy_dict(
    provenance: BenchmarkPolicyProvenance,
    regression: RegressionPolicy,
) -> dict[str, JsonValue]:
    """Return stable policy provenance and effective regression rules."""
    regression_payload: dict[str, JsonValue] = {
        "default_threshold_percent": regression.default_threshold_percent,
        "by_metric": {str(key): value for key, value in regression.by_metric.items()},
        "by_implementation": dict(regression.by_implementation),
        "by_case": dict(regression.by_case),
        "by_cell": [
            {
                "implementation": implementation,
                "case": case,
                "metric": metric,
                "threshold_percent": threshold,
            }
            for (implementation, case, metric), threshold in regression.by_cell.items()
        ],
    }
    return {
        "selection": provenance.selection,
        "configuration_file": provenance.configuration_file,
        "configured_fields": list(provenance.configured_fields),
        "cli_overrides": list(provenance.cli_overrides),
        "regression": regression_payload,
    }


def _comparison_dict(
    cell: BenchmarkComparison,
    threshold: BenchmarkThresholdProvenance,
) -> dict[str, JsonValue]:
    """Return the stable representation of one matrix-cell result."""
    return {
        "implementation_name": cell.implementation_name,
        "case_name": cell.case_name,
        "metric_name": cell.metric_name,
        "statistic": cell.statistic,
        "direction": cell.direction,
        "status": cell.status,
        "regression": cell.regression,
        "baseline_value": cell.baseline_value,
        "candidate_value": cell.candidate_value,
        "ratio": cell.ratio,
        "percent_change": cell.percent_change,
        "improvement_percent": cell.improvement_percent,
        "improvement_low_percent": cell.improvement_low_percent,
        "improvement_high_percent": cell.improvement_high_percent,
        "threshold_percent": cell.threshold_percent,
        "threshold_source": {
            "scope": threshold.scope,
            "origin": threshold.origin,
            "field": threshold.field,
        },
        "unit": cell.unit,
        "reason": cell.reason,
        "baseline_evidence": _evidence_dict(cell.baseline_evidence),
        "candidate_evidence": _evidence_dict(cell.candidate_evidence),
        "inference": _inference_dict(cell.inference),
        "precision": _precision_plan_dict(cell.precision),
    }


def _v2_comparison_dict(
    cell: BenchmarkComparison,
    threshold: BenchmarkThresholdProvenance,
) -> dict[str, JsonValue]:
    """Return the frozen schema-v2 representation of one result."""
    payload = _comparison_dict(cell, threshold)
    del payload["precision"]
    payload["inference"] = _v2_inference_dict(cell.inference)
    return payload


def _v1_comparison_dict(
    cell: BenchmarkComparison,
    threshold: BenchmarkThresholdProvenance,
) -> dict[str, JsonValue]:
    """Return the frozen schema-v1 representation of one result."""
    payload = _v2_comparison_dict(cell, threshold)
    del payload["inference"]
    payload["baseline_evidence"] = _v1_evidence_dict(cell.baseline_evidence)
    payload["candidate_evidence"] = _v1_evidence_dict(cell.candidate_evidence)
    return payload


def _evidence_dict(evidence: BenchmarkEvidence | None) -> dict[str, JsonValue] | None:
    """Return the stable representation of cell evidence."""
    if evidence is None:
        return None
    return {
        "provided_run_count": evidence.provided_run_count,
        "observed_run_count": evidence.observed_run_count,
        "rounds": list(evidence.rounds),
        "iterations": list(evidence.iterations),
        "sample_counts": list(evidence.sample_counts),
        "sample_count": evidence.sample_count,
        "iqr": evidence.iqr,
        "coefficient_of_variation": evidence.coefficient_of_variation,
        "outlier_count": evidence.outlier_count,
        "outlier_fraction": evidence.outlier_fraction,
        "adequate": evidence.adequate,
        "issues": list(evidence.issues),
        "run_iqrs": list(evidence.run_iqrs),
        "run_coefficients_of_variation": list(evidence.run_coefficients_of_variation),
        "run_outlier_counts": list(evidence.run_outlier_counts),
        "run_outlier_fractions": list(evidence.run_outlier_fractions),
    }


def _v1_evidence_dict(evidence: BenchmarkEvidence | None) -> dict[str, JsonValue] | None:
    """Return the frozen schema-v1 representation of cell evidence."""
    payload = _evidence_dict(evidence)
    if payload is None:
        return None
    for key in (
        "run_iqrs",
        "run_coefficients_of_variation",
        "run_outlier_counts",
        "run_outlier_fractions",
    ):
        del payload[key]
    return payload


def _inference_dict(inference: BenchmarkInference | None) -> dict[str, JsonValue] | None:
    """Return the stable representation of one cell's inference result."""
    if inference is None:
        return None
    return {
        "method": inference.method,
        "estimand": inference.estimand,
        "design": inference.design,
        "confidence_level": inference.confidence_level,
        "adjusted_confidence_level": inference.adjusted_confidence_level,
        "multiplicity": inference.multiplicity,
        "family_size": inference.family_size,
        "resamples": inference.resamples,
        "random_seed": inference.random_seed,
        "estimate_percent": inference.estimate_percent,
        "confidence_low_percent": inference.confidence_low_percent,
        "confidence_high_percent": inference.confidence_high_percent,
        "warnings": list(inference.warnings),
        "issues": list(inference.issues),
        "adequate": inference.adequate,
        "pair_count": inference.pair_count,
        "strata_count": inference.strata_count,
    }


def _v2_inference_dict(inference: BenchmarkInference | None) -> dict[str, JsonValue] | None:
    """Return the frozen schema-v2 inference representation."""
    payload = _inference_dict(inference)
    if payload is not None:
        del payload["pair_count"]
        del payload["strata_count"]
    return payload


def _precision_plan_dict(plan: PrecisionPlan | None) -> dict[str, JsonValue] | None:
    """Return the stable representation of one precision plan."""
    if plan is None:
        return None
    return {
        "method": plan.method,
        "pilot_pairs": plan.pilot_pairs,
        "target_half_width_percent": plan.target_half_width_percent,
        "confidence_level": plan.confidence_level,
        "adjusted_confidence_level": plan.adjusted_confidence_level,
        "multiplicity": plan.multiplicity,
        "family_size": plan.family_size,
        "pilot_log_ratio_standard_deviation": plan.pilot_log_ratio_standard_deviation,
        "critical_value": plan.critical_value,
        "minimum_pairs": plan.minimum_pairs,
        "pair_count_multiple": plan.pair_count_multiple,
        "unconstrained_required_pairs": plan.unconstrained_required_pairs,
        "required_pairs": plan.required_pairs,
        "additional_pairs": plan.additional_pairs,
        "strata_count": plan.strata_count,
        "assumptions": list(plan.assumptions),
        "warnings": list(plan.warnings),
        "issues": list(plan.issues),
        "adequate": plan.adequate,
    }


def _parse_collection(value: object, *, path: str) -> BenchmarkCollectionSnapshot:
    """Parse one collection snapshot."""
    payload = _mapping(value, path=path)
    _exact_keys(payload, _COLLECTION_KEYS, path=path)
    expected_cells = tuple(
        _parse_cell(item, path=f"{path}.expected_cells[{index}]")
        for index, item in enumerate(_list(payload["expected_cells"], path=f"{path}.expected_cells"))
    )
    records = tuple(
        _parse_record(item, path=f"{path}.runs[{index}]")
        for index, item in enumerate(_list(payload["runs"], path=f"{path}.runs"))
    )
    try:
        snapshot = BenchmarkCollectionSnapshot(
            manifest=_non_empty_string(payload["manifest"], path=f"{path}.manifest"),
            created_at=_non_empty_string(payload["created_at"], path=f"{path}.created_at"),
            command=tuple(_string_list(payload["command"], path=f"{path}.command", non_empty=True)),
            cwd=_non_empty_string(payload["cwd"], path=f"{path}.cwd"),
            commit=_optional_string(payload["commit"], path=f"{path}.commit"),
            environment_fingerprint=_optional_string(
                payload["environment_fingerprint"],
                path=f"{path}.environment_fingerprint",
            ),
            requested_runs=_positive_integer(payload["requested_runs"], path=f"{path}.requested_runs"),
            expected_cells=expected_cells,
            records=records,
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid collection snapshot at {path}: {exc}") from exc
    for key in ("attempted_runs", "successful_runs", "failed_runs"):
        _ = _non_negative_integer(payload[key], path=f"{path}.{key}")
    _ = _boolean(payload["complete"], path=f"{path}.complete")
    if snapshot.to_dict() != dict(payload):
        raise BenchmarkJsonError(f"Collection snapshot contains inconsistent derived values at {path}.")
    return snapshot


def _parse_paired_collection(value: object, *, path: str) -> BenchmarkPairedCollectionSnapshot:
    """Parse one paired collection snapshot."""
    payload = _mapping(value, path=path)
    _exact_keys(payload, _PAIRED_COLLECTION_KEYS, path=path)
    expected_cells = tuple(
        _parse_cell(item, path=f"{path}.expected_cells[{index}]")
        for index, item in enumerate(_list(payload["expected_cells"], path=f"{path}.expected_cells"))
    )
    records = tuple(
        _parse_paired_record(item, path=f"{path}.runs[{index}]")
        for index, item in enumerate(_list(payload["runs"], path=f"{path}.runs"))
    )
    try:
        snapshot = BenchmarkPairedCollectionSnapshot(
            manifest=_non_empty_string(payload["manifest"], path=f"{path}.manifest"),
            created_at=_non_empty_string(payload["created_at"], path=f"{path}.created_at"),
            baseline_command=tuple(
                _string_list(payload["baseline_command"], path=f"{path}.baseline_command", non_empty=True)
            ),
            candidate_command=tuple(
                _string_list(payload["candidate_command"], path=f"{path}.candidate_command", non_empty=True)
            ),
            baseline_cwd=_non_empty_string(payload["baseline_cwd"], path=f"{path}.baseline_cwd"),
            candidate_cwd=_non_empty_string(payload["candidate_cwd"], path=f"{path}.candidate_cwd"),
            baseline_commit=_optional_string(payload["baseline_commit"], path=f"{path}.baseline_commit"),
            candidate_commit=_optional_string(payload["candidate_commit"], path=f"{path}.candidate_commit"),
            baseline_environment_fingerprint=_optional_string(
                payload["baseline_environment_fingerprint"],
                path=f"{path}.baseline_environment_fingerprint",
            ),
            candidate_environment_fingerprint=_optional_string(
                payload["candidate_environment_fingerprint"],
                path=f"{path}.candidate_environment_fingerprint",
            ),
            requested_pairs=_positive_integer(payload["requested_pairs"], path=f"{path}.requested_pairs"),
            random_seed=_non_negative_integer(payload["random_seed"], path=f"{path}.random_seed"),
            expected_cells=expected_cells,
            records=records,
            automatic_pairs=_boolean(payload["automatic_pairs"], path=f"{path}.automatic_pairs"),
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid paired collection snapshot at {path}: {exc}") from exc
    for key in (
        "attempted_commands",
        "successful_commands",
        "failed_commands",
        "complete_pairs",
        "orphan_successes",
    ):
        _ = _non_negative_integer(payload[key], path=f"{path}.{key}")
    _ = _boolean(payload["complete"], path=f"{path}.complete")
    if snapshot.to_dict() != dict(payload):
        raise BenchmarkJsonError(f"Paired collection snapshot contains inconsistent derived values at {path}.")
    return snapshot


def _parse_record(value: object, *, path: str) -> BenchmarkRunRecord:
    """Parse one portable collection record."""
    payload = _mapping(value, path=path)
    _exact_keys(payload, _RECORD_KEYS, path=path)
    status = _string(payload["status"], path=f"{path}.status")
    if status not in {"succeeded", "failed"}:
        raise BenchmarkJsonError(f"Unsupported collection status at {path}.status: {status!r}.")
    try:
        return BenchmarkRunRecord(
            index=_positive_integer(payload["index"], path=f"{path}.index"),
            status=cast(CollectionRunStatus, status),
            path=Path(_non_empty_string(payload["path"], path=f"{path}.path")),
            returncode=_optional_integer(payload["returncode"], path=f"{path}.returncode"),
            started_at=_non_empty_string(payload["started_at"], path=f"{path}.started_at"),
            duration_seconds=_non_negative_number(
                payload["duration_seconds"],
                path=f"{path}.duration_seconds",
            ),
            error=_optional_string(payload["error"], path=f"{path}.error"),
            warnings=tuple(_string_list(payload["warnings"], path=f"{path}.warnings")),
            commit=_optional_string(payload["commit"], path=f"{path}.commit"),
            environment_fingerprint=_optional_string(
                payload["environment_fingerprint"],
                path=f"{path}.environment_fingerprint",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid collection record at {path}: {exc}") from exc


def _parse_paired_record(value: object, *, path: str) -> BenchmarkPairedRunRecord:
    """Parse one portable paired command record."""
    payload = _mapping(value, path=path)
    _exact_keys(payload, _PAIRED_RECORD_KEYS, path=path)
    status = _enum_string(payload["status"], {"succeeded", "failed"}, path=f"{path}.status")
    variant = _enum_string(payload["variant"], {"baseline", "candidate"}, path=f"{path}.variant")
    pair_order = _enum_string(payload["pair_order"], {"AB", "BA"}, path=f"{path}.pair_order")
    try:
        return BenchmarkPairedRunRecord(
            index=_positive_integer(payload["index"], path=f"{path}.index"),
            pair_index=_positive_integer(payload["pair_index"], path=f"{path}.pair_index"),
            block_attempt=_positive_integer(payload["block_attempt"], path=f"{path}.block_attempt"),
            variant=cast(Literal["baseline", "candidate"], variant),
            pair_order=cast(Literal["AB", "BA"], pair_order),
            order_position=_positive_integer(payload["order_position"], path=f"{path}.order_position"),
            cell_order_index=_positive_integer(
                payload["cell_order_index"],
                path=f"{path}.cell_order_index",
            ),
            status=cast(CollectionRunStatus, status),
            path=Path(_non_empty_string(payload["path"], path=f"{path}.path")),
            returncode=_optional_integer(payload["returncode"], path=f"{path}.returncode"),
            started_at=_non_empty_string(payload["started_at"], path=f"{path}.started_at"),
            duration_seconds=_non_negative_number(
                payload["duration_seconds"],
                path=f"{path}.duration_seconds",
            ),
            error=_optional_string(payload["error"], path=f"{path}.error"),
            warnings=tuple(_string_list(payload["warnings"], path=f"{path}.warnings")),
            commit=_optional_string(payload["commit"], path=f"{path}.commit"),
            environment_fingerprint=_optional_string(
                payload["environment_fingerprint"],
                path=f"{path}.environment_fingerprint",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid paired collection record at {path}: {exc}") from exc


def _parse_cell(value: object, *, path: str) -> BenchmarkCell:
    """Parse one expected matrix cell."""
    payload = _mapping(value, path=path)
    _exact_keys(payload, _CELL_KEYS, path=path)
    metric = _metric(payload["metric_name"], path=f"{path}.metric_name")
    return (
        _non_empty_string(payload["implementation_name"], path=f"{path}.implementation_name"),
        _non_empty_string(payload["case_name"], path=f"{path}.case_name"),
        metric,
    )


def _parse_compatibility(value: object) -> RunCompatibilityReport:
    """Parse the run compatibility report section."""
    path = "report.compatibility"
    payload = _mapping(value, path=path)
    _exact_keys(payload, _COMPATIBILITY_KEYS, path=path)
    mode = _string(payload["mode"], path=f"{path}.mode")
    if mode not in {"strict", "permissive", "off"}:
        raise BenchmarkJsonError(f"Unsupported compatibility mode at {path}.mode: {mode!r}.")
    findings = tuple(
        _parse_finding(item, path=f"{path}.findings[{index}]")
        for index, item in enumerate(_list(payload["findings"], path=f"{path}.findings"))
    )
    report = RunCompatibilityReport(
        policy=RunCompatibilityPolicy(mode=cast(CompatibilityMode, mode)),
        findings=findings,
        pairs_checked=_non_negative_integer(payload["pairs_checked"], path=f"{path}.pairs_checked"),
    )
    _ = _boolean(payload["is_compatible"], path=f"{path}.is_compatible")
    if report.is_compatible != payload["is_compatible"]:
        raise BenchmarkJsonError("report.compatibility.is_compatible is inconsistent with findings.")
    return report


def _parse_finding(value: object, *, path: str) -> RunCompatibilityFinding:
    """Parse one compatibility finding."""
    payload = _mapping(value, path=path)
    _exact_keys(payload, _FINDING_KEYS, path=path)
    severity = _string(payload["severity"], path=f"{path}.severity")
    if severity not in {"blocking", "warning"}:
        raise BenchmarkJsonError(f"Unsupported compatibility severity at {path}.severity: {severity!r}.")
    return RunCompatibilityFinding(
        field=_non_empty_string(payload["field"], path=f"{path}.field"),
        baseline_value=_json_value(payload["baseline_value"], path=f"{path}.baseline_value"),
        candidate_value=_json_value(payload["candidate_value"], path=f"{path}.candidate_value"),
        severity=cast(CompatibilitySeverity, severity),
        reason=_non_empty_string(payload["reason"], path=f"{path}.reason"),
        baseline_run=_optional_string(payload["baseline_run"], path=f"{path}.baseline_run"),
        candidate_run=_optional_string(payload["candidate_run"], path=f"{path}.candidate_run"),
    )


def _parse_evidence_policy(value: object, *, schema_version: int) -> EvidencePolicy:
    """Parse the effective evidence policy."""
    path = "report.evidence_policy"
    payload = _mapping(value, path=path)
    keys = _EVIDENCE_POLICY_KEYS_V1 if schema_version == 1 else _EVIDENCE_POLICY_KEYS_V2
    _exact_keys(payload, keys, path=path)
    try:
        return EvidencePolicy(
            minimum_runs=_integer(payload["minimum_runs"], path=f"{path}.minimum_runs"),
            minimum_samples_per_run=_integer(
                payload["minimum_samples_per_run"],
                path=f"{path}.minimum_samples_per_run",
            ),
            minimum_rounds_per_run=(
                0
                if schema_version == 1
                else _integer(payload["minimum_rounds_per_run"], path=f"{path}.minimum_rounds_per_run")
            ),
            require_rounds=_boolean(payload["require_rounds"], path=f"{path}.require_rounds"),
            require_iterations=_boolean(
                payload["require_iterations"],
                path=f"{path}.require_iterations",
            ),
            require_raw_samples_for_inference=(
                False
                if schema_version == 1
                else _boolean(
                    payload["require_raw_samples_for_inference"],
                    path=f"{path}.require_raw_samples_for_inference",
                )
            ),
            minimum_tail_samples_per_run=(
                0
                if schema_version == 1
                else _integer(
                    payload["minimum_tail_samples_per_run"],
                    path=f"{path}.minimum_tail_samples_per_run",
                )
            ),
            require_tail_iterations_one=(
                False
                if schema_version == 1
                else _boolean(
                    payload["require_tail_iterations_one"],
                    path=f"{path}.require_tail_iterations_one",
                )
            ),
            maximum_cv=_optional_number(payload["maximum_cv"], path=f"{path}.maximum_cv"),
            maximum_outlier_fraction=_optional_number(
                payload["maximum_outlier_fraction"],
                path=f"{path}.maximum_outlier_fraction",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid evidence policy: {exc}") from exc


def _parse_inference_policy(value: object) -> InferencePolicy:
    """Parse the effective inference policy."""
    path = "report.inference_policy"
    payload = _mapping(value, path=path)
    _exact_keys(payload, _INFERENCE_POLICY_KEYS, path=path)
    method = _enum_string(
        payload["method"],
        {"bca_bootstrap", "legacy_consistency"},
        path=f"{path}.method",
    )
    multiplicity = _enum_string(
        payload["multiplicity"],
        {"bonferroni", "none"},
        path=f"{path}.multiplicity",
    )
    try:
        return InferencePolicy(
            method=cast(Literal["bca_bootstrap", "legacy_consistency"], method),
            confidence_level=_number(payload["confidence_level"], path=f"{path}.confidence_level"),
            resamples=_integer(payload["resamples"], path=f"{path}.resamples"),
            random_seed=_integer(payload["random_seed"], path=f"{path}.random_seed"),
            multiplicity=cast(Literal["bonferroni", "none"], multiplicity),
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid inference policy: {exc}") from exc


def _parse_precision_policy(value: object) -> PrecisionPolicy:
    """Parse the effective paired precision-planning policy."""
    path = "report.precision_policy"
    payload = _mapping(value, path=path)
    _exact_keys(payload, _PRECISION_POLICY_KEYS, path=path)
    try:
        return PrecisionPolicy(
            target_half_width_percent=_optional_number(
                payload["target_half_width_percent"],
                path=f"{path}.target_half_width_percent",
            )
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid precision policy: {exc}") from exc


def _parse_policy(value: object) -> tuple[BenchmarkPolicyProvenance, RegressionPolicy]:
    """Parse policy provenance and effective regression rules."""
    path = "report.policy"
    payload = _mapping(value, path=path)
    _exact_keys(payload, _POLICY_KEYS, path=path)
    selection = _string(payload["selection"], path=f"{path}.selection")
    if selection not in {"defaults", "disabled", "discovered", "explicit"}:
        raise BenchmarkJsonError(f"Unsupported policy selection at {path}.selection: {selection!r}.")
    try:
        provenance = BenchmarkPolicyProvenance(
            selection=cast(PolicySelection, selection),
            configuration_file=_optional_string(
                payload["configuration_file"],
                path=f"{path}.configuration_file",
            ),
            configured_fields=tuple(_string_list(payload["configured_fields"], path=f"{path}.configured_fields")),
            cli_overrides=tuple(_string_list(payload["cli_overrides"], path=f"{path}.cli_overrides")),
        )
        regression = _parse_regression_policy(payload["regression"])
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid report policy: {exc}") from exc
    return provenance, regression


def _parse_regression_policy(value: object) -> RegressionPolicy:
    """Parse the effective regression policy."""
    path = "report.policy.regression"
    payload = _mapping(value, path=path)
    _exact_keys(payload, _REGRESSION_POLICY_KEYS, path=path)
    by_metric = _numeric_mapping(payload["by_metric"], path=f"{path}.by_metric")
    by_implementation = _numeric_mapping(
        payload["by_implementation"],
        path=f"{path}.by_implementation",
    )
    by_case = _numeric_mapping(payload["by_case"], path=f"{path}.by_case")
    by_cell: dict[tuple[str, str, MetricName], float] = {}
    for index, item in enumerate(_list(payload["by_cell"], path=f"{path}.by_cell")):
        cell_path = f"{path}.by_cell[{index}]"
        cell = _mapping(item, path=cell_path)
        _exact_keys(cell, _POLICY_CELL_KEYS, path=cell_path)
        key = (
            _non_empty_string(cell["implementation"], path=f"{cell_path}.implementation"),
            _non_empty_string(cell["case"], path=f"{cell_path}.case"),
            _metric(cell["metric"], path=f"{cell_path}.metric"),
        )
        if key in by_cell:
            raise BenchmarkJsonError(f"Duplicate regression cell at {cell_path}: {key!r}.")
        by_cell[key] = _number(cell["threshold_percent"], path=f"{cell_path}.threshold_percent")
    try:
        return RegressionPolicy(
            default_threshold_percent=_number(
                payload["default_threshold_percent"],
                path=f"{path}.default_threshold_percent",
            ),
            by_metric=cast(Mapping[MetricName, float], by_metric),
            by_implementation=by_implementation,
            by_case=by_case,
            by_cell=by_cell,
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid regression policy: {exc}") from exc


def _parse_comparison(
    value: object,
    *,
    path: str,
    schema_version: int,
) -> tuple[BenchmarkComparison, BenchmarkThresholdProvenance]:
    """Parse one reported cell and its threshold provenance."""
    payload = _mapping(value, path=path)
    if schema_version == 1:
        keys = _COMPARISON_KEYS_V1
    elif schema_version == 2:
        keys = _COMPARISON_KEYS_V2
    else:
        keys = _COMPARISON_KEYS_V3
    _exact_keys(payload, keys, path=path)
    direction = _enum_string(
        payload["direction"],
        {"lower_is_better", "higher_is_better"},
        path=f"{path}.direction",
    )
    status = _enum_string(
        payload["status"],
        {"matched", "missing_baseline", "missing_candidate", "incompatible"},
        path=f"{path}.status",
    )
    regression = _enum_string(
        payload["regression"],
        {"improved", "unchanged", "regressed", "inconclusive", "not_comparable"},
        path=f"{path}.regression",
    )
    threshold = _parse_threshold_source(payload["threshold_source"], path=f"{path}.threshold_source")
    cell = BenchmarkComparison(
        implementation_name=_non_empty_string(
            payload["implementation_name"],
            path=f"{path}.implementation_name",
        ),
        case_name=_non_empty_string(payload["case_name"], path=f"{path}.case_name"),
        metric_name=_metric(payload["metric_name"], path=f"{path}.metric_name"),
        statistic=_non_empty_string(payload["statistic"], path=f"{path}.statistic"),
        direction=cast(ComparisonDirection, direction),
        status=cast(ComparisonStatus, status),
        baseline_value=_optional_number(payload["baseline_value"], path=f"{path}.baseline_value"),
        candidate_value=_optional_number(payload["candidate_value"], path=f"{path}.candidate_value"),
        ratio=_optional_number(payload["ratio"], path=f"{path}.ratio"),
        percent_change=_optional_number(payload["percent_change"], path=f"{path}.percent_change"),
        improvement_percent=_optional_number(
            payload["improvement_percent"],
            path=f"{path}.improvement_percent",
        ),
        regression=cast(RegressionClassification, regression),
        threshold_percent=_non_negative_number(
            payload["threshold_percent"],
            path=f"{path}.threshold_percent",
        ),
        unit=_string(payload["unit"], path=f"{path}.unit"),
        baseline_evidence=_parse_evidence(
            payload["baseline_evidence"],
            path=f"{path}.baseline_evidence",
            schema_version=schema_version,
        ),
        candidate_evidence=_parse_evidence(
            payload["candidate_evidence"],
            path=f"{path}.candidate_evidence",
            schema_version=schema_version,
        ),
        improvement_low_percent=_optional_number(
            payload["improvement_low_percent"],
            path=f"{path}.improvement_low_percent",
        ),
        improvement_high_percent=_optional_number(
            payload["improvement_high_percent"],
            path=f"{path}.improvement_high_percent",
        ),
        reason=_optional_string(payload["reason"], path=f"{path}.reason"),
        inference=(
            None
            if schema_version == 1
            else _parse_inference(
                payload["inference"],
                path=f"{path}.inference",
                schema_version=schema_version,
            )
        ),
        precision=(
            None if schema_version < 3 else _parse_precision_plan(payload["precision"], path=f"{path}.precision")
        ),
    )
    expected_threshold = _expected_threshold_field(cell, scope=threshold.scope)
    if threshold.field != expected_threshold:
        raise BenchmarkJsonError(f"Threshold provenance field is inconsistent at {path}.threshold_source.")
    return cell, threshold


def _parse_threshold_source(value: object, *, path: str) -> BenchmarkThresholdProvenance:
    """Parse threshold rule provenance."""
    payload = _mapping(value, path=path)
    _exact_keys(payload, _THRESHOLD_SOURCE_KEYS, path=path)
    scope = _enum_string(
        payload["scope"],
        {"cell", "case", "implementation", "metric", "default"},
        path=f"{path}.scope",
    )
    origin = _enum_string(
        payload["origin"],
        {"built_in", "configuration", "cli"},
        path=f"{path}.origin",
    )
    return BenchmarkThresholdProvenance(
        scope=cast(RegressionThresholdScope, scope),
        origin=cast(ThresholdOrigin, origin),
        field=_non_empty_string(payload["field"], path=f"{path}.field"),
    )


def _parse_evidence(
    value: object,
    *,
    path: str,
    schema_version: int,
) -> BenchmarkEvidence | None:
    """Parse optional cell evidence diagnostics."""
    if value is None:
        return None
    payload = _mapping(value, path=path)
    keys = _EVIDENCE_KEYS_V1 if schema_version == 1 else _EVIDENCE_KEYS_V2
    _exact_keys(payload, keys, path=path)
    rounds = tuple(
        None if item is None else _positive_integer(item, path=f"{path}.rounds[{index}]")
        for index, item in enumerate(_list(payload["rounds"], path=f"{path}.rounds"))
    )
    iterations = tuple(
        None if item is None else _positive_integer(item, path=f"{path}.iterations[{index}]")
        for index, item in enumerate(_list(payload["iterations"], path=f"{path}.iterations"))
    )
    sample_counts = tuple(
        _non_negative_integer(item, path=f"{path}.sample_counts[{index}]")
        for index, item in enumerate(_list(payload["sample_counts"], path=f"{path}.sample_counts"))
    )
    evidence = BenchmarkEvidence(
        provided_run_count=_non_negative_integer(
            payload["provided_run_count"],
            path=f"{path}.provided_run_count",
        ),
        observed_run_count=_non_negative_integer(
            payload["observed_run_count"],
            path=f"{path}.observed_run_count",
        ),
        rounds=rounds,
        iterations=iterations,
        sample_counts=sample_counts,
        sample_count=_non_negative_integer(payload["sample_count"], path=f"{path}.sample_count"),
        iqr=_optional_number(payload["iqr"], path=f"{path}.iqr"),
        coefficient_of_variation=_optional_number(
            payload["coefficient_of_variation"],
            path=f"{path}.coefficient_of_variation",
        ),
        outlier_count=(
            None
            if payload["outlier_count"] is None
            else _non_negative_integer(payload["outlier_count"], path=f"{path}.outlier_count")
        ),
        outlier_fraction=_optional_number(
            payload["outlier_fraction"],
            path=f"{path}.outlier_fraction",
        ),
        adequate=_boolean(payload["adequate"], path=f"{path}.adequate"),
        issues=tuple(_string_list(payload["issues"], path=f"{path}.issues")),
        run_iqrs=(() if schema_version == 1 else _optional_number_list(payload["run_iqrs"], path=f"{path}.run_iqrs")),
        run_coefficients_of_variation=(
            ()
            if schema_version == 1
            else _optional_number_list(
                payload["run_coefficients_of_variation"],
                path=f"{path}.run_coefficients_of_variation",
            )
        ),
        run_outlier_counts=(
            ()
            if schema_version == 1
            else tuple(
                None if item is None else _non_negative_integer(item, path=f"{path}.run_outlier_counts[{index}]")
                for index, item in enumerate(_list(payload["run_outlier_counts"], path=f"{path}.run_outlier_counts"))
            )
        ),
        run_outlier_fractions=(
            ()
            if schema_version == 1
            else _optional_number_list(
                payload["run_outlier_fractions"],
                path=f"{path}.run_outlier_fractions",
            )
        ),
    )
    _validate_evidence_shape(evidence, path=path, schema_version=schema_version)
    return evidence


def _parse_inference(
    value: object,
    *,
    path: str,
    schema_version: int,
) -> BenchmarkInference | None:
    """Parse optional run-level inference for one matrix cell."""
    if value is None:
        return None
    payload = _mapping(value, path=path)
    keys = _INFERENCE_KEYS_V2 if schema_version == 2 else _INFERENCE_KEYS_V3
    _exact_keys(payload, keys, path=path)
    method = _enum_string(
        payload["method"],
        {"bca_bootstrap", "percentile_bootstrap"},
        path=f"{path}.method",
    )
    allowed_designs = {"independent"} if schema_version == 2 else {"independent", "paired"}
    design = _enum_string(payload["design"], allowed_designs, path=f"{path}.design")
    multiplicity = _enum_string(
        payload["multiplicity"],
        {"bonferroni", "none"},
        path=f"{path}.multiplicity",
    )
    try:
        inference = BenchmarkInference(
            method=cast(Literal["bca_bootstrap", "percentile_bootstrap"], method),
            estimand=_non_empty_string(payload["estimand"], path=f"{path}.estimand"),
            design=cast(ComparisonDesign, design),
            confidence_level=_number(payload["confidence_level"], path=f"{path}.confidence_level"),
            adjusted_confidence_level=_number(
                payload["adjusted_confidence_level"],
                path=f"{path}.adjusted_confidence_level",
            ),
            multiplicity=cast(Literal["bonferroni", "none"], multiplicity),
            family_size=_positive_integer(payload["family_size"], path=f"{path}.family_size"),
            resamples=_positive_integer(payload["resamples"], path=f"{path}.resamples"),
            random_seed=_non_negative_integer(payload["random_seed"], path=f"{path}.random_seed"),
            estimate_percent=_optional_number(payload["estimate_percent"], path=f"{path}.estimate_percent"),
            confidence_low_percent=_optional_number(
                payload["confidence_low_percent"],
                path=f"{path}.confidence_low_percent",
            ),
            confidence_high_percent=_optional_number(
                payload["confidence_high_percent"],
                path=f"{path}.confidence_high_percent",
            ),
            warnings=tuple(_string_list(payload["warnings"], path=f"{path}.warnings")),
            issues=tuple(_string_list(payload["issues"], path=f"{path}.issues")),
            pair_count=(
                None if schema_version == 2 else _optional_integer(payload["pair_count"], path=f"{path}.pair_count")
            ),
            strata_count=(
                None if schema_version == 2 else _optional_integer(payload["strata_count"], path=f"{path}.strata_count")
            ),
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid benchmark inference at {path}: {exc}") from exc
    adequate = _boolean(payload["adequate"], path=f"{path}.adequate")
    if inference.adequate != adequate:
        raise BenchmarkJsonError(f"Inference adequacy is inconsistent at {path}.adequate.")
    return inference


def _parse_precision_plan(value: object, *, path: str) -> PrecisionPlan | None:
    """Parse optional fixed-design precision planning for one matrix cell."""
    if value is None:
        return None
    payload = _mapping(value, path=path)
    _exact_keys(payload, _PRECISION_PLAN_KEYS, path=path)
    method = _enum_string(payload["method"], {"paired_log_ratio_t"}, path=f"{path}.method")
    multiplicity = _enum_string(
        payload["multiplicity"],
        {"bonferroni", "none"},
        path=f"{path}.multiplicity",
    )
    try:
        plan = PrecisionPlan(
            method=cast(Literal["paired_log_ratio_t"], method),
            pilot_pairs=_non_negative_integer(payload["pilot_pairs"], path=f"{path}.pilot_pairs"),
            target_half_width_percent=_number(
                payload["target_half_width_percent"],
                path=f"{path}.target_half_width_percent",
            ),
            confidence_level=_number(payload["confidence_level"], path=f"{path}.confidence_level"),
            adjusted_confidence_level=_number(
                payload["adjusted_confidence_level"],
                path=f"{path}.adjusted_confidence_level",
            ),
            multiplicity=cast(Literal["bonferroni", "none"], multiplicity),
            family_size=_positive_integer(payload["family_size"], path=f"{path}.family_size"),
            pilot_log_ratio_standard_deviation=_optional_number(
                payload["pilot_log_ratio_standard_deviation"],
                path=f"{path}.pilot_log_ratio_standard_deviation",
            ),
            critical_value=_optional_number(payload["critical_value"], path=f"{path}.critical_value"),
            minimum_pairs=_positive_integer(payload["minimum_pairs"], path=f"{path}.minimum_pairs"),
            pair_count_multiple=_positive_integer(
                payload["pair_count_multiple"],
                path=f"{path}.pair_count_multiple",
            ),
            unconstrained_required_pairs=_optional_integer(
                payload["unconstrained_required_pairs"],
                path=f"{path}.unconstrained_required_pairs",
            ),
            required_pairs=_optional_integer(payload["required_pairs"], path=f"{path}.required_pairs"),
            additional_pairs=_optional_integer(
                payload["additional_pairs"],
                path=f"{path}.additional_pairs",
            ),
            strata_count=_non_negative_integer(payload["strata_count"], path=f"{path}.strata_count"),
            assumptions=tuple(_string_list(payload["assumptions"], path=f"{path}.assumptions")),
            warnings=tuple(_string_list(payload["warnings"], path=f"{path}.warnings")),
            issues=tuple(_string_list(payload["issues"], path=f"{path}.issues")),
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid precision plan at {path}: {exc}") from exc
    adequate = _boolean(payload["adequate"], path=f"{path}.adequate")
    if plan.adequate != adequate:
        raise BenchmarkJsonError(f"Precision-plan adequacy is inconsistent at {path}.adequate.")
    return plan


def _optional_number_list(value: object, *, path: str) -> tuple[float | None, ...]:
    """Parse a list of optional finite numbers."""
    return tuple(_optional_number(item, path=f"{path}[{index}]") for index, item in enumerate(_list(value, path=path)))


def _validate_evidence_shape(
    evidence: BenchmarkEvidence,
    *,
    path: str,
    schema_version: int,
) -> None:
    """Validate alignment and derived counts for one evidence record."""
    expected = evidence.provided_run_count
    aligned = (evidence.rounds, evidence.iterations, evidence.sample_counts)
    if any(len(values) != expected for values in aligned):
        raise BenchmarkJsonError(f"Evidence run-aligned fields have inconsistent lengths at {path}.")
    if evidence.sample_count != sum(evidence.sample_counts):
        raise BenchmarkJsonError(f"Evidence sample_count is inconsistent at {path}.")
    if evidence.adequate != (not evidence.issues):
        raise BenchmarkJsonError(f"Evidence adequacy is inconsistent at {path}.")
    if schema_version >= 2:
        diagnostics = (
            evidence.run_iqrs,
            evidence.run_coefficients_of_variation,
            evidence.run_outlier_counts,
            evidence.run_outlier_fractions,
        )
        if any(len(values) not in {0, expected} for values in diagnostics):
            raise BenchmarkJsonError(f"Per-run evidence diagnostics have inconsistent lengths at {path}.")


def _validate_cell_inference(
    cell: BenchmarkComparison,
    *,
    inference_policy: InferencePolicy,
    environment_compatible: bool,
    design: ComparisonDesign,
    expected_pair_count: int | None,
    expected_strata_count: int | None,
) -> None:
    """Validate one cell's inference against its policy and classification."""
    inference = cell.inference
    if inference_policy.method == "legacy_consistency":
        if inference is not None:
            raise ValueError("Legacy-consistency comparisons must not include formal inference.")
        return
    if cell.status != "matched" or not environment_compatible:
        if inference is not None:
            raise ValueError("Non-comparable cells must not include formal inference.")
        return
    if inference is None:
        raise ValueError("Matched inferential comparisons require a BenchmarkInference result.")
    if inference.design != design:
        raise ValueError("Reported inference design does not match the report comparison design.")
    if design == "independent" and inference.pair_count is not None:
        raise ValueError("Independent report inference must not define pair_count.")
    if design == "paired" and inference.pair_count != expected_pair_count:
        raise ValueError("Reported inference pair_count does not match the paired report sources.")
    if design == "paired" and expected_strata_count is not None and inference.strata_count != expected_strata_count:
        raise ValueError("Reported inference strata_count does not match paired AB/BA collection provenance.")
    if not math.isclose(
        inference.confidence_level,
        inference_policy.confidence_level,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError("Reported inference confidence level does not match its policy.")
    if inference.multiplicity != inference_policy.multiplicity:
        raise ValueError("Reported inference multiplicity does not match its policy.")
    if inference.resamples != inference_policy.resamples:
        raise ValueError("Reported inference resamples do not match its policy.")
    expected_seed_payload = "\0".join(
        (
            str(inference_policy.random_seed),
            cell.implementation_name,
            cell.case_name,
            cell.metric_name,
        )
    ).encode()
    expected_seed = int.from_bytes(sha256(expected_seed_payload).digest()[:8], "big", signed=False)
    if inference.random_seed != expected_seed:
        raise ValueError("Reported inference random seed is inconsistent with its policy and cell key.")
    expected_adjusted = inference_policy.confidence_level
    if inference_policy.multiplicity == "bonferroni":
        expected_adjusted = 1.0 - (1.0 - inference_policy.confidence_level) / inference.family_size
    if not math.isclose(
        inference.adjusted_confidence_level,
        expected_adjusted,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError("Reported adjusted confidence level is inconsistent with multiplicity.")
    if inference.estimate_percent is not None and (
        cell.improvement_percent is None
        or not math.isclose(
            inference.estimate_percent,
            cell.improvement_percent,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Reported inference estimate does not match the cell improvement estimate.")
    expected_classification = _inference_classification(
        inference,
        threshold_percent=cell.threshold_percent,
    )
    if cell.regression != expected_classification:
        raise ValueError("Reported classification is inconsistent with its confidence interval.")


def _validate_cell_precision(
    cell: BenchmarkComparison,
    *,
    precision_policy: PrecisionPolicy,
    inference_policy: InferencePolicy,
    evidence_policy: EvidencePolicy,
    design: ComparisonDesign,
    expected_pair_count: int | None,
    expected_strata_count: int | None,
    expected_pair_count_multiple: int | None,
) -> None:
    """Validate one cell's informational precision plan against report policy."""
    plan = cell.precision
    target = precision_policy.target_half_width_percent
    if design == "independent":
        if plan is not None:
            raise ValueError("Independent report cells must not include paired precision plans.")
        return
    if target is None:
        if plan is not None:
            raise ValueError("Precision-disabled reports must not include per-cell plans.")
        return
    if cell.status != "matched":
        if plan is not None:
            raise ValueError("Non-matched cells must not include precision plans.")
        return
    if plan is None:
        raise ValueError("Matched cells require a precision plan when precision planning is enabled.")
    if not math.isclose(
        plan.target_half_width_percent,
        target,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError("Precision-plan target does not match its policy.")
    if plan.pilot_pairs != expected_pair_count:
        raise ValueError("Precision-plan pilot pair count does not match the paired report sources.")
    if plan.minimum_pairs != evidence_policy.minimum_runs:
        raise ValueError("Precision-plan minimum pair count does not match the report evidence policy.")
    if expected_pair_count_multiple is not None and plan.pair_count_multiple != expected_pair_count_multiple:
        raise ValueError("Precision-plan pair-count multiple does not match paired collection provenance.")
    if plan.pair_count_multiple % 2 != 0:
        raise ValueError("Precision-plan pair-count multiple must preserve balanced AB/BA allocation.")
    if expected_strata_count is not None and plan.strata_count != expected_strata_count:
        raise ValueError("Precision-plan strata_count does not match paired AB/BA collection provenance.")
    if not math.isclose(
        plan.confidence_level,
        inference_policy.confidence_level,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError("Precision-plan confidence level does not match inference policy.")
    if plan.multiplicity != inference_policy.multiplicity:
        raise ValueError("Precision-plan multiplicity does not match inference policy.")
    expected_adjusted = inference_policy.confidence_level
    if inference_policy.multiplicity == "bonferroni":
        expected_adjusted = 1.0 - (1.0 - inference_policy.confidence_level) / plan.family_size
    if not math.isclose(
        plan.adjusted_confidence_level,
        expected_adjusted,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError("Precision-plan adjusted confidence is inconsistent with multiplicity.")
    inference = cell.inference
    if inference is not None and (
        plan.family_size != inference.family_size
        or plan.strata_count != inference.strata_count
        or not math.isclose(
            plan.adjusted_confidence_level,
            inference.adjusted_confidence_level,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Precision-plan family settings do not match cell inference.")
    result_fields = (
        plan.critical_value,
        plan.unconstrained_required_pairs,
        plan.required_pairs,
        plan.additional_pairs,
    )
    if plan.issues and any(value is not None for value in result_fields):
        raise ValueError("Failed precision plans must not include pair-count results.")
    if not plan.issues and (not plan.adequate or plan.pilot_log_ratio_standard_deviation is None):
        raise ValueError("Successful precision plans require variability and complete pair-count results.")
    if plan.required_pairs is not None and plan.required_pairs % plan.pair_count_multiple != 0:
        raise ValueError("Precision-plan required pair count must be divisible by its design multiple.")


def _inference_classification(
    inference: BenchmarkInference,
    *,
    threshold_percent: float,
) -> RegressionClassification:
    """Return the interval-based classification represented in a v2 report."""
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


def _expected_threshold_field(cell: BenchmarkComparison, *, scope: RegressionThresholdScope) -> str:
    """Return the expected provenance field for one cell and scope."""
    if scope == "cell":
        return f"regression.by_cell.{cell.implementation_name}.{cell.case_name}.{cell.metric_name}"
    if scope == "case":
        return f"regression.by_case.{cell.case_name}"
    if scope == "implementation":
        return f"regression.by_implementation.{cell.implementation_name}"
    if scope == "metric":
        return f"regression.by_metric.{cell.metric_name}"
    return "regression.default_threshold_percent"


def _validate_threshold_provenance(
    cell: BenchmarkComparison,
    threshold: BenchmarkThresholdProvenance,
    *,
    regression_policy: RegressionPolicy,
    policy_provenance: BenchmarkPolicyProvenance,
) -> None:
    """Validate one cell's threshold against policy and provenance."""
    expected_scope = regression_policy.threshold_scope_for(
        cell.implementation_name,
        cell.case_name,
        cell.metric_name,
    )
    if threshold.scope != expected_scope:
        raise BenchmarkJsonError("Threshold provenance scope does not match the effective regression policy.")
    expected_threshold = regression_policy.threshold_for(
        cell.implementation_name,
        cell.case_name,
        cell.metric_name,
    )
    if not math.isclose(cell.threshold_percent, expected_threshold, rel_tol=1e-12, abs_tol=1e-12):
        raise BenchmarkJsonError("Reported threshold does not match the effective regression policy.")
    if threshold.field in policy_provenance.cli_overrides:
        expected_origin: ThresholdOrigin = "cli"
    elif threshold.field in policy_provenance.configured_fields:
        expected_origin = "configuration"
    else:
        expected_origin = "built_in"
    if threshold.origin != expected_origin:
        raise BenchmarkJsonError("Threshold provenance origin does not match policy provenance.")


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    """Return a string-keyed mapping or raise a report schema error."""
    if not isinstance(value, Mapping):
        raise BenchmarkJsonError(f"Expected mapping at {path}, got {type(value).__name__}.")
    if any(not isinstance(key, str) for key in value):
        raise BenchmarkJsonError(f"Expected string keys at {path}.")
    return cast(Mapping[str, object], value)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], *, path: str) -> None:
    """Require the exact object keys declared by the report schema."""
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown {', '.join(unknown)}")
        raise BenchmarkJsonError(f"Invalid keys at {path}: {'; '.join(parts)}.")


def _list(value: object, *, path: str) -> list[object]:
    """Return a list or raise a report schema error."""
    if not isinstance(value, list):
        raise BenchmarkJsonError(f"Expected list at {path}, got {type(value).__name__}.")
    return value


def _string(value: object, *, path: str) -> str:
    """Return a string or raise a report schema error."""
    if not isinstance(value, str):
        raise BenchmarkJsonError(f"Expected string at {path}, got {type(value).__name__}.")
    return value


def _non_empty_string(value: object, *, path: str) -> str:
    """Return a non-empty string or raise a report schema error."""
    result = _string(value, path=path)
    if not result:
        raise BenchmarkJsonError(f"Expected non-empty string at {path}.")
    return result


def _optional_string(value: object, *, path: str) -> str | None:
    """Return an optional non-empty string."""
    if value is None:
        return None
    return _non_empty_string(value, path=path)


def _string_list(value: object, *, path: str, non_empty: bool = False) -> list[str]:
    """Return a list of strings."""
    payload = _list(value, path=path)
    if non_empty and not payload:
        raise BenchmarkJsonError(f"Expected non-empty list at {path}.")
    return [_non_empty_string(item, path=f"{path}[{index}]") for index, item in enumerate(payload)]


def _integer(value: object, *, path: str) -> int:
    """Return an integer or raise a report schema error."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchmarkJsonError(f"Expected integer at {path}, got {type(value).__name__}.")
    return value


def _optional_integer(value: object, *, path: str) -> int | None:
    """Return an optional integer."""
    if value is None:
        return None
    return _integer(value, path=path)


def _positive_integer(value: object, *, path: str) -> int:
    """Return a positive integer."""
    result = _integer(value, path=path)
    if result <= 0:
        raise BenchmarkJsonError(f"Expected positive integer at {path}.")
    return result


def _non_negative_integer(value: object, *, path: str) -> int:
    """Return a non-negative integer."""
    result = _integer(value, path=path)
    if result < 0:
        raise BenchmarkJsonError(f"Expected non-negative integer at {path}.")
    return result


def _number(value: object, *, path: str) -> float:
    """Return a finite number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BenchmarkJsonError(f"Expected finite number at {path}.")
    result = float(value)
    if not math.isfinite(result):
        raise BenchmarkJsonError(f"Expected finite number at {path}.")
    return result


def _optional_number(value: object, *, path: str) -> float | None:
    """Return an optional finite number."""
    if value is None:
        return None
    return _number(value, path=path)


def _non_negative_number(value: object, *, path: str) -> float:
    """Return a finite non-negative number."""
    result = _number(value, path=path)
    if result < 0.0:
        raise BenchmarkJsonError(f"Expected non-negative number at {path}.")
    return result


def _boolean(value: object, *, path: str) -> bool:
    """Return a boolean."""
    if not isinstance(value, bool):
        raise BenchmarkJsonError(f"Expected boolean at {path}, got {type(value).__name__}.")
    return value


def _metric(value: object, *, path: str) -> MetricName:
    """Return a supported metric name."""
    metric = _non_empty_string(value, path=path)
    if metric not in KNOWN_METRICS:
        raise BenchmarkJsonError(f"Unsupported metric at {path}: {metric!r}.")
    return cast(MetricName, metric)


def _enum_string(value: object, allowed: set[str], *, path: str) -> str:
    """Return a string from an allowed set."""
    result = _string(value, path=path)
    if result not in allowed:
        raise BenchmarkJsonError(f"Unsupported value at {path}: {result!r}.")
    return result


def _numeric_mapping(value: object, *, path: str) -> dict[str, float]:
    """Return a mapping of non-empty selectors to finite numbers."""
    payload = _mapping(value, path=path)
    return {
        _non_empty_string(key, path=f"{path}.key"): _number(item, path=f"{path}.{key}") for key, item in payload.items()
    }


def _json_value(value: object, *, path: str) -> JsonValue:
    """Validate and return one strict JSON-safe value."""
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BenchmarkJsonError(f"Expected strict JSON value at {path}.")
        return value
    if isinstance(value, list | tuple):
        return [_json_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise BenchmarkJsonError(f"Expected string mapping keys at {path}.")
            result[key] = _json_value(item, path=f"{path}.{key}")
        return result
    raise BenchmarkJsonError(f"Expected strict JSON value at {path}.")
