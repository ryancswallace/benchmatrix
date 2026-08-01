"""Collect, persist, and load repeated pytest-benchmark runs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess  # nosec B404
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TextIO, TypeAlias, cast

from ._collection_design import (
    ORDER_INDEX_ENV,
    ORDER_SEED_ENV,
    balanced_cell_order,
)
from ._collection_design import balanced_order_cycle_length as balanced_order_cycle_length
from ._collection_design import balanced_order_supercycle_length as balanced_order_supercycle_length
from ._schema import (
    KNOWN_METRICS,
    PAIRED_RUN_GROUP_KIND,
    PAIRED_RUN_GROUP_SCHEMA_READ_VERSIONS,
    PAIRED_RUN_GROUP_SCHEMA_VERSION,
    PRODUCER,
    RUN_GROUP_KIND,
    RUN_GROUP_SCHEMA_READ_VERSIONS,
    RUN_GROUP_SCHEMA_VERSION,
    MetricName,
)
from .bench_compare import (
    BenchmarkRunComparison,
    EvidencePolicy,
    InferencePolicy,
    PrecisionPolicy,
    RegressionPolicy,
    RunCompatibilityPolicy,
    compare_benchmark_run_groups,
    compare_paired_benchmark_run_groups,
)
from .bench_results import BenchmarkRun, load_benchmark_run
from .exceptions import BenchmarkCollectionError, BenchmarkJsonError

CollectionRunStatus: TypeAlias = Literal["succeeded", "failed"]
BenchmarkCell: TypeAlias = tuple[str, str, MetricName]
PairedVariant: TypeAlias = Literal["baseline", "candidate"]
PairedOrder: TypeAlias = Literal["AB", "BA"]

RUN_GROUP_MANIFEST = "benchmatrix-manifest.json"
_DEFAULT_MINIMUM_PAIRS = 5
_PROVISIONAL_AUTOMATIC_PAIRS = 6

_COLLECTION_COMMAND_STDOUT: ContextVar[TextIO | None] = ContextVar(
    "benchmatrix_collection_command_stdout",
    default=None,
)

_ROOT_KEYS = frozenset(
    {
        "producer",
        "kind",
        "schema_version",
        "created_at",
        "command",
        "cwd",
        "commit",
        "environment_fingerprint",
        "requested_runs",
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
_CELL_KEYS = frozenset({"implementation_name", "case_name", "metric_name"})

_PAIRED_ROOT_KEYS = frozenset(
    {
        "producer",
        "kind",
        "schema_version",
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
        "automatic_pairs",
        "random_seed",
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


@contextmanager
def _redirect_collection_command_stdout(stream: TextIO) -> Iterator[None]:
    """Route child stdout through a Python text stream for CLI JSON mode."""
    token = _COLLECTION_COMMAND_STDOUT.set(stream)
    try:
        yield
    finally:
        _COLLECTION_COMMAND_STDOUT.reset(token)


@contextmanager
def _collection_order_environment(*, random_seed: int, order_index: int) -> Iterator[None]:
    """Temporarily expose one balanced-order schedule row to the harness."""
    previous_seed = os.environ.get(ORDER_SEED_ENV)
    previous_index = os.environ.get(ORDER_INDEX_ENV)
    os.environ[ORDER_SEED_ENV] = str(random_seed)
    os.environ[ORDER_INDEX_ENV] = str(order_index)
    try:
        yield
    finally:
        if previous_seed is None:
            os.environ.pop(ORDER_SEED_ENV, None)
        else:
            os.environ[ORDER_SEED_ENV] = previous_seed
        if previous_index is None:
            os.environ.pop(ORDER_INDEX_ENV, None)
        else:
            os.environ[ORDER_INDEX_ENV] = previous_index


@dataclass(frozen=True, slots=True)
class BenchmarkPairSchedule:
    """One deterministic baseline/candidate collection block.

    Attributes:
        pair_index: One-based target-pair index.
        pair_order: ``AB`` for baseline first or ``BA`` for candidate first.
        cell_order_index: One-based balanced matrix-order row used by both
            variants in the block.
    """

    pair_index: int
    pair_order: PairedOrder
    cell_order_index: int

    def __post_init__(self) -> None:
        """Validate a scheduled pair."""
        if isinstance(self.pair_index, bool) or not isinstance(self.pair_index, int) or self.pair_index <= 0:
            raise ValueError("BenchmarkPairSchedule.pair_index must be a positive integer.")
        if self.pair_order not in {"AB", "BA"}:
            raise ValueError(f"Unsupported paired collection order: {self.pair_order!r}.")
        if (
            isinstance(self.cell_order_index, bool)
            or not isinstance(self.cell_order_index, int)
            or self.cell_order_index <= 0
        ):
            raise ValueError("BenchmarkPairSchedule.cell_order_index must be a positive integer.")

    @property
    def variants(self) -> tuple[PairedVariant, PairedVariant]:
        """Return variants in their scheduled execution order."""
        return ("baseline", "candidate") if self.pair_order == "AB" else ("candidate", "baseline")


def make_paired_ab_ba_schedule(
    pair_count: int,
    *,
    random_seed: int = 0,
    cell_count: int | None = None,
) -> tuple[BenchmarkPairSchedule, ...]:
    """Return a deterministic joint AB/BA and balanced-row block schedule.

    The seed chooses whether the first block is AB or BA. Later blocks
    alternate, so the counts differ by at most one for odd ``pair_count``.
    Both members of a block use the same balanced cell-order row. When the
    matrix size is known, each row occurs once with each orientation over a
    complete joint supercycle. Omitting ``cell_count`` provides an
    orientation-only, single-row schedule for compatibility and collection
    before the matrix has been learned.

    Args:
        pair_count: Number of target baseline/candidate pairs.
        random_seed: Non-negative deterministic schedule seed.
        cell_count: Positive number of cells in the benchmark matrix, when
            known.

    Returns:
        One schedule entry per requested pair.
    """
    if isinstance(pair_count, bool) or not isinstance(pair_count, int) or pair_count <= 0:
        raise ValueError("pair_count must be a positive integer.")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise TypeError("random_seed must be an integer.")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative.")
    if cell_count is not None:
        if isinstance(cell_count, bool) or not isinstance(cell_count, int):
            raise TypeError("cell_count must be an integer or None.")
        if cell_count <= 0:
            raise ValueError("cell_count must be positive when provided.")

    seed_digest = hashlib.sha256(str(random_seed).encode()).digest()
    starts_with_ba = bool(seed_digest[0] & 1)
    row_cycle_length = balanced_order_cycle_length(cell_count) if cell_count is not None else 1
    return tuple(
        BenchmarkPairSchedule(
            pair_index=pair_index,
            pair_order=("BA" if starts_with_ba == (pair_index % 2 == 1) else "AB"),
            cell_order_index=(pair_index - 1) // 2 % row_cycle_length + 1,
        )
        for pair_index in range(1, pair_count + 1)
    )


def _automatic_pair_target(cell_count: int) -> int:
    """Return the smallest complete joint supercycle meeting evidence defaults."""
    supercycle = balanced_order_supercycle_length(cell_count)
    return ((_DEFAULT_MINIMUM_PAIRS + supercycle - 1) // supercycle) * supercycle


@dataclass(frozen=True, slots=True)
class BenchmarkRunRecord:
    """One attempted run recorded in a collection manifest.

    Attributes:
        index: One-based attempt number.
        status: Whether the command produced accepted benchmark evidence.
        path: Benchmark JSON path for the attempt.
        returncode: Child-process return code, when the command started.
        started_at: UTC ISO 8601 timestamp for the attempt.
        duration_seconds: Child command and validation duration.
        error: Failure reason for an unsuccessful attempt.
        warnings: Non-blocking environment diagnostics.
        commit: Source commit reported by pytest-benchmark, when present.
        environment_fingerprint: SHA-256 fingerprint of environment metadata,
            when a valid run was produced.
    """

    index: int
    status: CollectionRunStatus
    path: Path
    returncode: int | None
    started_at: str
    duration_seconds: float
    error: str | None = None
    warnings: tuple[str, ...] = ()
    commit: str | None = None
    environment_fingerprint: str | None = None

    def __post_init__(self) -> None:
        """Normalize and validate an attempted-run record."""
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index <= 0:
            raise ValueError("BenchmarkRunRecord.index must be a positive integer.")
        if self.status not in {"succeeded", "failed"}:
            raise ValueError(f"Unsupported benchmark collection status: {self.status!r}.")
        if self.returncode is not None and (isinstance(self.returncode, bool) or not isinstance(self.returncode, int)):
            raise TypeError("BenchmarkRunRecord.returncode must be an integer or None.")
        _validate_timestamp(self.started_at, field_name="BenchmarkRunRecord.started_at")
        if (
            isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, int | float)
            or self.duration_seconds < 0.0
        ):
            raise ValueError("BenchmarkRunRecord.duration_seconds must be a non-negative number.")

        warnings = tuple(self.warnings)
        if any(not isinstance(warning, str) or not warning for warning in warnings):
            raise ValueError("BenchmarkRunRecord.warnings must contain non-empty strings.")
        if self.commit is not None and (not isinstance(self.commit, str) or not self.commit):
            raise ValueError("BenchmarkRunRecord.commit must be a non-empty string or None.")
        if self.environment_fingerprint is not None:
            _validate_fingerprint(
                self.environment_fingerprint,
                field_name="BenchmarkRunRecord.environment_fingerprint",
            )

        if self.status == "succeeded":
            if self.returncode != 0 or self.error is not None:
                raise ValueError("Successful benchmark records require returncode 0 and no error.")
            if self.environment_fingerprint is None:
                raise ValueError("Successful benchmark records require an environment fingerprint.")
        elif not isinstance(self.error, str) or not self.error:
            raise ValueError("Failed benchmark records require a non-empty error.")

        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "duration_seconds", float(self.duration_seconds))
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True, slots=True)
class BenchmarkPairedRunRecord:
    """One command attempt within a scheduled paired collection block.

    ``pair_index`` identifies the target pair. ``block_attempt`` identifies an
    adjacent two-command attempt at that pair; a block contributes inference
    evidence only when both variants succeed in the same block attempt.

    Attributes:
        index: One-based command-attempt index across the collection.
        pair_index: One-based target-pair index.
        block_attempt: One-based atomic-block attempt for that target pair.
        variant: Baseline or candidate member.
        pair_order: Scheduled AB or BA orientation.
        order_position: One for the first command in the block, otherwise two.
        cell_order_index: Balanced cell-order row shared by the pair.
        status: Whether this command produced accepted benchmark evidence.
        path: Benchmark JSON path for the command attempt.
        returncode: Child-process return code, when the command started.
        started_at: UTC ISO 8601 timestamp for the command attempt.
        duration_seconds: Child command and validation duration.
        error: Failure reason for an unsuccessful command attempt.
        warnings: Non-blocking environment diagnostics.
        commit: Source commit reported by pytest-benchmark, when present.
        environment_fingerprint: SHA-256 environment fingerprint, when valid.
    """

    index: int
    pair_index: int
    block_attempt: int
    variant: PairedVariant
    pair_order: PairedOrder
    order_position: int
    cell_order_index: int
    status: CollectionRunStatus
    path: Path
    returncode: int | None
    started_at: str
    duration_seconds: float
    error: str | None = None
    warnings: tuple[str, ...] = ()
    commit: str | None = None
    environment_fingerprint: str | None = None

    def __post_init__(self) -> None:
        """Normalize and validate one paired command record."""
        for name, value in (
            ("index", self.index),
            ("pair_index", self.pair_index),
            ("block_attempt", self.block_attempt),
            ("cell_order_index", self.cell_order_index),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"BenchmarkPairedRunRecord.{name} must be a positive integer.")
        if self.variant not in {"baseline", "candidate"}:
            raise ValueError(f"Unsupported paired collection variant: {self.variant!r}.")
        if self.pair_order not in {"AB", "BA"}:
            raise ValueError(f"Unsupported paired collection order: {self.pair_order!r}.")
        if self.order_position != _variant_order_position(self.variant, self.pair_order):
            raise ValueError("BenchmarkPairedRunRecord.order_position is inconsistent with variant and pair_order.")
        if self.status not in {"succeeded", "failed"}:
            raise ValueError(f"Unsupported benchmark collection status: {self.status!r}.")
        if self.returncode is not None and (isinstance(self.returncode, bool) or not isinstance(self.returncode, int)):
            raise TypeError("BenchmarkPairedRunRecord.returncode must be an integer or None.")
        _validate_timestamp(self.started_at, field_name="BenchmarkPairedRunRecord.started_at")
        if (
            isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, int | float)
            or self.duration_seconds < 0.0
        ):
            raise ValueError("BenchmarkPairedRunRecord.duration_seconds must be a non-negative number.")

        warnings = tuple(self.warnings)
        if any(not isinstance(warning, str) or not warning for warning in warnings):
            raise ValueError("BenchmarkPairedRunRecord.warnings must contain non-empty strings.")
        if self.commit is not None and (not isinstance(self.commit, str) or not self.commit):
            raise ValueError("BenchmarkPairedRunRecord.commit must be a non-empty string or None.")
        if self.environment_fingerprint is not None:
            _validate_fingerprint(
                self.environment_fingerprint,
                field_name="BenchmarkPairedRunRecord.environment_fingerprint",
            )
        if self.status == "succeeded":
            if self.returncode != 0 or self.error is not None:
                raise ValueError("Successful paired records require returncode 0 and no error.")
            if self.environment_fingerprint is None:
                raise ValueError("Successful paired records require an environment fingerprint.")
        elif not isinstance(self.error, str) or not self.error:
            raise ValueError("Failed paired records require a non-empty error.")

        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "duration_seconds", float(self.duration_seconds))
        object.__setattr__(self, "warnings", warnings)


def _variant_order_position(variant: PairedVariant, pair_order: PairedOrder) -> int:
    """Return a variant's one-based position within an AB/BA block."""
    return 1 if (variant == "baseline") == (pair_order == "AB") else 2


