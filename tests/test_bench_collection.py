"""Tests for repeated benchmark collection manifests."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import benchmatrix.bench_collection as collection_module
from benchmatrix import (
    BenchmarkCollectionError,
    BenchmarkJsonError,
    BenchmarkRunGroup,
    BenchmarkRunRecord,
    EvidencePolicy,
    MetricName,
    collect_benchmark_runs,
    load_benchmark_run_group,
)
from benchmatrix.bench_collection import CollectionRunStatus

pytestmark = pytest.mark.unit

_ValueFactory = Callable[[int, Path], tuple[int, dict[str, object] | None]]


def _run_payload(
    value: float,
    *,
    case_name: str = "small",
    system: str = "Linux",
    python_version: str = "3.14.6",
    commit: str = "abc123",
) -> dict[str, object]:
    """Return one complete latency-only benchmark run."""
    return {
        "version": "5.2.3",
        "commit_info": {"id": commit},
        "machine_info": {
            "system": system,
            "release": "6.8.0",
            "machine": "x86_64",
            "python_implementation": "CPython",
            "python_version": python_version,
            "python_compiler": "GCC 14",
            "cpu": {
                "bits": 64,
                "brand_raw": "Example CPU",
                "vendor_id_raw": "ExampleVendor",
                "count": 8,
                "flags": ["avx2", "sse4"],
            },
        },
        "benchmarks": [
            {
                "name": f"test_benchmark[impl-{case_name}]",
                "extra_info": {
                    "benchmatrix_producer": "benchmatrix",
                    "benchmatrix_schema_version": 1,
                    "metric_name": "single_call_latency",
                    "implementation_name": "impl",
                    "case_name": case_name,
                    "case_fresh_inputs": False,
                },
                "stats": {
                    "mean": value,
                    "median": value,
                    "min": value,
                    "rounds": 5,
                    "iterations": 1,
                    "data": [value * 0.98, value * 0.99, value, value * 1.01, value * 1.02],
                },
            }
        ],
    }


def _install_runner(
    monkeypatch: pytest.MonkeyPatch,
    factory: _ValueFactory,
) -> list[tuple[str, ...]]:
    """Install a deterministic subprocess runner that writes benchmark JSON."""
    commands: list[tuple[str, ...]] = []

    def runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert cwd == Path.cwd().resolve()
        frozen = tuple(command)
        commands.append(frozen)
        output_argument = next(argument for argument in frozen if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        returncode, payload = factory(len(commands), output_path)
        if payload is not None:
            _ = output_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), returncode)

    monkeypatch.setattr(collection_module.subprocess, "run", runner)
    return commands


def test_collect_benchmark_runs_writes_and_loads_complete_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = _install_runner(
        monkeypatch,
        lambda index, _path: (0, _run_payload(1.0 + index / 100.0)),
    )
    output = tmp_path / "baseline"

    group = collect_benchmark_runs(("uv", "run", "pytest", "benchmarks.py"), output, run_count=3)
    loaded = load_benchmark_run_group(output)

    assert isinstance(group, BenchmarkRunGroup)
    assert group.is_complete is True
    assert group.successful_count == 3
    assert group.failed_count == 0
    assert group.attempted_count == 3
    assert group.failed_records == ()
    assert group.command == ("uv", "run", "pytest", "benchmarks.py")
    assert group.commit == "abc123"
    assert group.environment_fingerprint is not None
    assert group.environment_fingerprint.startswith("sha256:")
    assert group.expected_cells == (("impl", "small", "single_call_latency"),)
    assert [record.path.name for record in group.records] == [
        "run-001.json",
        "run-002.json",
        "run-003.json",
    ]
    assert all(record.status == "succeeded" for record in group.records)
    assert all(command[-1].startswith("--benchmark-json=") for command in commands)

    assert loaded.is_complete is True
    assert loaded.command == group.command
    assert loaded.commit == group.commit
    assert loaded.environment_fingerprint == group.environment_fingerprint
    assert [run.source for run in loaded.runs] == [record.path for record in loaded.records]

    manifest = cast(dict[str, object], json.loads((output / "benchmatrix-manifest.json").read_text()))
    records = cast(list[dict[str, object]], manifest["runs"])
    assert records[0]["path"] == "run-001.json"
    assert manifest["requested_runs"] == 3
    assert manifest["kind"] == "benchmark_run_group"


def test_collect_defaults_to_five_successful_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = _install_runner(
        monkeypatch,
        lambda index, _path: (0, _run_payload(1.0 + index / 100.0)),
    )

    group = collect_benchmark_runs(("pytest",), tmp_path / "default")

    assert group.requested_runs == 5
    assert group.successful_count == 5
    assert len(commands) == 5


def test_collect_records_command_and_matrix_failures_without_discarding_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def factory(index: int, _path: Path) -> tuple[int, dict[str, object] | None]:
        if index == 1:
            return 0, _run_payload(1.0)
        if index == 2:
            return 7, None
        return 0, _run_payload(1.0, case_name="large")

    _install_runner(monkeypatch, factory)

    group = collect_benchmark_runs(("pytest", "benchmarks.py"), tmp_path / "partial", run_count=3)
    loaded = load_benchmark_run_group(group.manifest_path)

    assert group.is_complete is False
    assert group.successful_count == 1
    assert group.failed_count == 2
    assert [record.status for record in group.records] == ["succeeded", "failed", "failed"]
    assert group.records[1].returncode == 7
    assert group.records[1].error == "Benchmark command exited with status 7."
    assert group.records[2].returncode == 0
    assert group.records[2].error == "Benchmark matrix cells differ from the first successful run."
    assert loaded.successful_count == 1
    assert loaded.failed_count == 2


def test_collect_rejects_commit_and_blocking_environment_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = (
        _run_payload(1.0),
        _run_payload(1.0, commit="different"),
        _run_payload(1.0, system="Darwin"),
    )
    _install_runner(monkeypatch, lambda index, _path: (0, payloads[index - 1]))

    group = collect_benchmark_runs(("pytest",), tmp_path / "incompatible", run_count=3)

    assert group.successful_count == 1
    assert "commit differs" in cast(str, group.records[1].error)
    assert "environment is incompatible" in cast(str, group.records[2].error)
    assert "os.system" in cast(str, group.records[2].error)


def test_collect_accepts_warning_level_environment_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = (
        _run_payload(1.0),
        _run_payload(1.0, python_version="3.14.7"),
    )
    _install_runner(monkeypatch, lambda index, _path: (0, payloads[index - 1]))

    group = collect_benchmark_runs(("pytest",), tmp_path / "warnings", run_count=2)
    loaded = load_benchmark_run_group(group.manifest_path)

    assert group.is_complete is True
    assert group.records[1].warnings
    assert group.records[1].warnings[0].startswith("python.version:")
    assert loaded.successful_count == 2


@pytest.mark.parametrize(
    "command",
    [
        (),
        ("pytest", "--benchmark-json", "result.json"),
        ("pytest", "--benchmark-json=result.json"),
    ],
)
def test_collect_rejects_invalid_commands(tmp_path: Path, command: tuple[str, ...]) -> None:
    with pytest.raises(BenchmarkCollectionError):
        _ = collect_benchmark_runs(command, tmp_path / "runs", run_count=1)


@pytest.mark.parametrize("run_count", [0, -1, True, 1.5])
def test_collect_rejects_invalid_run_counts(
    tmp_path: Path,
    run_count: object,
) -> None:
    with pytest.raises(BenchmarkCollectionError, match="positive integer"):
        _ = collect_benchmark_runs(
            ("pytest",),
            tmp_path / "runs",
            run_count=cast(int, run_count),
        )


def test_collect_rejects_nonempty_output_directory(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    _ = (output / "keep.txt").write_text("user data", encoding="utf-8")

    with pytest.raises(BenchmarkCollectionError, match="not empty"):
        _ = collect_benchmark_runs(("pytest",), output, run_count=1)

    assert (output / "keep.txt").read_text(encoding="utf-8") == "user data"


def test_run_group_compare_to_uses_successful_repeated_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(monkeypatch, lambda index, _path: (0, _run_payload(1.0 + index / 100.0)))
    baseline = collect_benchmark_runs(("pytest",), tmp_path / "baseline", run_count=2)
    _install_runner(monkeypatch, lambda index, _path: (0, _run_payload(1.2 + index / 100.0)))
    candidate = collect_benchmark_runs(("pytest",), tmp_path / "candidate", run_count=2)

    comparison = baseline.compare_to(
        candidate,
        evidence_policy=EvidencePolicy(minimum_runs=2, minimum_samples_per_run=5),
    )

    assert comparison.has_regressions is True
    assert comparison.regressed[0].implementation_name == "impl"


def test_load_manifest_rejects_tampered_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    group = collect_benchmark_runs(("pytest",), tmp_path / "runs", run_count=1)
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    records = cast(list[dict[str, object]], manifest["runs"])
    records[0]["environment_fingerprint"] = "sha256:" + "0" * 64
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match="fingerprint does not match"):
        _ = load_benchmark_run_group(group.manifest_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("producer", "other", "Unsupported producer"),
        ("kind", "other", "Unsupported benchmark run-group"),
        ("schema_version", 3, "Unsupported benchmark run-group manifest schema"),
        ("created_at", "yesterday", "ISO 8601"),
        ("environment_fingerprint", "bad", "SHA-256"),
        ("requested_runs", 0, "positive integer"),
    ],
)
def test_load_manifest_rejects_invalid_root_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    group = collect_benchmark_runs(("pytest",), tmp_path / field, run_count=1)
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    manifest[field] = value
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_benchmark_run_group(group.manifest_path)


def test_load_manifest_rejects_unknown_keys_and_unsafe_run_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    group = collect_benchmark_runs(("pytest",), tmp_path / "runs", run_count=1)
    original = cast(dict[str, object], json.loads(group.manifest_path.read_text()))

    unknown = dict(original)
    unknown["surprise"] = True
    _ = group.manifest_path.write_text(json.dumps(unknown), encoding="utf-8")
    with pytest.raises(BenchmarkJsonError, match="unknown surprise"):
        _ = load_benchmark_run_group(group.manifest_path)

    records = cast(list[dict[str, object]], original["runs"])
    records[0]["path"] = "../outside.json"
    _ = group.manifest_path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(BenchmarkJsonError, match="relative in-directory"):
        _ = load_benchmark_run_group(group.manifest_path)


def test_load_manifest_rejects_duplicate_run_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(monkeypatch, lambda index, _path: (0, _run_payload(1.0 + index / 100)))
    group = collect_benchmark_runs(("pytest",), tmp_path / "runs", run_count=2)
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    records = cast(list[dict[str, object]], manifest["runs"])
    records[1]["path"] = records[0]["path"]
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match="run paths must be unique"):
        _ = load_benchmark_run_group(group.manifest_path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"index": 0}, "positive integer"),
        ({"status": "other"}, "Unsupported benchmark collection status"),
        ({"returncode": True}, "returncode"),
        ({"started_at": "2026-07-30T12:00:00"}, "timezone"),
        ({"duration_seconds": -1.0}, "non-negative"),
        ({"warnings": ("",)}, "non-empty strings"),
        ({"commit": ""}, "non-empty string"),
        ({"environment_fingerprint": "bad"}, "SHA-256"),
        ({"returncode": 1}, "returncode 0"),
        ({"error": "unexpected"}, "no error"),
        ({"environment_fingerprint": None}, "environment fingerprint"),
    ],
)
def test_run_record_rejects_invalid_success_fields(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    record = BenchmarkRunRecord(
        index=1,
        status="succeeded",
        path=tmp_path / "run.json",
        returncode=0,
        started_at="2026-07-30T12:00:00Z",
        duration_seconds=1,
        environment_fingerprint="sha256:" + "0" * 64,
    )

    with pytest.raises((TypeError, ValueError), match=message):
        _ = replace(record, **changes)


def test_failed_run_record_requires_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty error"):
        _ = BenchmarkRunRecord(
            index=1,
            status="failed",
            path=tmp_path / "run.json",
            returncode=None,
            started_at="2026-07-30T12:00:00Z",
            duration_seconds=0.0,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"command": ()}, "command"),
        ({"created_at": "today"}, "ISO 8601"),
        ({"commit": ""}, "commit"),
        ({"environment_fingerprint": "bad"}, "SHA-256"),
        ({"requested_runs": True}, "must be an integer"),
        ({"requested_runs": 0}, "must be positive"),
        ({"requested_runs": 1}, "more successful runs"),
        ({"expected_cells": (("impl", "small", "single_call_latency"),) * 2}, "duplicates"),
        ({"expected_cells": (("impl", "small", "other"),)}, "Invalid benchmark matrix cell"),
        ({"expected_cells": ()}, "requires expected cells"),
        ({"runs": ()}, "align with successful records"),
    ],
)
def test_run_group_rejects_invalid_invariants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
    message: str,
) -> None:
    _install_runner(monkeypatch, lambda index, _path: (0, _run_payload(1.0 + index / 100.0)))
    group = collect_benchmark_runs(("pytest",), tmp_path / "valid", run_count=2)

    with pytest.raises((TypeError, ValueError), match=message):
        _ = replace(group, **changes)


def test_run_group_rejects_noncontiguous_records_and_changed_run_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(monkeypatch, lambda index, _path: (0, _run_payload(1.0 + index / 100.0)))
    group = collect_benchmark_runs(("pytest",), tmp_path / "valid", run_count=2)
    noncontiguous = (replace(group.records[0], index=2), group.records[1])

    with pytest.raises(ValueError, match="contiguous"):
        _ = replace(group, records=noncontiguous)
    with pytest.raises(ValueError, match="does not match"):
        _ = replace(
            group,
            expected_cells=(("impl", "other", "single_call_latency"),),
        )
    with pytest.raises(TypeError, match="BenchmarkRun values"):
        _ = replace(group, runs=cast(tuple[object, ...], (object(), object())))


def test_run_group_without_success_cannot_define_anchor(
    tmp_path: Path,
) -> None:
    failed = BenchmarkRunRecord(
        index=1,
        status="failed",
        path=tmp_path / "run.json",
        returncode=1,
        started_at="2026-07-30T12:00:00Z",
        duration_seconds=0.1,
        error="failed",
    )

    with pytest.raises(ValueError, match="cannot define an anchor"):
        _ = BenchmarkRunGroup(
            runs=(),
            records=(failed,),
            command=("pytest",),
            created_at="2026-07-30T12:00:00Z",
            cwd=tmp_path,
            commit="abc123",
            environment_fingerprint=None,
            expected_cells=(),
            requested_runs=1,
            manifest_path=tmp_path / "benchmatrix-manifest.json",
        )


def test_collect_records_os_and_invalid_json_errors_then_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        assert check is False
        assert cwd == Path.cwd().resolve()
        calls += 1
        if calls == 1:
            raise OSError("executable unavailable")
        output_argument = next(argument for argument in command if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        if calls == 2:
            _ = output_path.write_text("not json", encoding="utf-8")
        else:
            _ = output_path.write_text(json.dumps(_run_payload(1.0)), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0)

    monkeypatch.setattr(collection_module.subprocess, "run", runner)
    group = collect_benchmark_runs(("pytest",), tmp_path / "recovered", run_count=3)

    assert group.successful_count == 1
    assert "executable unavailable" in cast(str, group.records[0].error)
    assert "Invalid JSON" in cast(str, group.records[1].error)
    assert group.records[2].status == "succeeded"


def test_collect_rejects_non_json_environment_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _run_payload(1.0)
    payload["dependencies"] = {"broken": float("nan")}
    _install_runner(monkeypatch, lambda _index, _path: (0, payload))

    group = collect_benchmark_runs(("pytest",), tmp_path / "bad-metadata", run_count=1)

    assert group.successful_count == 0
    assert "non-standard numeric constant" in cast(str, group.records[0].error)


def test_collect_rejects_output_path_that_is_a_file(tmp_path: Path) -> None:
    output = tmp_path / "file"
    _ = output.write_text("keep", encoding="utf-8")

    with pytest.raises(BenchmarkCollectionError, match="not a directory"):
        _ = collect_benchmark_runs(("pytest",), output, run_count=1)


def test_load_group_reports_missing_and_malformed_manifest(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkJsonError, match="Could not read"):
        _ = load_benchmark_run_group(tmp_path / "missing")

    malformed = tmp_path / "malformed.json"
    _ = malformed.write_text("{", encoding="utf-8")
    with pytest.raises(BenchmarkJsonError, match="Invalid JSON"):
        _ = load_benchmark_run_group(malformed)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("command", [], "non-empty list"),
        ("command", [""], "non-empty string"),
        ("cwd", 7, "Expected string"),
        ("commit", "", "non-empty string"),
        ("expected_cells", "bad", "Expected list"),
        ("runs", "bad", "Expected list"),
    ],
)
def test_load_manifest_rejects_invalid_container_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    group = collect_benchmark_runs(("pytest",), tmp_path / field, run_count=1)
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    manifest[field] = value
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_benchmark_run_group(group.manifest_path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        ({"status": "unknown"}, "Unsupported collection status"),
        ({"path": "/tmp/run.json"}, "relative in-directory"),
        ({"returncode": True}, "Expected integer"),
        ({"duration_seconds": -1}, "finite non-negative"),
        ({"warnings": [""]}, "non-empty string"),
        ({"environment_fingerprint": "bad"}, "SHA-256"),
    ],
)
def test_load_manifest_rejects_invalid_record_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: dict[str, object],
    message: str,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    group = collect_benchmark_runs(("pytest",), tmp_path / "runs", run_count=1)
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    records = cast(list[dict[str, object]], manifest["runs"])
    records[0].update(mutate)
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_benchmark_run_group(group.manifest_path)


@pytest.mark.parametrize(
    ("cell", "message"),
    [
        ({"implementation_name": "", "case_name": "small", "metric_name": "single_call_latency"}, "non-empty"),
        ({"implementation_name": "impl", "case_name": "small", "metric_name": "unknown"}, "Unsupported metric"),
        ({"implementation_name": "impl", "case_name": "small"}, "missing metric_name"),
    ],
)
def test_load_manifest_rejects_invalid_expected_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cell: dict[str, object],
    message: str,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    group = collect_benchmark_runs(("pytest",), tmp_path / "runs", run_count=1)
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    manifest["expected_cells"] = [cell]
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_benchmark_run_group(group.manifest_path)


def test_resume_continues_unrecorded_attempts_without_overwriting_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "interrupted"
    calls = 0

    def interrupting_runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        assert check is False
        assert cwd == Path.cwd().resolve()
        calls += 1
        output_argument = next(argument for argument in command if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        if calls == 3:
            _ = output_path.write_text("partial output", encoding="utf-8")
            _ = output_path.with_name("run-003-attempt-02.json").write_text(
                "another partial output",
                encoding="utf-8",
            )
            raise KeyboardInterrupt
        _ = output_path.write_text(json.dumps(_run_payload(1.0 + calls / 100.0)), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0)

    monkeypatch.setattr(collection_module.subprocess, "run", interrupting_runner)
    with pytest.raises(KeyboardInterrupt):
        _ = collect_benchmark_runs(("pytest", "benchmarks.py"), output, run_count=4)

    interrupted = load_benchmark_run_group(output)
    created_at = interrupted.created_at
    assert interrupted.attempted_count == 2
    assert interrupted.pending_count == 2
    assert interrupted.remaining_count == 2
    assert (output / "run-003.json").read_text(encoding="utf-8") == "partial output"

    commands = _install_runner(
        monkeypatch,
        lambda index, _path: (0, _run_payload(1.1 + index / 100.0)),
    )
    resumed = collect_benchmark_runs((), output, resume=True)
    loaded = load_benchmark_run_group(output)

    assert resumed.is_complete is True
    assert resumed.created_at == created_at
    assert resumed.command == ("pytest", "benchmarks.py")
    assert resumed.attempted_count == 4
    assert resumed.pending_count == 0
    assert resumed.retry_count == 0
    assert resumed.remaining_count == 0
    assert resumed.records[2].path.name == "run-003-attempt-03.json"
    assert resumed.records[3].path.name == "run-004.json"
    assert (output / "run-003.json").read_text(encoding="utf-8") == "partial output"
    assert (output / "run-003-attempt-02.json").read_text(encoding="utf-8") == "another partial output"
    assert len(commands) == 2
    assert loaded == resumed


def test_retry_appends_attempt_and_preserves_failed_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def initial_factory(index: int, _path: Path) -> tuple[int, dict[str, object] | None]:
        if index == 2:
            return 7, None
        return 0, _run_payload(1.0 + index / 100.0)

    _install_runner(monkeypatch, initial_factory)
    output = tmp_path / "retry"
    initial = collect_benchmark_runs(("pytest",), output, run_count=3)
    failed = initial.records[1]

    commands = _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.1)))
    retried = collect_benchmark_runs((), output, resume=True, retry_failed=True)
    loaded = load_benchmark_run_group(output)

    assert retried.is_complete is True
    assert retried.successful_count == 3
    assert retried.failed_count == 1
    assert retried.attempted_count == 4
    assert retried.retry_count == 1
    assert retried.remaining_count == 0
    assert retried.records[1] == failed
    assert retried.records[3].status == "succeeded"
    assert retried.records[3].path.name == "run-004.json"
    assert len(commands) == 1
    assert loaded == retried
    manifest = cast(dict[str, object], json.loads(retried.manifest_path.read_text()))
    assert manifest["schema_version"] == 2


def test_each_retry_invocation_is_bounded_and_retains_retry_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(
        monkeypatch,
        lambda index, _path: (0, _run_payload(1.0)) if index == 1 else (1, None),
    )
    output = tmp_path / "bounded"
    initial = collect_benchmark_runs(("pytest",), output, run_count=2)
    assert initial.remaining_count == 1

    first_retry_commands = _install_runner(monkeypatch, lambda _index, _path: (1, None))
    first_retry = collect_benchmark_runs((), output, resume=True, retry_failed=True)
    assert len(first_retry_commands) == 1
    assert first_retry.is_complete is False
    assert first_retry.retry_count == 1
    assert first_retry.remaining_count == 1
    assert first_retry.records[2].status == "failed"

    second_retry_commands = _install_runner(
        monkeypatch,
        lambda _index, _path: (0, _run_payload(1.1)),
    )
    second_retry = collect_benchmark_runs((), output, resume=True, retry_failed=True)
    assert len(second_retry_commands) == 1
    assert second_retry.is_complete is True
    assert second_retry.retry_count == 2
    assert second_retry.failed_count == 2
    assert [record.index for record in second_retry.records] == [1, 2, 3, 4]


def test_resume_reuses_original_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "cwd"
    calls = 0

    def runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        output_argument = next(argument for argument in command if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        if calls == 2:
            raise KeyboardInterrupt
        _ = output_path.write_text(json.dumps(_run_payload(1.0)), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0)

    monkeypatch.setattr(collection_module.subprocess, "run", runner)
    with pytest.raises(KeyboardInterrupt):
        _ = collect_benchmark_runs(("pytest",), output, run_count=2)

    original_cwd = Path.cwd().resolve()
    observed_directories: list[Path] = []

    def resumed_runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        observed_directories.append(cwd)
        output_argument = next(argument for argument in command if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        _ = output_path.write_text(json.dumps(_run_payload(1.1)), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0)

    monkeypatch.setattr(collection_module.subprocess, "run", resumed_runner)
    resumed = collect_benchmark_runs((), output, resume=True)

    assert resumed.is_complete is True
    assert observed_directories == [original_cwd]


def test_resume_validates_mode_command_count_directory_and_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    output = tmp_path / "validation"
    group = collect_benchmark_runs(("pytest", "benchmarks.py"), output, run_count=1)

    with pytest.raises(BenchmarkCollectionError, match="requires resume"):
        _ = collect_benchmark_runs((), output, retry_failed=True)
    with pytest.raises(BenchmarkCollectionError, match="does not match"):
        _ = collect_benchmark_runs(("pytest", "other.py"), output, resume=True)
    with pytest.raises(BenchmarkCollectionError, match="manifest target"):
        _ = collect_benchmark_runs((), output, run_count=2, resume=True)
    with pytest.raises(BenchmarkCollectionError, match="does not exist"):
        _ = collect_benchmark_runs((), tmp_path / "missing", resume=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(BenchmarkCollectionError, match="Could not resume collection"):
        _ = collect_benchmark_runs((), empty, resume=True)

    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    manifest["cwd"] = str(tmp_path / "unavailable")
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BenchmarkCollectionError, match="working directory is unavailable"):
        _ = collect_benchmark_runs((), output, resume=True)


def test_resume_complete_collection_is_a_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    output = tmp_path / "complete"
    initial = collect_benchmark_runs(("pytest",), output, run_count=1)

    def unexpected_runner(
        _command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError((check, cwd))

    monkeypatch.setattr(collection_module.subprocess, "run", unexpected_runner)
    resumed = collect_benchmark_runs(
        ("pytest",),
        output,
        run_count=1,
        resume=True,
        retry_failed=True,
    )

    assert resumed == initial


def test_loader_accepts_version_one_manifest_and_rejects_v1_retry_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    compatible = collect_benchmark_runs(("pytest",), tmp_path / "v1", run_count=1)
    payload = cast(dict[str, object], json.loads(compatible.manifest_path.read_text()))
    payload["schema_version"] = 1
    _ = compatible.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_benchmark_run_group(compatible.manifest_path).is_complete is True

    _install_runner(monkeypatch, lambda _index, _path: (1, None))
    retry_output = tmp_path / "v1-retry"
    _ = collect_benchmark_runs(("pytest",), retry_output, run_count=1)
    _install_runner(monkeypatch, lambda _index, _path: (0, _run_payload(1.0)))
    retried = collect_benchmark_runs((), retry_output, resume=True, retry_failed=True)
    retry_payload = cast(dict[str, object], json.loads(retried.manifest_path.read_text()))
    retry_payload["schema_version"] = 1
    _ = retried.manifest_path.write_text(json.dumps(retry_payload), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match="cannot contain retry attempts"):
        _ = load_benchmark_run_group(retried.manifest_path)


def test_public_collection_type_aliases_accept_documented_values() -> None:
    status: CollectionRunStatus = "succeeded"
    metric: MetricName = "single_call_latency"

    assert status == "succeeded"
    assert metric == "single_call_latency"
