"""Collect, persist, and load repeated pytest-benchmark runs."""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias, cast

from ._schema import (
    KNOWN_METRICS,
    PRODUCER,
    RUN_GROUP_KIND,
    RUN_GROUP_SCHEMA_READ_VERSIONS,
    RUN_GROUP_SCHEMA_VERSION,
    MetricName,
)
from .bench_compare import (
    BenchmarkRunComparison,
    EvidencePolicy,
    RegressionPolicy,
    RunCompatibilityPolicy,
    compare_benchmark_run_groups,
)
from .bench_results import BenchmarkRun, load_benchmark_run
from .exceptions import BenchmarkCollectionError, BenchmarkJsonError

CollectionRunStatus: TypeAlias = Literal["succeeded", "failed"]
BenchmarkCell: TypeAlias = tuple[str, str, MetricName]

RUN_GROUP_MANIFEST = "benchmatrix-manifest.json"

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
    ) -> BenchmarkRunComparison:
        """Compare this repeated baseline collection with a candidate.

        Args:
            candidate: Repeated candidate collection.
            compatibility_policy: Environment checks to apply.
            regression_policy: Thresholds used to classify cell changes.
            evidence_policy: Minimum repeated-run evidence to require.

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
    for position, record_payload in enumerate(record_payloads):
        record_path = f"manifest.runs[{position}]"
        record_mapping = _require_mapping(record_payload, path=record_path)
        _require_exact_keys(record_mapping, _RECORD_KEYS, path=record_path)
        record = _parse_record(record_mapping, manifest_path=manifest_path, path=record_path)
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
                completed = subprocess.run(argv, check=False, cwd=cwd)  # nosec B603
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