@dataclass(frozen=True, slots=True)
class BenchmarkRunGroup:
    """A manifest-backed collection of repeated benchmark attempts.

    Only successful records appear in ``runs`` and can contribute evidence.
    Failed attempts remain available in ``records`` for lifecycle diagnostics.

    Attributes:
        runs: Successfully parsed benchmark runs in attempt order.
        records: All attempted collection records.
        command: Original pytest command before output-path injection.
        created_at: UTC ISO 8601 collection timestamp.
        cwd: Working directory inherited by the child commands.
        commit: Commit reported by the first successful run, when present.
        environment_fingerprint: Environment fingerprint from the first
            successful run.
        expected_cells: Matrix cells established by the first successful run.
        requested_runs: Number of successful runs requested.
        manifest_path: Source manifest path.
    """

    runs: tuple[BenchmarkRun, ...]
    records: tuple[BenchmarkRunRecord, ...]
    command: tuple[str, ...]
    created_at: str
    cwd: Path
    commit: str | None
    environment_fingerprint: str | None
    expected_cells: tuple[BenchmarkCell, ...]
    requested_runs: int
    manifest_path: Path

    def __post_init__(self) -> None:
        """Normalize containers and validate collection invariants."""
        runs = tuple(self.runs)
        records = tuple(self.records)
        command = tuple(self.command)
        expected_cells = tuple(self.expected_cells)

        if not command or any(not isinstance(argument, str) or not argument for argument in command):
            raise ValueError("BenchmarkRunGroup.command must contain non-empty strings.")
        _validate_timestamp(self.created_at, field_name="BenchmarkRunGroup.created_at")
        if self.commit is not None and (not isinstance(self.commit, str) or not self.commit):
            raise ValueError("BenchmarkRunGroup.commit must be a non-empty string or None.")
        if self.environment_fingerprint is not None:
            _validate_fingerprint(
                self.environment_fingerprint,
                field_name="BenchmarkRunGroup.environment_fingerprint",
            )
        if isinstance(self.requested_runs, bool) or not isinstance(self.requested_runs, int):
            raise TypeError("BenchmarkRunGroup.requested_runs must be an integer.")
        if self.requested_runs <= 0:
            raise ValueError("BenchmarkRunGroup.requested_runs must be positive.")
        if tuple(record.index for record in records) != tuple(range(1, len(records) + 1)):
            raise ValueError("BenchmarkRunGroup record indexes must be contiguous and one-based.")
        if len(runs) != sum(record.status == "succeeded" for record in records):
            raise ValueError("BenchmarkRunGroup runs must align with successful records.")
        if len(runs) > self.requested_runs:
            raise ValueError("BenchmarkRunGroup has more successful runs than requested.")
        if len(set(expected_cells)) != len(expected_cells):
            raise ValueError("BenchmarkRunGroup.expected_cells must not contain duplicates.")
        for cell in expected_cells:
            _validate_cell(cell)
        if runs and not expected_cells:
            raise ValueError("BenchmarkRunGroup with successful runs requires expected cells.")
        if not runs and (self.commit is not None or self.environment_fingerprint is not None or expected_cells):
            raise ValueError("BenchmarkRunGroup without successful runs cannot define an anchor.")
        for run in runs:
            if not isinstance(run, BenchmarkRun):
                raise TypeError("BenchmarkRunGroup.runs must contain BenchmarkRun values.")
            if _run_cells(run) != expected_cells:
                raise ValueError("BenchmarkRunGroup run matrix does not match expected_cells.")

        object.__setattr__(self, "runs", runs)
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "cwd", Path(self.cwd))
        object.__setattr__(self, "expected_cells", expected_cells)
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))

    @property
    def successful_count(self) -> int:
        """Return the number of accepted benchmark runs."""
        return len(self.runs)

    @property
    def failed_count(self) -> int:
        """Return the number of failed attempts."""
        return sum(record.status == "failed" for record in self.records)

    @property
    def attempted_count(self) -> int:
        """Return the number of completed attempts."""
        return len(self.records)

    @property
    def is_complete(self) -> bool:
        """Return whether the requested successful-run target was reached."""
        return self.successful_count == self.requested_runs

    @property
    def pending_count(self) -> int:
        """Return initial collection slots that have not been attempted."""
        return max(0, self.requested_runs - self.attempted_count)

    @property
    def retry_count(self) -> int:
        """Return attempts appended after the initial collection slots."""
        return max(0, self.attempted_count - self.requested_runs)

    @property
    def remaining_count(self) -> int:
        """Return additional successful runs needed for completeness."""
        return self.requested_runs - self.successful_count

    @property
    def failed_records(self) -> tuple[BenchmarkRunRecord, ...]:
        """Return failed attempts in collection order."""
        return tuple(record for record in self.records if record.status == "failed")

    def compare_to(
        self,
        candidate: BenchmarkRunGroup,
        *,
        compatibility_policy: RunCompatibilityPolicy | None = None,
        regression_policy: RegressionPolicy | None = None,
        evidence_policy: EvidencePolicy | None = None,
        inference_policy: InferencePolicy | None = None,
        precision_policy: PrecisionPolicy | None = None,
    ) -> BenchmarkRunComparison:
        """Compare this repeated baseline collection with a candidate.

        Args:
            candidate: Repeated candidate collection.
            compatibility_policy: Environment checks to apply.
            regression_policy: Thresholds used to classify cell changes.
            evidence_policy: Minimum repeated-run evidence to require.
            inference_policy: Statistical inference and multiplicity controls.
            precision_policy: Optional precision-planning policy. Independent
                groups require its planning mode to remain disabled.

        Returns:
            A matrix-aware repeated-run comparison.

        Raises:
            ValueError: If either collection has no successful runs.
        """
        return compare_benchmark_run_groups(
            self.runs,
            candidate.runs,
            compatibility_policy=compatibility_policy,
            regression_policy=regression_policy,
            evidence_policy=evidence_policy,
            inference_policy=inference_policy,
            precision_policy=precision_policy,
        )


@dataclass(frozen=True, slots=True)
class BenchmarkRunPair:
    """One complete atomic baseline/candidate collection block.

    Attributes:
        pair_index: One-based target-pair index.
        block_attempt: Successful atomic-block attempt for the pair.
        pair_order: AB or BA execution orientation.
        cell_order: Balanced matrix order used by both variants.
        baseline: Baseline benchmark run.
        candidate: Candidate benchmark run.
        baseline_record: Manifest record for ``baseline``.
        candidate_record: Manifest record for ``candidate``.
    """

    pair_index: int
    block_attempt: int
    pair_order: PairedOrder
    cell_order: tuple[BenchmarkCell, ...]
    baseline: BenchmarkRun
    candidate: BenchmarkRun
    baseline_record: BenchmarkPairedRunRecord
    candidate_record: BenchmarkPairedRunRecord

    def __post_init__(self) -> None:
        """Validate the matched-block contract."""
        if self.baseline_record.status != "succeeded" or self.candidate_record.status != "succeeded":
            raise ValueError("BenchmarkRunPair requires two successful records.")
        for record, variant in (
            (self.baseline_record, "baseline"),
            (self.candidate_record, "candidate"),
        ):
            if (
                record.pair_index != self.pair_index
                or record.block_attempt != self.block_attempt
                or record.variant != variant
                or record.pair_order != self.pair_order
            ):
                raise ValueError("BenchmarkRunPair records do not match the pair identity.")
        if _run_cell_order(self.baseline) != self.cell_order or _run_cell_order(self.candidate) != self.cell_order:
            raise ValueError("BenchmarkRunPair runs do not match their scheduled cell order.")


@dataclass(frozen=True, slots=True)
class BenchmarkPairedRunGroup:
    """Manifest-backed paired AB/BA benchmark collection.

    Complete pairs are atomic adjacent block attempts: an orphan success from
    a block whose other command failed is retained in ``records`` and ``runs``
    but excluded from ``complete_pairs`` and statistical inference.
    """

    runs: tuple[BenchmarkRun, ...]
    records: tuple[BenchmarkPairedRunRecord, ...]
    baseline_command: tuple[str, ...]
    candidate_command: tuple[str, ...]
    created_at: str
    baseline_cwd: Path
    candidate_cwd: Path
    baseline_commit: str | None
    candidate_commit: str | None
    baseline_environment_fingerprint: str | None
    candidate_environment_fingerprint: str | None
    expected_cells: tuple[BenchmarkCell, ...]
    requested_pairs: int
    random_seed: int
    manifest_path: Path
    automatic_pairs: bool = False

    def __post_init__(self) -> None:
        """Normalize containers and validate paired collection invariants."""
        runs = tuple(self.runs)
        records = tuple(self.records)
        baseline_command = tuple(self.baseline_command)
        candidate_command = tuple(self.candidate_command)
        expected_cells = tuple(self.expected_cells)
        for name, command in (("baseline_command", baseline_command), ("candidate_command", candidate_command)):
            if not command or any(not isinstance(argument, str) or not argument for argument in command):
                raise ValueError(f"BenchmarkPairedRunGroup.{name} must contain non-empty strings.")
        _validate_timestamp(self.created_at, field_name="BenchmarkPairedRunGroup.created_at")
        if isinstance(self.requested_pairs, bool) or not isinstance(self.requested_pairs, int):
            raise TypeError("BenchmarkPairedRunGroup.requested_pairs must be an integer.")
        if self.requested_pairs <= 0:
            raise ValueError("BenchmarkPairedRunGroup.requested_pairs must be positive.")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise TypeError("BenchmarkPairedRunGroup.random_seed must be an integer.")
        if self.random_seed < 0:
            raise ValueError("BenchmarkPairedRunGroup.random_seed must be non-negative.")
        if not isinstance(self.automatic_pairs, bool):
            raise TypeError("BenchmarkPairedRunGroup.automatic_pairs must be a boolean.")
        if tuple(record.index for record in records) != tuple(range(1, len(records) + 1)):
            raise ValueError("BenchmarkPairedRunGroup record indexes must be contiguous and one-based.")
        if len(runs) != sum(record.status == "succeeded" for record in records):
            raise ValueError("BenchmarkPairedRunGroup runs must align with successful records.")
        if len(set(expected_cells)) != len(expected_cells):
            raise ValueError("BenchmarkPairedRunGroup.expected_cells must not contain duplicates.")
        for cell in expected_cells:
            _validate_cell(cell)
        if runs and not expected_cells:
            raise ValueError("BenchmarkPairedRunGroup with successful runs requires expected cells.")
        _validate_optional_anchor(self.baseline_commit, field="baseline_commit")
        _validate_optional_anchor(self.candidate_commit, field="candidate_commit")
        _validate_optional_fingerprint(
            self.baseline_environment_fingerprint,
            field="BenchmarkPairedRunGroup.baseline_environment_fingerprint",
        )
        _validate_optional_fingerprint(
            self.candidate_environment_fingerprint,
            field="BenchmarkPairedRunGroup.candidate_environment_fingerprint",
        )
        if not runs and (
            expected_cells
            or self.baseline_commit is not None
            or self.candidate_commit is not None
            or self.baseline_environment_fingerprint is not None
            or self.candidate_environment_fingerprint is not None
        ):
            raise ValueError("BenchmarkPairedRunGroup without successful runs cannot define anchors or cells.")

        if self.automatic_pairs:
            automatic_target = (
                _automatic_pair_target(len(expected_cells)) if expected_cells else _PROVISIONAL_AUTOMATIC_PAIRS
            )
            if self.requested_pairs != automatic_target:
                raise ValueError(
                    "BenchmarkPairedRunGroup automatic requested_pairs does not match the learned matrix supercycle."
                )

        schedule = make_paired_ab_ba_schedule(
            self.requested_pairs,
            random_seed=self.random_seed,
            cell_count=len(expected_cells) or None,
        )
        schedule_by_pair = {entry.pair_index: entry for entry in schedule}
        blocks: dict[tuple[int, int], set[PairedVariant]] = {}
        latest_attempt_by_pair: dict[int, int] = {}
        successful_records = tuple(record for record in records if record.status == "succeeded")
        first_seen_pairs: list[int] = []
        seen_pairs: set[int] = set()
        matrix_anchor_seen = False
        for record in records:
            if record.pair_index > self.requested_pairs:
                raise ValueError("BenchmarkPairedRunGroup record pair_index exceeds requested_pairs.")
            if record.pair_index not in seen_pairs:
                if record.pair_index != len(seen_pairs) + 1:
                    raise ValueError("BenchmarkPairedRunGroup first-seen pair indexes must form a one-based prefix.")
                first_seen_pairs.append(record.pair_index)
                seen_pairs.add(record.pair_index)
            if record.pair_index > 1 and not matrix_anchor_seen:
                raise ValueError("BenchmarkPairedRunGroup cannot attempt a later pair before a matrix anchor.")
            scheduled = schedule_by_pair[record.pair_index]
            if record.pair_order != scheduled.pair_order or record.cell_order_index != scheduled.cell_order_index:
                raise ValueError("BenchmarkPairedRunGroup record differs from the deterministic schedule.")
            previous_attempt = latest_attempt_by_pair.get(record.pair_index, record.block_attempt)
            if record.block_attempt < previous_attempt:
                raise ValueError("BenchmarkPairedRunGroup block attempts must be chronological per pair.")
            latest_attempt_by_pair[record.pair_index] = record.block_attempt
            variants = blocks.setdefault((record.pair_index, record.block_attempt), set())
            if record.variant in variants:
                raise ValueError("BenchmarkPairedRunGroup block attempts cannot repeat a variant.")
            variants.add(record.variant)
            matrix_anchor_seen = matrix_anchor_seen or record.status == "succeeded"
        if first_seen_pairs != list(range(1, len(first_seen_pairs) + 1)):
            raise ValueError("BenchmarkPairedRunGroup first-seen pair indexes must form a one-based prefix.")
        if not expected_cells and any(record.pair_index != 1 for record in records):
            raise ValueError("BenchmarkPairedRunGroup cannot contain later pairs before learning the matrix.")
        records_by_block: dict[tuple[int, int], list[BenchmarkPairedRunRecord]] = {}
        for record in records:
            records_by_block.setdefault((record.pair_index, record.block_attempt), []).append(record)
        for (pair_index, _block_attempt), block_records in records_by_block.items():
            scheduled_variants = schedule_by_pair[pair_index].variants
            observed_variants = tuple(record.variant for record in block_records)
            if observed_variants != scheduled_variants[: len(observed_variants)]:
                raise ValueError("BenchmarkPairedRunGroup block records are not in scheduled AB/BA order.")
            if len(block_records) == 2 and block_records[1].index != block_records[0].index + 1:
                raise ValueError("BenchmarkPairedRunGroup block members must be adjacent records.")
            if len(block_records) == 1 and block_records[0].index < len(records):
                following = records[block_records[0].index]
                if following.pair_index != pair_index or following.block_attempt != block_records[0].block_attempt + 1:
                    raise ValueError(
                        "BenchmarkPairedRunGroup a partial block must be followed by a retry of the same pair."
                    )
        for pair_index in range(1, self.requested_pairs + 1):
            attempts = sorted(attempt for pair, attempt in blocks if pair == pair_index)
            if attempts and attempts != list(range(1, attempts[-1] + 1)):
                raise ValueError("BenchmarkPairedRunGroup block attempts must be contiguous per pair.")

        successful_by_block: dict[tuple[int, int], set[PairedVariant]] = {}
        for record in successful_records:
            successful_by_block.setdefault((record.pair_index, record.block_attempt), set()).add(record.variant)
        complete_by_pair: dict[int, int] = {}
        for (pair_index, block_attempt), variants in successful_by_block.items():
            if variants == {"baseline", "candidate"}:
                if pair_index in complete_by_pair:
                    raise ValueError("BenchmarkPairedRunGroup cannot contain two complete blocks for one pair.")
                complete_by_pair[pair_index] = block_attempt
        for pair_index, complete_attempt in complete_by_pair.items():
            if any(pair == pair_index and attempt > complete_attempt for pair, attempt in blocks):
                raise ValueError("BenchmarkPairedRunGroup cannot retry a pair after a complete block.")

        scheduled_orders = {
            pair_index: balanced_cell_order(
                expected_cells,
                order_index=schedule_by_pair[pair_index].cell_order_index,
                random_seed=self.random_seed,
            )
            for pair_index in range(1, self.requested_pairs + 1)
        }
        for run, record in zip(runs, successful_records, strict=True):
            if not isinstance(run, BenchmarkRun):
                raise TypeError("BenchmarkPairedRunGroup.runs must contain BenchmarkRun values.")
            if _run_cells(run) != expected_cells:
                raise ValueError("BenchmarkPairedRunGroup run matrix does not match expected_cells.")
            if _run_cell_order(run) != scheduled_orders[record.pair_index]:
                raise ValueError("BenchmarkPairedRunGroup run does not match its scheduled cell order.")

        _validate_paired_variant_anchors(
            successful_records,
            baseline_commit=self.baseline_commit,
            candidate_commit=self.candidate_commit,
            baseline_fingerprint=self.baseline_environment_fingerprint,
            candidate_fingerprint=self.candidate_environment_fingerprint,
        )

        object.__setattr__(self, "runs", runs)
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "baseline_command", baseline_command)
        object.__setattr__(self, "candidate_command", candidate_command)
        object.__setattr__(self, "baseline_cwd", Path(self.baseline_cwd))
        object.__setattr__(self, "candidate_cwd", Path(self.candidate_cwd))
        object.__setattr__(self, "expected_cells", expected_cells)
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))

    @property
    def successful_count(self) -> int:
        """Return successful commands, including orphan successes."""
        return len(self.runs)

    @property
    def attempted_count(self) -> int:
        """Return the number of completed command attempts."""
        return len(self.records)

    @property
    def failed_count(self) -> int:
        """Return the number of failed command attempts."""
        return sum(record.status == "failed" for record in self.records)

    @property
    def complete_pairs(self) -> tuple[BenchmarkRunPair, ...]:
        """Return complete atomic blocks in deterministic target-pair order."""
        run_by_record = {
            (record.pair_index, record.block_attempt, record.variant): (record, run)
            for record, run in zip(
                (record for record in self.records if record.status == "succeeded"),
                self.runs,
                strict=True,
            )
        }
        pairs: list[BenchmarkRunPair] = []
        for pair_index in range(1, self.requested_pairs + 1):
            attempts = sorted({block_attempt for pair, block_attempt, _variant in run_by_record if pair == pair_index})
            for block_attempt in attempts:
                baseline_item = run_by_record.get((pair_index, block_attempt, "baseline"))
                candidate_item = run_by_record.get((pair_index, block_attempt, "candidate"))
                if baseline_item is None or candidate_item is None:
                    continue
                baseline_record, baseline = baseline_item
                candidate_record, candidate = candidate_item
                pairs.append(
                    BenchmarkRunPair(
                        pair_index=pair_index,
                        block_attempt=block_attempt,
                        pair_order=baseline_record.pair_order,
                        cell_order=balanced_cell_order(
                            self.expected_cells,
                            order_index=baseline_record.cell_order_index,
                            random_seed=self.random_seed,
                        ),
                        baseline=baseline,
                        candidate=candidate,
                        baseline_record=baseline_record,
                        candidate_record=candidate_record,
                    )
                )
                break
        return tuple(pairs)

    @property
    def baseline_runs(self) -> tuple[BenchmarkRun, ...]:
        """Return baseline members of complete pairs in pair order."""
        return tuple(pair.baseline for pair in self.complete_pairs)

    @property
    def candidate_runs(self) -> tuple[BenchmarkRun, ...]:
        """Return candidate members of complete pairs in pair order."""
        return tuple(pair.candidate for pair in self.complete_pairs)

    @property
    def complete_pair_count(self) -> int:
        """Return the number of complete atomic collection blocks."""
        return len(self.complete_pairs)

    @property
    def orphan_success_count(self) -> int:
        """Return successes excluded because their block is incomplete."""
        return self.successful_count - 2 * self.complete_pair_count

    @property
    def is_complete(self) -> bool:
        """Return whether every requested target pair has a complete block."""
        return self.complete_pair_count == self.requested_pairs

    @property
    def order_supercycle_length(self) -> int | None:
        """Return the joint AB/BA-by-row cycle, once the matrix is known."""
        if not self.expected_cells:
            return None
        return balanced_order_supercycle_length(len(self.expected_cells))

    @property
    def is_jointly_balanced(self) -> bool:
        """Return whether the fixed target contains whole joint supercycles."""
        supercycle = self.order_supercycle_length
        return supercycle is not None and self.requested_pairs % supercycle == 0

    @property
    def remaining_pair_count(self) -> int:
        """Return the number of target pairs still lacking a complete block."""
        return self.requested_pairs - self.complete_pair_count

    @property
    def incomplete_pair_indexes(self) -> tuple[int, ...]:
        """Return target-pair indexes without a complete atomic block."""
        complete = {pair.pair_index for pair in self.complete_pairs}
        return tuple(index for index in range(1, self.requested_pairs + 1) if index not in complete)

    def compare(
        self,
        *,
        compatibility_policy: RunCompatibilityPolicy | None = None,
        regression_policy: RegressionPolicy | None = None,
        evidence_policy: EvidencePolicy | None = None,
        inference_policy: InferencePolicy | None = None,
        precision_policy: PrecisionPolicy | None = None,
    ) -> BenchmarkRunComparison:
        """Compare members after every requested atomic block is complete.

        Raises:
            BenchmarkCollectionError: If the fixed paired design is incomplete.
        """
        if not self.is_complete:
            raise BenchmarkCollectionError(
                "Paired collection is incomplete; finish or retry every requested block before inference."
            )
        supercycle = self.order_supercycle_length
        if supercycle is None or self.requested_pairs % supercycle != 0:
            raise BenchmarkCollectionError(
                "Paired collection target is not a whole AB/BA-by-balanced-row supercycle; "
                "collect a jointly balanced fixed design before inference."
            )
        return compare_paired_benchmark_run_groups(
            self.baseline_runs,
            self.candidate_runs,
            pair_strata=tuple(pair.pair_order for pair in self.complete_pairs),
            compatibility_policy=compatibility_policy,
            regression_policy=regression_policy,
            evidence_policy=evidence_policy,
            inference_policy=inference_policy,
            precision_policy=precision_policy,
            precision_pair_count_multiple=supercycle,
        )


def load_benchmark_run_group(path: str | Path) -> BenchmarkRunGroup:
    """Load a repeated-run collection from a manifest or its directory.

    Args:
        path: Collection directory or ``benchmatrix-manifest.json`` path.

    Returns:
        A validated run group. Failed attempts are retained as records but do
        not appear in ``runs``.

    Raises:
        BenchmarkJsonError: If the manifest or a successful run is invalid.
    """
    source = Path(path)
    manifest_path = source / RUN_GROUP_MANIFEST if source.is_dir() else source

    try:
        payload = cast(object, json.loads(manifest_path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise BenchmarkJsonError(f"Could not read benchmark run-group manifest: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkJsonError(f"Invalid JSON in benchmark run-group manifest: {manifest_path}") from exc

    root = _require_mapping(payload, path="manifest")
    _require_exact_keys(root, _ROOT_KEYS, path="manifest")
    if _require_string(root["producer"], path="manifest.producer") != PRODUCER:
        raise BenchmarkJsonError("Unsupported producer in benchmark run-group manifest.")
    if _require_string(root["kind"], path="manifest.kind") != RUN_GROUP_KIND:
        raise BenchmarkJsonError("Unsupported benchmark run-group manifest kind.")
    schema_version = _require_int(root["schema_version"], path="manifest.schema_version")
    if schema_version not in RUN_GROUP_SCHEMA_READ_VERSIONS:
        raise BenchmarkJsonError("Unsupported benchmark run-group manifest schema version.")

    created_at = _require_string(root["created_at"], path="manifest.created_at")
    _validate_manifest_timestamp(created_at, path="manifest.created_at")
    command = tuple(_require_string_list(root["command"], path="manifest.command", non_empty=True))
    cwd = Path(_require_string(root["cwd"], path="manifest.cwd"))
    commit = _require_optional_string(root["commit"], path="manifest.commit")
    fingerprint = _require_optional_string(
        root["environment_fingerprint"],
        path="manifest.environment_fingerprint",
    )
    if fingerprint is not None:
        _validate_manifest_fingerprint(fingerprint, path="manifest.environment_fingerprint")
    requested_runs = _require_positive_int(root["requested_runs"], path="manifest.requested_runs")
    expected_cells = _parse_cells(root["expected_cells"])
    record_payloads = _require_list(root["runs"], path="manifest.runs")

    records: list[BenchmarkRunRecord] = []
    runs: list[BenchmarkRun] = []
    record_paths: set[Path] = set()
    for position, record_payload in enumerate(record_payloads):
        record_path = f"manifest.runs[{position}]"
        record_mapping = _require_mapping(record_payload, path=record_path)
        _require_exact_keys(record_mapping, _RECORD_KEYS, path=record_path)
        record = _parse_record(record_mapping, manifest_path=manifest_path, path=record_path)
        canonical_record_path = record.path.resolve()
        if canonical_record_path in record_paths:
            raise BenchmarkJsonError("Manifest run paths must be unique.")
        record_paths.add(canonical_record_path)
        records.append(record)
        if record.status == "succeeded":
            run = load_benchmark_run(record.path)
            _validate_loaded_run(
                run,
                record=record,
                expected_cells=expected_cells,
                anchor_commit=commit,
                anchor_fingerprint=fingerprint,
            )
            runs.append(run)

    successful_records = tuple(record for record in records if record.status == "succeeded")
    if schema_version == 1 and len(records) > requested_runs:
        raise BenchmarkJsonError("Version 1 run-group manifests cannot contain retry attempts.")
    if successful_records and successful_records[0].environment_fingerprint != fingerprint:
        raise BenchmarkJsonError("First successful run environment fingerprint does not match the manifest anchor.")
    if runs:
        compatibility = compare_benchmark_run_groups(
            (runs[0],),
            tuple(runs[1:]) or (runs[0],),
            compatibility_policy=RunCompatibilityPolicy(mode="permissive"),
            evidence_policy=EvidencePolicy(minimum_runs=1, minimum_samples_per_run=0),
            inference_policy=InferencePolicy(method="legacy_consistency"),
        ).compatibility
        if compatibility.blocking:
            fields = ", ".join(finding.field for finding in compatibility.blocking)
            raise BenchmarkJsonError(f"Manifest contains incompatible successful environments: {fields}.")

    try:
        return BenchmarkRunGroup(
            runs=tuple(runs),
            records=tuple(records),
            command=command,
            created_at=created_at,
            cwd=cwd,
            commit=commit,
            environment_fingerprint=fingerprint,
            expected_cells=expected_cells,
            requested_runs=requested_runs,
            manifest_path=manifest_path,
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid benchmark run-group manifest: {exc}") from exc


def load_paired_benchmark_run_group(path: str | Path) -> BenchmarkPairedRunGroup:
    """Load and validate a paired AB/BA collection manifest.

    Args:
        path: Collection directory or ``benchmatrix-manifest.json`` path.

    Returns:
        A paired collection whose complete pairs contain only atomic blocks in
        which both scheduled commands succeeded.

    Raises:
        BenchmarkJsonError: If the manifest or a successful run is invalid.
    """
    source = Path(path)
    manifest_path = source / RUN_GROUP_MANIFEST if source.is_dir() else source
    try:
        payload = cast(object, json.loads(manifest_path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise BenchmarkJsonError(f"Could not read paired benchmark manifest: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkJsonError(f"Invalid JSON in paired benchmark manifest: {manifest_path}") from exc

    root = _require_mapping(payload, path="manifest")
    _require_exact_keys(root, _PAIRED_ROOT_KEYS, path="manifest")
    if _require_string(root["producer"], path="manifest.producer") != PRODUCER:
        raise BenchmarkJsonError("Unsupported producer in paired benchmark manifest.")
    if _require_string(root["kind"], path="manifest.kind") != PAIRED_RUN_GROUP_KIND:
        raise BenchmarkJsonError("Unsupported paired benchmark manifest kind.")
    schema_version = _require_int(root["schema_version"], path="manifest.schema_version")
    if schema_version not in PAIRED_RUN_GROUP_SCHEMA_READ_VERSIONS:
        raise BenchmarkJsonError("Unsupported paired benchmark manifest schema version.")

    created_at = _require_string(root["created_at"], path="manifest.created_at")
    _validate_manifest_timestamp(created_at, path="manifest.created_at")
    baseline_command = tuple(
        _require_string_list(root["baseline_command"], path="manifest.baseline_command", non_empty=True)
    )
    candidate_command = tuple(
        _require_string_list(root["candidate_command"], path="manifest.candidate_command", non_empty=True)
    )
    baseline_cwd = Path(_require_non_empty_string(root["baseline_cwd"], path="manifest.baseline_cwd"))
    candidate_cwd = Path(_require_non_empty_string(root["candidate_cwd"], path="manifest.candidate_cwd"))
    baseline_commit = _require_optional_string(root["baseline_commit"], path="manifest.baseline_commit")
    candidate_commit = _require_optional_string(root["candidate_commit"], path="manifest.candidate_commit")
    baseline_fingerprint = _parse_optional_manifest_fingerprint(
        root["baseline_environment_fingerprint"],
        path="manifest.baseline_environment_fingerprint",
    )
    candidate_fingerprint = _parse_optional_manifest_fingerprint(
        root["candidate_environment_fingerprint"],
        path="manifest.candidate_environment_fingerprint",
    )
    requested_pairs = _require_positive_int(root["requested_pairs"], path="manifest.requested_pairs")
    automatic_pairs_value = root["automatic_pairs"]
    if not isinstance(automatic_pairs_value, bool):
        raise BenchmarkJsonError("Expected boolean at manifest.automatic_pairs.")
    random_seed = _require_non_negative_int(root["random_seed"], path="manifest.random_seed")
    expected_cells = _parse_cells(root["expected_cells"])

    records: list[BenchmarkPairedRunRecord] = []
    runs: list[BenchmarkRun] = []
    record_paths: set[Path] = set()
    for position, record_payload in enumerate(_require_list(root["runs"], path="manifest.runs")):
        record_path = f"manifest.runs[{position}]"
        record_mapping = _require_mapping(record_payload, path=record_path)
        _require_exact_keys(record_mapping, _PAIRED_RECORD_KEYS, path=record_path)
        record = _parse_paired_record(record_mapping, manifest_path=manifest_path, path=record_path)
        canonical_record_path = record.path.resolve()
        if canonical_record_path in record_paths:
            raise BenchmarkJsonError("Paired manifest run paths must be unique.")
        record_paths.add(canonical_record_path)
        records.append(record)
        if record.status == "succeeded":
            run = load_benchmark_run(record.path)
            _validate_loaded_paired_run(
                run,
                record=record,
                expected_cells=expected_cells,
                random_seed=random_seed,
            )
            runs.append(run)

    if runs:
        compatibility = compare_benchmark_run_groups(
            (runs[0],),
            tuple(runs[1:]) or (runs[0],),
            compatibility_policy=RunCompatibilityPolicy(mode="permissive"),
            evidence_policy=EvidencePolicy(minimum_runs=1, minimum_samples_per_run=0),
            inference_policy=InferencePolicy(method="legacy_consistency"),
        ).compatibility
        if compatibility.blocking:
            fields = ", ".join(finding.field for finding in compatibility.blocking)
            raise BenchmarkJsonError(f"Paired manifest contains incompatible successful environments: {fields}.")

    try:
        return BenchmarkPairedRunGroup(
            runs=tuple(runs),
            records=tuple(records),
            baseline_command=baseline_command,
            candidate_command=candidate_command,
            created_at=created_at,
            baseline_cwd=baseline_cwd,
            candidate_cwd=candidate_cwd,
            baseline_commit=baseline_commit,
            candidate_commit=candidate_commit,
            baseline_environment_fingerprint=baseline_fingerprint,
            candidate_environment_fingerprint=candidate_fingerprint,
            expected_cells=expected_cells,
            requested_pairs=requested_pairs,
            random_seed=random_seed,
            manifest_path=manifest_path,
            automatic_pairs=automatic_pairs_value,
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid paired benchmark manifest: {exc}") from exc


def collect_paired_benchmark_runs(
    baseline_command: Sequence[str],
    candidate_command: Sequence[str],
    output_dir: str | Path,
    *,
    pair_count: int | None = None,
    random_seed: int | None = None,
    baseline_cwd: str | Path | None = None,
    candidate_cwd: str | Path | None = None,
    resume: bool = False,
    retry_failed: bool = False,
) -> BenchmarkPairedRunGroup:
    """Collect adjacent paired runs using a deterministic AB/BA schedule.

    Every target pair is one atomic two-command block. AB and BA orientations
    alternate, with ``random_seed`` choosing the first orientation. Both
    variants use the same balanced Williams-style matrix order. A failed or
    interrupted block contributes no pair; retrying reruns both variants as a
    new adjacent block attempt while retaining all earlier records.

    Args:
        baseline_command: Baseline pytest command without ``--benchmark-json``.
        candidate_command: Candidate pytest command without
            ``--benchmark-json``.
        output_dir: New collection directory, or an existing one when resuming.
        pair_count: Complete-pair target. When omitted, collection starts with
            a provisional target of six and expands after matrix discovery to
            the smallest complete joint supercycle meeting the five-pair
            evidence default.
        random_seed: Deterministic AB/BA and matrix-order seed. New collections
            default to zero; an omitted resume value preserves the manifest.
        baseline_cwd: Baseline child working directory. Defaults to the current
            directory for a new collection and the manifest value on resume.
        candidate_cwd: Candidate child working directory, with the same rules.
        resume: Continue a manifest-backed paired collection.
        retry_failed: Append one atomic block attempt for every pair still
            incomplete after interrupted work is resumed. Requires ``resume``.

    Returns:
        The paired collection with complete pairs and full lifecycle records.

    Raises:
        BenchmarkCollectionError: If collection cannot be initialized or
            resumed, or supplied settings disagree with the manifest.
    """
    if retry_failed and not resume:
        raise BenchmarkCollectionError("retry_failed requires resume=True.")
    if pair_count is not None and (isinstance(pair_count, bool) or not isinstance(pair_count, int) or pair_count <= 0):
        raise BenchmarkCollectionError("pair_count must be a positive integer.")
    if random_seed is not None and (
        isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed < 0
    ):
        raise BenchmarkCollectionError("random_seed must be a non-negative integer.")

    output = Path(output_dir).resolve()
    if resume:
        group = _load_resumable_paired_group(output)
        normalized_baseline = _resume_variant_command(baseline_command, group.baseline_command, variant="baseline")
        normalized_candidate = _resume_variant_command(candidate_command, group.candidate_command, variant="candidate")
        requested_pairs = group.requested_pairs
        resolved_seed = group.random_seed
        if pair_count is not None and pair_count != requested_pairs:
            raise BenchmarkCollectionError(
                f"pair_count {pair_count} does not match the manifest target {requested_pairs}."
            )
        if random_seed is not None and random_seed != resolved_seed:
            raise BenchmarkCollectionError(
                f"random_seed {random_seed} does not match the manifest seed {resolved_seed}."
            )
        resolved_baseline_cwd = _resume_variant_cwd(baseline_cwd, group.baseline_cwd, variant="baseline")
        resolved_candidate_cwd = _resume_variant_cwd(candidate_cwd, group.candidate_cwd, variant="candidate")
        manifest_path = group.manifest_path
        created_at = group.created_at
        records = list(group.records)
        runs = list(group.runs)
        expected_cells = group.expected_cells
        baseline_commit = group.baseline_commit
        candidate_commit = group.candidate_commit
        baseline_fingerprint = group.baseline_environment_fingerprint
        candidate_fingerprint = group.candidate_environment_fingerprint
        automatic_pairs = group.automatic_pairs
    else:
        normalized_baseline = _validate_collection_command(baseline_command)
        normalized_candidate = _validate_collection_command(candidate_command)
        automatic_pairs = pair_count is None
        requested_pairs = _PROVISIONAL_AUTOMATIC_PAIRS if automatic_pairs else cast(int, pair_count)
        resolved_seed = 0 if random_seed is None else random_seed
        resolved_baseline_cwd = _resolve_new_collection_cwd(baseline_cwd, variant="baseline")
        resolved_candidate_cwd = _resolve_new_collection_cwd(candidate_cwd, variant="candidate")
        _initialize_output_directory(output)
        manifest_path = output / RUN_GROUP_MANIFEST
        created_at = _utc_now()
        records = []
        runs = []
        expected_cells = ()
        baseline_commit = None
        candidate_commit = None
        baseline_fingerprint = None
        candidate_fingerprint = None

    def write_manifest() -> None:
        """Persist current paired state after every completed command."""
        _write_paired_manifest(
            manifest_path,
            baseline_command=normalized_baseline,
            candidate_command=normalized_candidate,
            created_at=created_at,
            baseline_cwd=resolved_baseline_cwd,
            candidate_cwd=resolved_candidate_cwd,
            baseline_commit=baseline_commit,
            candidate_commit=candidate_commit,
            baseline_environment_fingerprint=baseline_fingerprint,
            candidate_environment_fingerprint=candidate_fingerprint,
            expected_cells=expected_cells,
            requested_pairs=requested_pairs,
            automatic_pairs=automatic_pairs,
            random_seed=resolved_seed,
            records=records,
        )

    if not resume:
        write_manifest()

    def execute_block(entry: BenchmarkPairSchedule, block_attempt: int) -> None:
        """Execute and persist one complete adjacent AB/BA block attempt."""
        nonlocal expected_cells, baseline_commit, candidate_commit
        nonlocal baseline_fingerprint, candidate_fingerprint
        nonlocal requested_pairs
        for variant in entry.variants:
            command = normalized_baseline if variant == "baseline" else normalized_candidate
            cwd = resolved_baseline_cwd if variant == "baseline" else resolved_candidate_cwd
            index = len(records) + 1
            result_path = _available_paired_result_path(
                output,
                pair_index=entry.pair_index,
                block_attempt=block_attempt,
                variant=variant,
            )
            started_at = _utc_now()
            started = time.monotonic()
            returncode: int | None = None
            error: str | None = None
            warnings: tuple[str, ...] = ()
            run: BenchmarkRun | None = None
            commit: str | None = None
            fingerprint: str | None = None
            try:
                argv = [*command, f"--benchmark-json={result_path}"]
                command_stdout = _COLLECTION_COMMAND_STDOUT.get()
                with _collection_order_environment(
                    random_seed=resolved_seed,
                    order_index=entry.cell_order_index,
                ):
                    if command_stdout is None:
                        completed = subprocess.run(argv, check=False, cwd=cwd)  # nosec B603
                    else:
                        completed = subprocess.run(  # nosec B603
                            argv,
                            check=False,
                            cwd=cwd,
                            stdout=subprocess.PIPE,
                            text=True,
                        )
                        if completed.stdout:
                            _ = command_stdout.write(completed.stdout)
                            command_stdout.flush()
                returncode = completed.returncode
                if returncode != 0:
                    error = f"Benchmark command exited with status {returncode}."
                else:
                    run = load_benchmark_run(result_path)
                    candidate_cells = expected_cells or _run_cells(run)
                    scheduled_cells = balanced_cell_order(
                        candidate_cells,
                        order_index=entry.cell_order_index,
                        random_seed=resolved_seed,
                    )
                    if _run_cell_order(run) != scheduled_cells:
                        error = "Benchmark matrix cells were not executed in the scheduled balanced order."
                    commit = _run_commit(run)
                    fingerprint = _environment_fingerprint(run)
                    anchor_commit = baseline_commit if variant == "baseline" else candidate_commit
                    if error is None and anchor_commit is not None and commit != anchor_commit:
                        error = f"{variant.capitalize()} commit differs from its first successful run."
                    if error is None and runs:
                        error, warnings = _validate_paired_collected_run(
                            runs[0],
                            run,
                            expected_cells=candidate_cells,
                        )
                    if error is None and not expected_cells:
                        expected_cells = candidate_cells
                        if automatic_pairs:
                            requested_pairs = _automatic_pair_target(len(expected_cells))
                    if error is None and variant == "baseline" and baseline_fingerprint is None:
                        baseline_commit = commit
                        baseline_fingerprint = fingerprint
                    if error is None and variant == "candidate" and candidate_fingerprint is None:
                        candidate_commit = commit
                        candidate_fingerprint = fingerprint
            except (OSError, BenchmarkJsonError, TypeError, ValueError) as exc:
                error = str(exc)

            duration = time.monotonic() - started
            common = {
                "index": index,
                "pair_index": entry.pair_index,
                "block_attempt": block_attempt,
                "variant": variant,
                "pair_order": entry.pair_order,
                "order_position": _variant_order_position(variant, entry.pair_order),
                "cell_order_index": entry.cell_order_index,
                "path": result_path,
                "returncode": returncode,
                "started_at": started_at,
                "duration_seconds": duration,
            }
            if error is None and run is not None and fingerprint is not None:
                runs.append(run)
                record = BenchmarkPairedRunRecord(
                    **common,
                    status="succeeded",
                    warnings=warnings,
                    commit=commit,
                    environment_fingerprint=fingerprint,
                )
            else:
                record = BenchmarkPairedRunRecord(
                    **common,
                    status="failed",
                    error=error or "Benchmark command did not produce a valid run.",
                )
            records.append(record)
            write_manifest()

    attempted_pairs_this_call: set[int] = set()

    # The first target pair establishes the matrix size. Until at least one
    # command succeeds, no later pair has a well-defined balanced-order row.
    if not expected_cells:
        first_entry = make_paired_ab_ba_schedule(
            requested_pairs,
            random_seed=resolved_seed,
        )[0]
        first_records = [record for record in records if record.pair_index == 1]
        should_attempt_first = (
            not first_records
            or _latest_block_is_partial(first_records)
            or (retry_failed and not _pair_has_complete_block(first_records))
        )
        if should_attempt_first:
            next_attempt = max((record.block_attempt for record in first_records), default=0) + 1
            execute_block(first_entry, next_attempt)
            attempted_pairs_this_call.add(1)

    # Start every never-attempted target pair only after learning cell_count.
    # A partially persisted block is abandoned and replaced by a new adjacent
    # atomic block before collection advances.
    schedule = (
        make_paired_ab_ba_schedule(
            requested_pairs,
            random_seed=resolved_seed,
            cell_count=len(expected_cells),
        )
        if expected_cells
        else ()
    )
    for entry in schedule:
        pair_records = [record for record in records if record.pair_index == entry.pair_index]
        if not pair_records:
            execute_block(entry, 1)
            attempted_pairs_this_call.add(entry.pair_index)
        elif not _pair_has_complete_block(pair_records) and _latest_block_is_partial(pair_records):
            execute_block(entry, max(record.block_attempt for record in pair_records) + 1)
            attempted_pairs_this_call.add(entry.pair_index)

    if retry_failed:
        for entry in schedule:
            pair_records = [record for record in records if record.pair_index == entry.pair_index]
            if entry.pair_index not in attempted_pairs_this_call and not _pair_has_complete_block(pair_records):
                next_attempt = max((record.block_attempt for record in pair_records), default=0) + 1
                execute_block(entry, next_attempt)

    return BenchmarkPairedRunGroup(
        runs=tuple(runs),
        records=tuple(records),
        baseline_command=normalized_baseline,
        candidate_command=normalized_candidate,
        created_at=created_at,
        baseline_cwd=resolved_baseline_cwd,
        candidate_cwd=resolved_candidate_cwd,
        baseline_commit=baseline_commit,
        candidate_commit=candidate_commit,
        baseline_environment_fingerprint=baseline_fingerprint,
        candidate_environment_fingerprint=candidate_fingerprint,
        expected_cells=expected_cells,
        requested_pairs=requested_pairs,
        random_seed=resolved_seed,
        manifest_path=manifest_path,
        automatic_pairs=automatic_pairs,
    )


def _load_resumable_paired_group(output: Path) -> BenchmarkPairedRunGroup:
    """Load an existing paired output directory for resume."""
    if not output.is_dir():
        raise BenchmarkCollectionError(f"Collection output directory does not exist: {output}")
    try:
        return load_paired_benchmark_run_group(output / RUN_GROUP_MANIFEST)
    except BenchmarkJsonError as exc:
        raise BenchmarkCollectionError(f"Could not resume paired collection: {exc}") from exc


def _resume_variant_command(
    supplied: Sequence[str],
    recorded: tuple[str, ...],
    *,
    variant: PairedVariant,
) -> tuple[str, ...]:
    """Resolve and validate one paired resume command."""
    if not supplied:
        return recorded
    normalized = _validate_collection_command(supplied)
    if normalized != recorded:
        raise BenchmarkCollectionError(f"Resume {variant} command does not match the paired manifest.")
    return normalized


def _resolve_new_collection_cwd(value: str | Path | None, *, variant: PairedVariant) -> Path:
    """Resolve a new paired child working directory."""
    resolved = Path.cwd().resolve() if value is None else Path(value).resolve()
    if not resolved.is_dir():
        raise BenchmarkCollectionError(f"Paired {variant} working directory is unavailable: {resolved}")
    return resolved


def _resume_variant_cwd(
    supplied: str | Path | None,
    recorded: Path,
    *,
    variant: PairedVariant,
) -> Path:
    """Resolve and validate one paired resume working directory."""
    if supplied is not None and Path(supplied).resolve() != recorded:
        raise BenchmarkCollectionError(f"Resume {variant} working directory does not match the paired manifest.")
    if not recorded.is_dir():
        raise BenchmarkCollectionError(f"Paired {variant} working directory is unavailable: {recorded}")
    return recorded


def _available_paired_result_path(
    output: Path,
    *,
    pair_index: int,
    block_attempt: int,
    variant: PairedVariant,
) -> Path:
    """Return a paired result path without overwriting partial output."""
    stem = f"pair-{pair_index:03d}-block-{block_attempt:02d}-{variant}"
    preferred = output / f"{stem}.json"
    if not preferred.exists():
        return preferred
    suffix = 2
    while True:
        candidate = output / f"{stem}-attempt-{suffix:02d}.json"
        if not candidate.exists():
            return candidate
        suffix += 1


def _pair_has_complete_block(records: Sequence[BenchmarkPairedRunRecord]) -> bool:
    """Return whether one target pair has a successful atomic block."""
    successes: dict[int, set[PairedVariant]] = {}
    for record in records:
        if record.status == "succeeded":
            successes.setdefault(record.block_attempt, set()).add(record.variant)
    return any(variants == {"baseline", "candidate"} for variants in successes.values())


def _latest_block_is_partial(records: Sequence[BenchmarkPairedRunRecord]) -> bool:
    """Return whether the latest block attempt lacks one scheduled command."""
    latest = max(record.block_attempt for record in records)
    return sum(record.block_attempt == latest for record in records) < 2


def _validate_paired_collected_run(
    anchor: BenchmarkRun,
    candidate: BenchmarkRun,
    *,
    expected_cells: tuple[BenchmarkCell, ...],
) -> tuple[str | None, tuple[str, ...]]:
    """Validate matrix and environment without requiring equal commits."""
    if _run_cells(candidate) != expected_cells:
        return "Benchmark matrix cells differ from the first successful run.", ()
    comparison = compare_benchmark_run_groups(
        (anchor,),
        (candidate,),
        compatibility_policy=RunCompatibilityPolicy(mode="permissive"),
        evidence_policy=EvidencePolicy(minimum_runs=1, minimum_samples_per_run=0),
        inference_policy=InferencePolicy(method="legacy_consistency"),
    )
    if comparison.compatibility.blocking:
        fields = ", ".join(finding.field for finding in comparison.compatibility.blocking)
        return f"Benchmark environment is incompatible with the first successful run: {fields}.", ()
    warnings = tuple(f"{finding.field}: {finding.reason}" for finding in comparison.compatibility.warnings)
    return None, warnings


def _write_paired_manifest(
    manifest_path: Path,
    *,
    baseline_command: tuple[str, ...],
    candidate_command: tuple[str, ...],
    created_at: str,
    baseline_cwd: Path,
    candidate_cwd: Path,
    baseline_commit: str | None,
    candidate_commit: str | None,
    baseline_environment_fingerprint: str | None,
    candidate_environment_fingerprint: str | None,
    expected_cells: tuple[BenchmarkCell, ...],
    requested_pairs: int,
    automatic_pairs: bool,
    random_seed: int,
    records: Sequence[BenchmarkPairedRunRecord],
) -> None:
    """Atomically write a paired collection manifest."""
    payload = {
        "producer": PRODUCER,
        "kind": PAIRED_RUN_GROUP_KIND,
        "schema_version": PAIRED_RUN_GROUP_SCHEMA_VERSION,
        "created_at": created_at,
        "baseline_command": list(baseline_command),
        "candidate_command": list(candidate_command),
        "baseline_cwd": str(baseline_cwd),
        "candidate_cwd": str(candidate_cwd),
        "baseline_commit": baseline_commit,
        "candidate_commit": candidate_commit,
        "baseline_environment_fingerprint": baseline_environment_fingerprint,
        "candidate_environment_fingerprint": candidate_environment_fingerprint,
        "requested_pairs": requested_pairs,
        "automatic_pairs": automatic_pairs,
        "random_seed": random_seed,
        "expected_cells": [
            {
                "implementation_name": implementation_name,
                "case_name": case_name,
                "metric_name": metric_name,
            }
            for implementation_name, case_name, metric_name in expected_cells
        ],
        "runs": [_paired_record_json(record, manifest_path=manifest_path) for record in records],
    }
    temporary_path = manifest_path.with_suffix(".json.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
    except (OSError, TypeError, ValueError) as exc:
        raise BenchmarkCollectionError(f"Could not write paired collection manifest: {manifest_path}") from exc


def _paired_record_json(record: BenchmarkPairedRunRecord, *, manifest_path: Path) -> dict[str, object]:
    """Return one paired manifest-safe command record."""
    try:
        relative_path = record.path.relative_to(manifest_path.parent)
    except ValueError as exc:
        raise BenchmarkCollectionError("Paired collection run paths must be inside the output directory.") from exc
    return {
        "index": record.index,
        "pair_index": record.pair_index,
        "block_attempt": record.block_attempt,
        "variant": record.variant,
        "pair_order": record.pair_order,
        "order_position": record.order_position,
        "cell_order_index": record.cell_order_index,
        "status": record.status,
        "path": relative_path.as_posix(),
        "returncode": record.returncode,
        "started_at": record.started_at,
        "duration_seconds": record.duration_seconds,
        "error": record.error,
        "warnings": list(record.warnings),
        "commit": record.commit,
        "environment_fingerprint": record.environment_fingerprint,
    }


def _parse_paired_record(
    payload: Mapping[str, object],
    *,
    manifest_path: Path,
    path: str,
) -> BenchmarkPairedRunRecord:
    """Parse one paired command record from a manifest."""
    relative = Path(_require_non_empty_string(payload["path"], path=f"{path}.path"))
    if relative.anchor or ".." in relative.parts:
        raise BenchmarkJsonError(f"Expected a relative in-directory path at {path}.path.")
    status = _require_string(payload["status"], path=f"{path}.status")
    if status not in {"succeeded", "failed"}:
        raise BenchmarkJsonError(f"Unsupported collection status at {path}.status: {status!r}.")
    variant = _require_string(payload["variant"], path=f"{path}.variant")
    if variant not in {"baseline", "candidate"}:
        raise BenchmarkJsonError(f"Unsupported paired variant at {path}.variant: {variant!r}.")
    pair_order = _require_string(payload["pair_order"], path=f"{path}.pair_order")
    if pair_order not in {"AB", "BA"}:
        raise BenchmarkJsonError(f"Unsupported paired order at {path}.pair_order: {pair_order!r}.")
    fingerprint = _parse_optional_manifest_fingerprint(
        payload["environment_fingerprint"],
        path=f"{path}.environment_fingerprint",
    )
    try:
        return BenchmarkPairedRunRecord(
            index=_require_positive_int(payload["index"], path=f"{path}.index"),
            pair_index=_require_positive_int(payload["pair_index"], path=f"{path}.pair_index"),
            block_attempt=_require_positive_int(payload["block_attempt"], path=f"{path}.block_attempt"),
            variant=cast(PairedVariant, variant),
            pair_order=cast(PairedOrder, pair_order),
            order_position=_require_positive_int(payload["order_position"], path=f"{path}.order_position"),
            cell_order_index=_require_positive_int(payload["cell_order_index"], path=f"{path}.cell_order_index"),
            status=cast(CollectionRunStatus, status),
            path=manifest_path.parent / relative,
            returncode=_require_optional_int(payload["returncode"], path=f"{path}.returncode"),
            started_at=_require_string(payload["started_at"], path=f"{path}.started_at"),
            duration_seconds=_require_non_negative_float(payload["duration_seconds"], path=f"{path}.duration_seconds"),
            error=_require_optional_string(payload["error"], path=f"{path}.error"),
            warnings=tuple(_require_string_list(payload["warnings"], path=f"{path}.warnings")),
            commit=_require_optional_string(payload["commit"], path=f"{path}.commit"),
            environment_fingerprint=fingerprint,
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid paired run record at {path}: {exc}") from exc


def _validate_loaded_paired_run(
    run: BenchmarkRun,
    *,
    record: BenchmarkPairedRunRecord,
    expected_cells: tuple[BenchmarkCell, ...],
    random_seed: int,
) -> None:
    """Validate a paired record against its referenced benchmark file."""
    if _run_cells(run) != expected_cells:
        raise BenchmarkJsonError(f"Successful paired run {record.index} does not match expected_cells.")
    expected_order = balanced_cell_order(
        expected_cells,
        order_index=record.cell_order_index,
        random_seed=random_seed,
    )
    if _run_cell_order(run) != expected_order:
        raise BenchmarkJsonError(f"Successful paired run {record.index} does not match its scheduled cell order.")
    if _run_commit(run) != record.commit:
        raise BenchmarkJsonError(f"Successful paired run {record.index} commit does not match its record.")
    if _environment_fingerprint(run) != record.environment_fingerprint:
        raise BenchmarkJsonError(
            f"Successful paired run {record.index} environment fingerprint does not match its record."
        )


def _validate_optional_anchor(value: str | None, *, field: str) -> None:
    """Validate one optional root string anchor."""
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f"BenchmarkPairedRunGroup.{field} must be a non-empty string or None.")


def _validate_optional_fingerprint(value: str | None, *, field: str) -> None:
    """Validate one optional root fingerprint."""
    if value is not None:
        _validate_fingerprint(value, field_name=field)


def _validate_paired_variant_anchors(
    records: Sequence[BenchmarkPairedRunRecord],
    *,
    baseline_commit: str | None,
    candidate_commit: str | None,
    baseline_fingerprint: str | None,
    candidate_fingerprint: str | None,
) -> None:
    """Validate per-variant root anchors against successful records."""
    for variant, commit, fingerprint in (
        ("baseline", baseline_commit, baseline_fingerprint),
        ("candidate", candidate_commit, candidate_fingerprint),
    ):
        variant_records = [record for record in records if record.variant == variant]
        if not variant_records:
            if commit is not None or fingerprint is not None:
                raise ValueError(f"Paired {variant} anchors require a successful record.")
            continue
        if variant_records[0].environment_fingerprint != fingerprint:
            raise ValueError(f"First successful {variant} fingerprint does not match the group anchor.")
        if any(record.commit != commit for record in variant_records):
            raise ValueError(f"Successful {variant} commits do not match the group anchor.")


def _parse_optional_manifest_fingerprint(value: object, *, path: str) -> str | None:
    """Parse and validate an optional manifest fingerprint."""
    fingerprint = _require_optional_string(value, path=path)
    if fingerprint is not None:
        _validate_manifest_fingerprint(fingerprint, path=path)
    return fingerprint


def collect_benchmark_runs(
    command: Sequence[str],
    output_dir: str | Path,
    *,
    run_count: int | None = None,
    resume: bool = False,
    retry_failed: bool = False,
) -> BenchmarkRunGroup:
    """Execute or resume pytest runs and persist a run-group manifest.

    ``--benchmark-json`` is injected once per attempt. Attempts run
    sequentially and collection continues after failures so the manifest
    preserves complete lifecycle diagnostics. Resuming fills initial attempts
    that were never recorded. Retrying appends attempts until each currently
    missing successful run has received one new attempt; prior failures are
    never replaced.

    Args:
        command: Pytest command and arguments without ``--benchmark-json``.
            May be empty when resuming, in which case the manifest command is
            reused. A supplied resume command must exactly match the manifest.
        output_dir: New or empty directory for a new collection, or an existing
            collection directory when resuming.
        run_count: Successful-run target. New collections default to five.
            When resuming, an omitted value preserves the manifest target and
            a supplied value must match it.
        resume: Continue an existing manifest-backed collection.
        retry_failed: After resuming unattempted slots, append one new attempt
            for each successful run still needed. Requires ``resume``.

    Returns:
        The completed collection, including successful runs and failed records.

    Raises:
        BenchmarkCollectionError: If collection cannot be initialized or
            resumed, or the command and requested count do not match.
    """
    if retry_failed and not resume:
        raise BenchmarkCollectionError("retry_failed requires resume=True.")
    if run_count is not None and (isinstance(run_count, bool) or not isinstance(run_count, int) or run_count <= 0):
        raise BenchmarkCollectionError("run_count must be a positive integer.")

    output = Path(output_dir).resolve()
    if resume:
        group = _load_resumable_group(output)
        normalized_command = _resume_command(command, group)
        requested_runs = group.requested_runs
        if run_count is not None and run_count != requested_runs:
            raise BenchmarkCollectionError(
                f"run_count {run_count} does not match the manifest target {requested_runs}."
            )
        manifest_path = group.manifest_path
        created_at = group.created_at
        cwd = group.cwd
        if not cwd.is_dir():
            raise BenchmarkCollectionError(f"Collection working directory is unavailable: {cwd}")
        records = list(group.records)
        runs = list(group.runs)
        expected_cells = group.expected_cells
        anchor_commit = group.commit
        anchor_fingerprint = group.environment_fingerprint
    else:
        normalized_command = _validate_collection_command(command)
        requested_runs = 5 if run_count is None else run_count
        _initialize_output_directory(output)
        manifest_path = output / RUN_GROUP_MANIFEST
        created_at = _utc_now()
        cwd = Path.cwd().resolve()
        records = []
        runs = []
        expected_cells = ()
        anchor_commit = None
        anchor_fingerprint = None
        _write_manifest(
            manifest_path,
            command=normalized_command,
            created_at=created_at,
            cwd=cwd,
            commit=anchor_commit,
            environment_fingerprint=anchor_fingerprint,
            expected_cells=expected_cells,
            requested_runs=requested_runs,
            records=records,
        )

    def execute_attempts(count: int) -> None:
        """Execute and persist a bounded set of collection attempts."""
        nonlocal expected_cells, anchor_commit, anchor_fingerprint
        for _ in range(count):
            index = len(records) + 1
            result_path = _available_result_path(output, index)
            started_at = _utc_now()
            started = time.monotonic()
            returncode: int | None = None
            error: str | None = None
            warnings: tuple[str, ...] = ()
            run: BenchmarkRun | None = None
            commit: str | None = None
            fingerprint: str | None = None

            try:
                # The CLI intentionally executes user-supplied argv without a shell.
                argv = [*normalized_command, f"--benchmark-json={result_path}"]
                command_stdout = _COLLECTION_COMMAND_STDOUT.get()
                if command_stdout is None:
                    completed = subprocess.run(argv, check=False, cwd=cwd)  # nosec B603
                else:
                    completed = subprocess.run(  # nosec B603
                        argv,
                        check=False,
                        cwd=cwd,
                        stdout=subprocess.PIPE,
                        text=True,
                    )
                    if completed.stdout:
                        _ = command_stdout.write(completed.stdout)
                        command_stdout.flush()
                returncode = completed.returncode
                if returncode != 0:
                    error = f"Benchmark command exited with status {returncode}."
                else:
                    run = load_benchmark_run(result_path)
                    commit = _run_commit(run)
                    fingerprint = _environment_fingerprint(run)
                    if runs:
                        error, warnings = _validate_collected_run(
                            runs[0],
                            run,
                            expected_cells=expected_cells,
                            anchor_commit=anchor_commit,
                            commit=commit,
                        )
                    if error is None and not runs:
                        expected_cells = _run_cells(run)
                        anchor_commit = commit
                        anchor_fingerprint = fingerprint
            except (OSError, BenchmarkJsonError, TypeError, ValueError) as exc:
                error = str(exc)

            duration = time.monotonic() - started
            if error is None and run is not None and fingerprint is not None:
                runs.append(run)
                record = BenchmarkRunRecord(
                    index=index,
                    status="succeeded",
                    path=result_path,
                    returncode=returncode,
                    started_at=started_at,
                    duration_seconds=duration,
                    warnings=warnings,
                    commit=commit,
                    environment_fingerprint=fingerprint,
                )
            else:
                record = BenchmarkRunRecord(
                    index=index,
                    status="failed",
                    path=result_path,
                    returncode=returncode,
                    started_at=started_at,
                    duration_seconds=duration,
                    error=error or "Benchmark command did not produce a valid run.",
                )
            records.append(record)
            _write_manifest(
                manifest_path,
                command=normalized_command,
                created_at=created_at,
                cwd=cwd,
                commit=anchor_commit,
                environment_fingerprint=anchor_fingerprint,
                expected_cells=expected_cells,
                requested_runs=requested_runs,
                records=records,
            )

    execute_attempts(max(0, requested_runs - len(records)))
    if retry_failed:
        execute_attempts(requested_runs - len(runs))

    return BenchmarkRunGroup(
        runs=tuple(runs),
        records=tuple(records),
        command=normalized_command,
        created_at=created_at,
        cwd=cwd,
        commit=anchor_commit,
        environment_fingerprint=anchor_fingerprint,
        expected_cells=expected_cells,
        requested_runs=requested_runs,
        manifest_path=manifest_path,
    )


def _load_resumable_group(output: Path) -> BenchmarkRunGroup:
    """Load an existing output directory for a resume operation."""
    if not output.is_dir():
        raise BenchmarkCollectionError(f"Collection output directory does not exist: {output}")
    manifest_path = output / RUN_GROUP_MANIFEST
    try:
        return load_benchmark_run_group(manifest_path)
    except BenchmarkJsonError as exc:
        raise BenchmarkCollectionError(f"Could not resume collection: {exc}") from exc


def _resume_command(
    command: Sequence[str],
    group: BenchmarkRunGroup,
) -> tuple[str, ...]:
    """Resolve and validate the command used for a resumed collection."""
    if not command:
        return group.command
    normalized = _validate_collection_command(command)
    if normalized != group.command:
        raise BenchmarkCollectionError("Resume command does not match the collection manifest.")
    return normalized


def _available_result_path(output: Path, index: int) -> Path:
    """Return a result path without overwriting an unrecorded partial file."""
    preferred = output / f"run-{index:03d}.json"
    if not preferred.exists():
        return preferred
    suffix = 2
    while True:
        candidate = output / f"run-{index:03d}-attempt-{suffix:02d}.json"
        if not candidate.exists():
            return candidate
        suffix += 1


def _validate_collected_run(
    anchor: BenchmarkRun,
    candidate: BenchmarkRun,
    *,
    expected_cells: tuple[BenchmarkCell, ...],
    anchor_commit: str | None,
    commit: str | None,
) -> tuple[str | None, tuple[str, ...]]:
    """Validate one run against the first successful collection run."""
    if _run_cells(candidate) != expected_cells:
        return "Benchmark matrix cells differ from the first successful run.", ()
    if commit != anchor_commit:
        return "Benchmark commit differs from the first successful run.", ()

    comparison = compare_benchmark_run_groups(
        (anchor,),
        (candidate,),
        compatibility_policy=RunCompatibilityPolicy(mode="permissive"),
        evidence_policy=EvidencePolicy(minimum_runs=1, minimum_samples_per_run=0),
        inference_policy=InferencePolicy(method="legacy_consistency"),
    )
    if comparison.compatibility.blocking:
        fields = ", ".join(finding.field for finding in comparison.compatibility.blocking)
        return f"Benchmark environment is incompatible with the first successful run: {fields}.", ()
    warnings = tuple(f"{finding.field}: {finding.reason}" for finding in comparison.compatibility.warnings)
    return None, warnings


def _validate_loaded_run(
    run: BenchmarkRun,
    *,
    record: BenchmarkRunRecord,
    expected_cells: tuple[BenchmarkCell, ...],
    anchor_commit: str | None,
    anchor_fingerprint: str | None,
) -> None:
    """Validate a successful manifest record against its referenced file."""
    if _run_cells(run) != expected_cells:
        raise BenchmarkJsonError(f"Successful run {record.index} does not match manifest expected_cells.")
    commit = _run_commit(run)
    if commit != record.commit:
        raise BenchmarkJsonError(f"Successful run {record.index} commit does not match its manifest record.")
    fingerprint = _environment_fingerprint(run)
    if fingerprint != record.environment_fingerprint:
        raise BenchmarkJsonError(
            f"Successful run {record.index} environment fingerprint does not match its manifest record."
        )
    if anchor_commit != commit:
        raise BenchmarkJsonError(f"Successful run {record.index} commit does not match the manifest anchor.")
    if anchor_fingerprint is None:
        raise BenchmarkJsonError("Manifest with successful runs requires an environment fingerprint.")


def _run_cells(run: BenchmarkRun) -> tuple[BenchmarkCell, ...]:
    """Return a stable sorted tuple of matrix cells."""
    return tuple(sorted((row.implementation_name, row.case_name, row.metric_name) for row in run.rows))


def _run_cell_order(run: BenchmarkRun) -> tuple[BenchmarkCell, ...]:
    """Return matrix cells in their observed pytest execution order."""
    return tuple((row.implementation_name, row.case_name, row.metric_name) for row in run.rows)


def _run_commit(run: BenchmarkRun) -> str | None:
    """Return the source commit reported by pytest-benchmark."""
    commit_info = run.metadata.get("commit_info")
    if not isinstance(commit_info, Mapping):
        return None
    commit = commit_info.get("id")
    return commit if isinstance(commit, str) and commit else None


def _environment_fingerprint(run: BenchmarkRun) -> str:
    """Return a stable SHA-256 fingerprint of environment metadata."""
    environment = {
        "dependencies": run.metadata.get("dependencies"),
        "machine_info": run.metadata.get("machine_info"),
        "pytest_benchmark_version": run.metadata.get("version"),
    }
    try:
        encoded = json.dumps(
            environment,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError("Benchmark environment metadata is not strict-JSON-safe.") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _validate_collection_command(command: Sequence[str]) -> tuple[str, ...]:
    """Validate and freeze a collection command."""
    normalized = tuple(command)
    if not normalized:
        raise BenchmarkCollectionError("A pytest command is required after '--'.")
    if any(not isinstance(argument, str) or not argument for argument in normalized):
        raise BenchmarkCollectionError("Command arguments must be non-empty strings.")
    if any(argument == "--benchmark-json" or argument.startswith("--benchmark-json=") for argument in normalized):
        raise BenchmarkCollectionError("Do not supply --benchmark-json; benchmatrix assigns one output per run.")
    return normalized


def _initialize_output_directory(output: Path) -> None:
    """Create an empty collection output directory."""
    try:
        if output.exists():
            if not output.is_dir():
                raise BenchmarkCollectionError(f"Collection output is not a directory: {output}")
            if any(output.iterdir()):
                raise BenchmarkCollectionError(f"Collection output directory is not empty: {output}")
        else:
            output.mkdir(parents=True)
    except OSError as exc:
        raise BenchmarkCollectionError(f"Could not initialize collection output: {output}") from exc


def _write_manifest(
    manifest_path: Path,
    *,
    command: tuple[str, ...],
    created_at: str,
    cwd: Path,
    commit: str | None,
    environment_fingerprint: str | None,
    expected_cells: tuple[BenchmarkCell, ...],
    requested_runs: int,
    records: Sequence[BenchmarkRunRecord],
) -> None:
    """Atomically write the current collection manifest."""
    payload = {
        "producer": PRODUCER,
        "kind": RUN_GROUP_KIND,
        "schema_version": RUN_GROUP_SCHEMA_VERSION,
        "created_at": created_at,
        "command": list(command),
        "cwd": str(cwd),
        "commit": commit,
        "environment_fingerprint": environment_fingerprint,
        "requested_runs": requested_runs,
        "expected_cells": [
            {
                "implementation_name": implementation_name,
                "case_name": case_name,
                "metric_name": metric_name,
            }
            for implementation_name, case_name, metric_name in expected_cells
        ],
        "runs": [_record_json(record, manifest_path=manifest_path) for record in records],
    }
    temporary_path = manifest_path.with_suffix(".json.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
    except (OSError, TypeError, ValueError) as exc:
        raise BenchmarkCollectionError(f"Could not write collection manifest: {manifest_path}") from exc


def _record_json(record: BenchmarkRunRecord, *, manifest_path: Path) -> dict[str, object]:
    """Return one manifest-safe run record."""
    try:
        relative_path = record.path.relative_to(manifest_path.parent)
    except ValueError as exc:
        raise BenchmarkCollectionError("Collection run paths must be inside the output directory.") from exc
    return {
        "index": record.index,
        "status": record.status,
        "path": relative_path.as_posix(),
        "returncode": record.returncode,
        "started_at": record.started_at,
        "duration_seconds": record.duration_seconds,
        "error": record.error,
        "warnings": list(record.warnings),
        "commit": record.commit,
        "environment_fingerprint": record.environment_fingerprint,
    }


def _parse_record(
    payload: Mapping[str, object],
    *,
    manifest_path: Path,
    path: str,
) -> BenchmarkRunRecord:
    """Parse one run record from a collection manifest."""
    relative = Path(_require_non_empty_string(payload["path"], path=f"{path}.path"))
    if relative.anchor or ".." in relative.parts:
        raise BenchmarkJsonError(f"Expected a relative in-directory path at {path}.path.")
    status = _require_string(payload["status"], path=f"{path}.status")
    if status not in {"succeeded", "failed"}:
        raise BenchmarkJsonError(f"Unsupported collection status at {path}.status: {status!r}.")
    fingerprint = _require_optional_string(
        payload["environment_fingerprint"],
        path=f"{path}.environment_fingerprint",
    )
    if fingerprint is not None:
        _validate_manifest_fingerprint(fingerprint, path=f"{path}.environment_fingerprint")
    try:
        return BenchmarkRunRecord(
            index=_require_positive_int(payload["index"], path=f"{path}.index"),
            status=cast(CollectionRunStatus, status),
            path=manifest_path.parent / relative,
            returncode=_require_optional_int(payload["returncode"], path=f"{path}.returncode"),
            started_at=_require_string(payload["started_at"], path=f"{path}.started_at"),
            duration_seconds=_require_non_negative_float(
                payload["duration_seconds"],
                path=f"{path}.duration_seconds",
            ),
            error=_require_optional_string(payload["error"], path=f"{path}.error"),
            warnings=tuple(_require_string_list(payload["warnings"], path=f"{path}.warnings")),
            commit=_require_optional_string(payload["commit"], path=f"{path}.commit"),
            environment_fingerprint=fingerprint,
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkJsonError(f"Invalid run record at {path}: {exc}") from exc


def _parse_cells(value: object) -> tuple[BenchmarkCell, ...]:
    """Parse expected matrix cells from a collection manifest."""
    payloads = _require_list(value, path="manifest.expected_cells")
    cells: list[BenchmarkCell] = []
    for index, payload in enumerate(payloads):
        path = f"manifest.expected_cells[{index}]"
        mapping = _require_mapping(payload, path=path)
        _require_exact_keys(mapping, _CELL_KEYS, path=path)
        metric = _require_string(mapping["metric_name"], path=f"{path}.metric_name")
        if metric not in KNOWN_METRICS:
            raise BenchmarkJsonError(f"Unsupported metric at {path}.metric_name: {metric!r}.")
        cells.append(
            (
                _require_non_empty_string(mapping["implementation_name"], path=f"{path}.implementation_name"),
                _require_non_empty_string(mapping["case_name"], path=f"{path}.case_name"),
                cast(MetricName, metric),
            )
        )
    if len(set(cells)) != len(cells):
        raise BenchmarkJsonError("Manifest expected_cells must not contain duplicates.")
    return tuple(cells)


def _validate_cell(cell: BenchmarkCell) -> None:
    """Validate one public benchmark cell tuple."""
    if (
        not isinstance(cell, tuple)
        or len(cell) != 3
        or not isinstance(cell[0], str)
        or not cell[0]
        or not isinstance(cell[1], str)
        or not cell[1]
        or cell[2] not in KNOWN_METRICS
    ):
        raise ValueError(f"Invalid benchmark matrix cell: {cell!r}.")


def _require_mapping(value: object, *, path: str) -> Mapping[str, object]:
    """Return a string-keyed mapping or raise a manifest error."""
    if not isinstance(value, Mapping):
        raise BenchmarkJsonError(f"Expected mapping at {path}, got {type(value).__name__}.")
    if any(not isinstance(key, str) for key in value):
        raise BenchmarkJsonError(f"Expected string keys at {path}.")
    return cast(Mapping[str, object], value)


def _require_exact_keys(value: Mapping[str, object], expected: frozenset[str], *, path: str) -> None:
    """Require an exact set of manifest object keys."""
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unknown:
            details.append(f"unknown {', '.join(unknown)}")
        raise BenchmarkJsonError(f"Invalid keys at {path}: {'; '.join(details)}.")


def _require_list(value: object, *, path: str) -> list[object]:
    """Return a list or raise a manifest error."""
    if not isinstance(value, list):
        raise BenchmarkJsonError(f"Expected list at {path}, got {type(value).__name__}.")
    return value


def _require_string(value: object, *, path: str) -> str:
    """Return a string or raise a manifest error."""
    if not isinstance(value, str):
        raise BenchmarkJsonError(f"Expected string at {path}, got {type(value).__name__}.")
    return value


def _require_non_empty_string(value: object, *, path: str) -> str:
    """Return a non-empty string or raise a manifest error."""
    result = _require_string(value, path=path)
    if not result:
        raise BenchmarkJsonError(f"Expected non-empty string at {path}.")
    return result


def _require_optional_string(value: object, *, path: str) -> str | None:
    """Return a non-empty optional string or raise a manifest error."""
    if value is None:
        return None
    return _require_non_empty_string(value, path=path)


def _require_int(value: object, *, path: str) -> int:
    """Return an integer or raise a manifest error."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchmarkJsonError(f"Expected integer at {path}, got {type(value).__name__}.")
    return value


def _require_positive_int(value: object, *, path: str) -> int:
    """Return a positive integer or raise a manifest error."""
    result = _require_int(value, path=path)
    if result <= 0:
        raise BenchmarkJsonError(f"Expected positive integer at {path}.")
    return result


def _require_non_negative_int(value: object, *, path: str) -> int:
    """Return a non-negative integer or raise a manifest error."""
    result = _require_int(value, path=path)
    if result < 0:
        raise BenchmarkJsonError(f"Expected non-negative integer at {path}.")
    return result


def _require_optional_int(value: object, *, path: str) -> int | None:
    """Return an optional integer or raise a manifest error."""
    if value is None:
        return None
    return _require_int(value, path=path)


def _require_non_negative_float(value: object, *, path: str) -> float:
    """Return a finite non-negative number or raise a manifest error."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BenchmarkJsonError(f"Expected numeric value at {path}.")
    result = float(value)
    if not 0.0 <= result < float("inf"):
        raise BenchmarkJsonError(f"Expected finite non-negative value at {path}.")
    return result


def _require_string_list(value: object, *, path: str, non_empty: bool = False) -> list[str]:
    """Return a list of strings or raise a manifest error."""
    payload = _require_list(value, path=path)
    if non_empty and not payload:
        raise BenchmarkJsonError(f"Expected non-empty list at {path}.")
    return [_require_non_empty_string(item, path=f"{path}[{index}]") for index, item in enumerate(payload)]


def _validate_timestamp(value: str, *, field_name: str) -> None:
    """Validate a timezone-aware ISO 8601 timestamp."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone.")


def _validate_manifest_timestamp(value: str, *, path: str) -> None:
    """Validate a manifest timestamp with a package-specific error."""
    try:
        _validate_timestamp(value, field_name=path)
    except ValueError as exc:
        raise BenchmarkJsonError(str(exc)) from exc


def _validate_fingerprint(value: str, *, field_name: str) -> None:
    """Validate a SHA-256 environment fingerprint."""
    prefix = "sha256:"
    digest = value.removeprefix(prefix)
    invalid_character = any(character not in "0123456789abcdef" for character in digest)
    if not value.startswith(prefix) or len(digest) != 64 or invalid_character:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 fingerprint.")


def _validate_manifest_fingerprint(value: str, *, path: str) -> None:
    """Validate a manifest fingerprint with a package-specific error."""
    try:
        _validate_fingerprint(value, field_name=path)
    except ValueError as exc:
        raise BenchmarkJsonError(str(exc)) from exc


def _utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
