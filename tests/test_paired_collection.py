"""Tests for balanced ordering and paired AB/BA collection."""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Protocol, cast

import pytest

import benchmatrix.bench_collection as collection_module
from benchmatrix import (
    BenchmarkCase,
    BenchmarkCollectionError,
    BenchmarkJsonError,
    BenchmarkPairedCollectionSnapshot,
    BenchmarkPairedRunGroup,
    BenchmarkPairedRunRecord,
    BenchmarkPairSchedule,
    BenchmarkRun,
    EvidencePolicy,
    InferencePolicy,
    balanced_cell_order,
    balanced_order_cycle_length,
    collect_paired_benchmark_runs,
    load_paired_benchmark_run_group,
    make_benchmark_parameters,
    make_paired_ab_ba_schedule,
)
from benchmatrix._collection_design import ORDER_INDEX_ENV, ORDER_SEED_ENV
from benchmatrix._schema import MetricName

pytestmark = pytest.mark.unit

_Cell = tuple[str, str, MetricName]
_PairedFactory = Callable[[str, int, int], tuple[int, dict[str, object] | None]]


class _ParameterSet(Protocol):
    """Subset of pytest's parameter wrapper needed by this module."""

    values: tuple[object, ...]


def _noop() -> None:
    """Do no work."""


def _payload(
    cells: Sequence[_Cell],
    *,
    value: float,
    commit: str,
) -> dict[str, object]:
    """Return a complete multi-cell pytest-benchmark payload."""
    benchmarks: list[dict[str, object]] = []
    for implementation_name, case_name, metric_name in cells:
        benchmarks.append(
            {
                "name": f"test_benchmark[{metric_name}::{implementation_name}::{case_name}]",
                "extra_info": {
                    "benchmatrix_producer": "benchmatrix",
                    "benchmatrix_schema_version": 1,
                    "metric_name": metric_name,
                    "implementation_name": implementation_name,
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
        )
    return {
        "version": "5.2.3",
        "commit_info": {"id": commit},
        "machine_info": {
            "system": "Linux",
            "release": "6.8.0",
            "machine": "x86_64",
            "python_implementation": "CPython",
            "python_version": "3.14.6",
            "python_compiler": "GCC 14",
            "cpu": {
                "bits": 64,
                "brand_raw": "Example CPU",
                "vendor_id_raw": "ExampleVendor",
                "count": 8,
                "flags": ["avx2", "sse4"],
            },
        },
        "benchmarks": benchmarks,
    }


def _install_paired_runner(
    monkeypatch: pytest.MonkeyPatch,
    factory: _PairedFactory,
) -> list[tuple[str, int, int, Path]]:
    """Install a subprocess double that observes collection-order metadata."""
    calls: list[tuple[str, int, int, Path]] = []

    def runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        variant = "baseline" if command[0] == "baseline-pytest" else "candidate"
        seed = int(os.environ[ORDER_SEED_ENV])
        order_index = int(os.environ[ORDER_INDEX_ENV])
        calls.append((variant, seed, order_index, cwd))
        output_argument = next(argument for argument in command if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        returncode, payload = factory(variant, order_index, len(calls))
        if payload is not None:
            _ = output_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), returncode)

    monkeypatch.setattr(collection_module.subprocess, "run", runner)
    return calls


def _failed_paired_group() -> BenchmarkPairedRunGroup:
    """Return a structurally valid group with one fully failed block."""
    schedule = make_paired_ab_ba_schedule(1, random_seed=0)[0]
    records = tuple(
        BenchmarkPairedRunRecord(
            index=index,
            pair_index=1,
            block_attempt=1,
            variant=variant,
            pair_order=schedule.pair_order,
            order_position=index,
            cell_order_index=1,
            status="failed",
            path=Path(f"failed-{variant}.json"),
            returncode=1,
            started_at="2026-08-01T00:00:00Z",
            duration_seconds=0.1,
            error="failed",
        )
        for index, variant in enumerate(schedule.variants, start=1)
    )
    return BenchmarkPairedRunGroup(
        runs=(),
        records=records,
        baseline_command=("baseline",),
        candidate_command=("candidate",),
        created_at="2026-08-01T00:00:00Z",
        baseline_cwd=Path.cwd(),
        candidate_cwd=Path.cwd(),
        baseline_commit=None,
        candidate_commit=None,
        baseline_environment_fingerprint=None,
        candidate_environment_fingerprint=None,
        expected_cells=(),
        requested_pairs=1,
        random_seed=0,
        manifest_path=Path("manifest.json"),
    )


@pytest.mark.parametrize("cell_count", [2, 4, 6])
def test_even_williams_schedule_balances_positions_and_predecessors(cell_count: int) -> None:
    metric: MetricName = "single_call_latency"
    cells: tuple[_Cell, ...] = tuple((f"impl-{index}", "case", metric) for index in range(cell_count))
    rows = [balanced_cell_order(cells, order_index=index + 1, random_seed=17) for index in range(cell_count)]

    assert balanced_order_cycle_length(cell_count) == cell_count
    for position in range(cell_count):
        assert {row[position] for row in rows} == set(cells)
    transitions = Counter((left, right) for row in rows for left, right in pairwise(row))
    assert set(transitions.values()) == {1}
    assert len(transitions) == cell_count * (cell_count - 1)


@pytest.mark.parametrize("cell_count", [3, 5])
def test_odd_williams_schedule_uses_reversed_cycle_for_carryover_balance(cell_count: int) -> None:
    metric: MetricName = "single_call_latency"
    cells: tuple[_Cell, ...] = tuple((f"impl-{index}", "case", metric) for index in range(cell_count))
    cycle = balanced_order_cycle_length(cell_count)
    rows = [balanced_cell_order(cells, order_index=index + 1, random_seed=31) for index in range(cycle)]

    assert cycle == 2 * cell_count
    for position in range(cell_count):
        assert Counter(row[position] for row in rows) == Counter(dict.fromkeys(cells, 2))
    transitions = Counter((left, right) for row in rows for left, right in pairwise(row))
    assert len(transitions) == cell_count * (cell_count - 1)
    assert len(set(transitions.values())) == 1


def test_harness_applies_collector_balanced_order_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    cells: tuple[_Cell, ...] = (
        ("impl-a", "small", "single_call_latency"),
        ("impl-a", "large", "single_call_latency"),
        ("impl-b", "small", "single_call_latency"),
        ("impl-b", "large", "single_call_latency"),
    )
    monkeypatch.setenv(ORDER_SEED_ENV, "47")
    monkeypatch.setenv(ORDER_INDEX_ENV, "3")

    parameters = make_benchmark_parameters(
        {"impl-a": _noop, "impl-b": _noop},
        {"small": BenchmarkCase("small"), "large": BenchmarkCase("large")},
        metrics=("single_call_latency",),
    )
    observed = tuple(
        cast(_Cell, (wrapped.values[1], wrapped.values[3], wrapped.values[0]))
        for parameter in parameters
        if (wrapped := cast(_ParameterSet, parameter))
    )

    assert observed == balanced_cell_order(cells, order_index=3, random_seed=47)


def test_harness_rejects_partial_or_invalid_order_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ORDER_SEED_ENV, "1")
    with pytest.raises(ValueError, match="must be set together"):
        _ = make_benchmark_parameters({"impl": _noop}, [BenchmarkCase("case")])

    monkeypatch.setenv(ORDER_INDEX_ENV, "zero")
    with pytest.raises(ValueError, match="decimal integers"):
        _ = make_benchmark_parameters({"impl": _noop}, [BenchmarkCase("case")])


def test_paired_schedule_alternates_orientation_deterministically() -> None:
    first = make_paired_ab_ba_schedule(8, random_seed=19, cell_count=4)
    repeated = make_paired_ab_ba_schedule(8, random_seed=19, cell_count=4)

    assert first == repeated
    assert all(left.pair_order != right.pair_order for left, right in pairwise(first))
    assert [entry.cell_order_index for entry in first] == [1, 1, 2, 2, 3, 3, 4, 4]
    assert sum(entry.pair_order == "AB" for entry in first) == 4
    assert sum(entry.pair_order == "BA" for entry in first) == 4


@pytest.mark.parametrize("cell_count", [1, 2, 3, 4, 5])
def test_paired_schedule_jointly_balances_every_row_and_orientation(cell_count: int) -> None:
    supercycle = collection_module.balanced_order_supercycle_length(cell_count)
    schedule = make_paired_ab_ba_schedule(
        supercycle,
        random_seed=47,
        cell_count=cell_count,
    )

    combinations = Counter((entry.cell_order_index, entry.pair_order) for entry in schedule)
    assert len(schedule) == supercycle
    assert combinations == Counter(
        {(row, orientation): 1 for row in range(1, supercycle // 2 + 1) for orientation in ("AB", "BA")}
    )
    assert all(left.pair_order != right.pair_order for left, right in pairwise(schedule))


@pytest.mark.parametrize(
    ("pair_count", "random_seed", "error", "message"),
    [
        (0, 0, ValueError, "positive integer"),
        (True, 0, ValueError, "positive integer"),
        (1, True, TypeError, "must be an integer"),
        (1, -1, ValueError, "non-negative"),
    ],
)
def test_paired_schedule_rejects_invalid_inputs(
    pair_count: object,
    random_seed: object,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        _ = make_paired_ab_ba_schedule(
            cast(int, pair_count),
            random_seed=cast(int, random_seed),
        )


@pytest.mark.parametrize(
    ("cell_count", "error", "message"),
    [
        (True, TypeError, "integer or None"),
        (0, ValueError, "positive when provided"),
        (-1, ValueError, "positive when provided"),
    ],
)
def test_paired_schedule_rejects_invalid_cell_count(
    cell_count: object,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        _ = make_paired_ab_ba_schedule(2, cell_count=cast(int, cell_count))


@pytest.mark.parametrize(
    ("cells", "order_index", "random_seed", "error", "message"),
    [
        ((("impl", "case", "unknown"),), 1, 0, ValueError, "Invalid benchmark matrix cell"),
        ((("impl", "case", "single_call_latency"),) * 2, 1, 0, ValueError, "must not contain duplicates"),
        ((("impl", "case", "single_call_latency"),), 0, 0, ValueError, "must be positive"),
        ((("impl", "case", "single_call_latency"),), cast(int, True), 0, TypeError, "must be an integer"),
        ((("impl", "case", "single_call_latency"),), 1, -1, ValueError, "must be non-negative"),
        ((("impl", "case", "single_call_latency"),), 1, cast(int, True), TypeError, "must be an integer"),
    ],
)
def test_balanced_cell_order_rejects_invalid_inputs(
    cells: object,
    order_index: int,
    random_seed: int,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        _ = balanced_cell_order(
            cast(Sequence[_Cell], cells),
            order_index=order_index,
            random_seed=random_seed,
        )


@pytest.mark.parametrize(
    ("cell_count", "error", "message"),
    [(True, TypeError, "must be an integer"), (-1, ValueError, "non-negative")],
)
def test_balanced_order_cycle_length_rejects_invalid_input(
    cell_count: object,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        _ = balanced_order_cycle_length(cast(int, cell_count))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"pair_index": 0}, "pair_index"),
        ({"variant": "other"}, "variant"),
        ({"pair_order": "AA"}, "order"),
        ({"order_position": 2}, "inconsistent"),
        ({"cell_order_index": 0}, "positive integer"),
        ({"status": "other"}, "status"),
        ({"returncode": True}, "returncode"),
        ({"duration_seconds": -1}, "duration_seconds"),
        ({"warnings": ("",)}, "warnings"),
        ({"commit": ""}, "commit"),
        ({"environment_fingerprint": "bad"}, "SHA-256"),
        ({"error": None}, "non-empty error"),
    ],
)
def test_paired_record_rejects_invalid_invariants(changes: dict[str, object], message: str) -> None:
    schedule = make_paired_ab_ba_schedule(1)[0]
    variant = schedule.variants[0]
    record = BenchmarkPairedRunRecord(
        index=1,
        pair_index=1,
        block_attempt=1,
        variant=variant,
        pair_order=schedule.pair_order,
        order_position=1,
        cell_order_index=1,
        status="failed",
        path=Path("run.json"),
        returncode=1,
        started_at="2026-08-01T00:00:00Z",
        duration_seconds=0.1,
        error="failed",
    )

    with pytest.raises((TypeError, ValueError), match=message):
        _ = replace(record, **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"pair_index": 0}, "pair_index"),
        ({"pair_order": "AA"}, "order"),
        ({"cell_order_index": 0}, "positive integer"),
    ],
)
def test_pair_schedule_record_rejects_invalid_invariants(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _ = BenchmarkPairSchedule(
            pair_index=cast(int, changes.get("pair_index", 1)),
            pair_order=cast(collection_module.PairedOrder, changes.get("pair_order", "AB")),
            cell_order_index=cast(int, changes.get("cell_order_index", 1)),
        )


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        ({"baseline_command": ()}, ValueError, "baseline_command"),
        ({"candidate_command": ("",)}, ValueError, "candidate_command"),
        ({"created_at": "not-a-timestamp"}, ValueError, "created_at"),
        ({"requested_pairs": True}, TypeError, "requested_pairs"),
        ({"requested_pairs": 0}, ValueError, "requested_pairs"),
        ({"random_seed": True}, TypeError, "random_seed"),
        ({"random_seed": -1}, ValueError, "random_seed"),
        ({"automatic_pairs": 1}, TypeError, "automatic_pairs"),
        ({"baseline_commit": ""}, ValueError, "baseline_commit"),
        ({"baseline_environment_fingerprint": "bad"}, ValueError, "SHA-256"),
        (
            {"expected_cells": (("impl", "case", "single_call_latency"),)},
            ValueError,
            "without successful runs",
        ),
        (
            {"expected_cells": (("impl", "case", "unknown"),)},
            ValueError,
            "Invalid benchmark matrix cell",
        ),
        (
            {
                "expected_cells": (
                    ("impl", "case", "single_call_latency"),
                    ("impl", "case", "single_call_latency"),
                )
            },
            ValueError,
            "duplicates",
        ),
    ],
)
def test_paired_group_rejects_invalid_root_invariants(
    changes: dict[str, object],
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        _ = replace(_failed_paired_group(), **changes)


def test_empty_automatic_group_requires_provisional_target() -> None:
    with pytest.raises(ValueError, match="automatic requested_pairs"):
        _ = replace(_failed_paired_group(), automatic_pairs=True)


def test_paired_group_rejects_invalid_record_structure() -> None:
    group = _failed_paired_group()
    first, second = group.records

    with pytest.raises(ValueError, match="runs must align"):
        _ = replace(group, runs=(cast(BenchmarkRun, object()),))
    with pytest.raises(ValueError, match="indexes must be contiguous"):
        _ = replace(group, records=(replace(first, index=2), second))
    with pytest.raises(ValueError, match="exceeds requested_pairs"):
        _ = replace(group, requested_pairs=1, records=(replace(first, pair_index=2, cell_order_index=2),))
    duplicate_variant = replace(first, index=2)
    with pytest.raises(ValueError, match="cannot repeat a variant"):
        _ = replace(group, records=(first, duplicate_variant))
    skipped_attempt = (
        first,
        second,
        replace(first, index=3, block_attempt=3),
        replace(second, index=4, block_attempt=3),
    )
    with pytest.raises(ValueError, match="contiguous per pair"):
        _ = replace(group, records=skipped_attempt)
    opposite_seed = next(
        seed
        for seed in range(1, 100)
        if make_paired_ab_ba_schedule(1, random_seed=seed)[0].pair_order != first.pair_order
    )
    with pytest.raises(ValueError, match="deterministic schedule"):
        _ = replace(group, random_seed=opposite_seed)


def test_collect_paired_runs_writes_loads_and_compares_atomic_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    calls = _install_paired_runner(
        monkeypatch,
        lambda variant, pair_index, call_index: (
            0,
            _payload(
                cells,
                value=1.0 + call_index / 100.0,
                commit="baseline-commit" if variant == "baseline" else "candidate-commit",
            ),
        ),
    )
    output = tmp_path / "paired"

    group = collect_paired_benchmark_runs(
        ("baseline-pytest", "benchmarks.py"),
        ("candidate-pytest", "benchmarks.py"),
        output,
        pair_count=4,
        random_seed=19,
    )
    loaded = load_paired_benchmark_run_group(output)

    assert isinstance(group, BenchmarkPairedRunGroup)
    assert group.is_complete is True
    assert group.complete_pair_count == 4
    assert group.orphan_success_count == 0
    assert group.baseline_commit == "baseline-commit"
    assert group.candidate_commit == "candidate-commit"
    assert [pair.pair_index for pair in group.complete_pairs] == [1, 2, 3, 4]
    assert len(group.baseline_runs) == len(group.candidate_runs) == 4
    expected_variants = [
        variant for entry in make_paired_ab_ba_schedule(4, random_seed=19, cell_count=1) for variant in entry.variants
    ]
    assert [variant for variant, _seed, _index, _cwd in calls] == expected_variants
    assert [index for _variant, _seed, index, _cwd in calls] == [1] * 8
    assert all(seed == 19 for _variant, seed, _index, _cwd in calls)
    assert loaded == group
    assert group.order_supercycle_length == 2
    assert group.is_jointly_balanced is True

    comparison = group.compare(
        evidence_policy=EvidencePolicy(minimum_runs=1, minimum_samples_per_run=0),
        inference_policy=InferencePolicy(method="legacy_consistency"),
    )
    assert comparison.design == "paired"

    forwarded: dict[str, object] = {}

    def capture_compare(*_args: object, **kwargs: object) -> object:
        forwarded.update(kwargs)
        return comparison

    monkeypatch.setattr(collection_module, "compare_paired_benchmark_run_groups", capture_compare)
    assert group.compare() is comparison
    assert forwarded["pair_strata"] == tuple(pair.pair_order for pair in group.complete_pairs)
    assert forwarded["precision_pair_count_multiple"] == group.order_supercycle_length

    with pytest.raises(TypeError, match="runs must contain BenchmarkRun"):
        _ = replace(group, runs=(cast(BenchmarkRun, object()), *group.runs[1:]))
    first_row = group.runs[0].rows[0]
    mismatched_row = replace(
        first_row,
        case_name="other",
        extra_info={**first_row.extra_info, "case_name": "other"},
    )
    mismatched_run = replace(group.runs[0], rows=(mismatched_row,))
    with pytest.raises(ValueError, match="run matrix does not match"):
        _ = replace(group, runs=(mismatched_run, *group.runs[1:]))
    with pytest.raises(ValueError, match="commits do not match"):
        _ = replace(group, baseline_commit="different-commit")
    with pytest.raises(ValueError, match="fingerprint does not match"):
        _ = replace(group, baseline_environment_fingerprint="sha256:" + "0" * 64)

    pair_one = tuple(record for record in group.records if record.pair_index == 1)
    pair_two = tuple(record for record in group.records if record.pair_index == 2)
    pair_three = tuple(record for record in group.records if record.pair_index == 3)
    partial_then_later = tuple(
        replace(record, index=index) for index, record in enumerate((pair_one[0], *pair_two), start=1)
    )
    partial_then_later_runs = (group.runs[0], group.runs[2], group.runs[3])
    with pytest.raises(ValueError, match="partial block must be followed by a retry"):
        _ = replace(group, records=partial_then_later, runs=partial_then_later_runs)

    skipped_first_seen_pair = tuple(
        replace(record, index=index) for index, record in enumerate((*pair_one, *pair_three), start=1)
    )
    skipped_first_seen_runs = (*group.runs[:2], *group.runs[4:6])
    with pytest.raises(ValueError, match="first-seen pair indexes must form a one-based prefix"):
        _ = replace(group, records=skipped_first_seen_pair, runs=skipped_first_seen_runs)

    tampered_row = tuple(
        replace(record, cell_order_index=2) if record.pair_index == 3 else record for record in group.records
    )
    with pytest.raises(ValueError, match="differs from the deterministic schedule"):
        _ = replace(group, records=tampered_row)

    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    assert manifest["kind"] == "benchmark_paired_run_group"
    assert manifest["schema_version"] == 1
    assert manifest["random_seed"] == 19


def test_group_rejects_later_pairs_before_matrix_anchor() -> None:
    group = _failed_paired_group()
    schedule = make_paired_ab_ba_schedule(2, random_seed=group.random_seed)
    later_records = tuple(
        BenchmarkPairedRunRecord(
            index=index,
            pair_index=2,
            block_attempt=1,
            variant=variant,
            pair_order=schedule[1].pair_order,
            order_position=position,
            cell_order_index=schedule[1].cell_order_index,
            status="failed",
            path=Path(f"later-{variant}.json"),
            returncode=1,
            started_at="2026-08-01T00:00:00Z",
            duration_seconds=0.1,
            error="failed",
        )
        for index, (position, variant) in enumerate(zip((1, 2), schedule[1].variants, strict=True), start=3)
    )

    with pytest.raises(ValueError, match="later pair before a matrix anchor"):
        _ = replace(group, requested_pairs=2, records=(*group.records, *later_records))

    reindexed_later = tuple(replace(record, index=index) for index, record in enumerate(later_records, start=1))
    with pytest.raises(ValueError, match="first-seen pair indexes must form a one-based prefix"):
        _ = replace(group, requested_pairs=2, records=reindexed_later)


@pytest.mark.parametrize(
    ("cell_count", "expected_target"),
    [(1, 6), (2, 8), (3, 12), (4, 8), (5, 20)],
)
def test_automatic_pair_target_is_a_complete_joint_supercycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cell_count: int,
    expected_target: int,
) -> None:
    cells: tuple[_Cell, ...] = tuple((f"impl-{index}", "case", "single_call_latency") for index in range(cell_count))
    seed = 23

    def scheduled_factory(variant: str, order_index: int, call_index: int) -> tuple[int, dict[str, object]]:
        scheduled = balanced_cell_order(cells, order_index=order_index, random_seed=seed)
        return 0, _payload(scheduled, value=1.0 + call_index / 1000.0, commit=f"{variant}-commit")

    calls = _install_paired_runner(monkeypatch, scheduled_factory)
    group = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        tmp_path / f"automatic-{cell_count}",
        random_seed=seed,
    )

    schedule = make_paired_ab_ba_schedule(
        expected_target,
        random_seed=seed,
        cell_count=cell_count,
    )
    assert group.automatic_pairs is True
    assert group.requested_pairs == expected_target
    assert group.order_supercycle_length == collection_module.balanced_order_supercycle_length(cell_count)
    assert group.is_jointly_balanced is True
    assert group.is_complete is True
    assert [order_index for _variant, _seed, order_index, _cwd in calls] == [
        entry.cell_order_index for entry in schedule for _variant in entry.variants
    ]
    combinations = Counter((record.cell_order_index, record.pair_order) for record in group.records[::2])
    assert len(set(combinations.values())) == 1
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    assert manifest["automatic_pairs"] is True
    assert manifest["requested_pairs"] == expected_target


def test_collection_waits_for_matrix_anchor_then_resume_expands_automatic_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "anchor-resume"
    initial_calls = _install_paired_runner(monkeypatch, lambda _variant, _row, _call: (1, None))

    initial = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        output,
        random_seed=29,
    )

    assert len(initial_calls) == 2
    assert initial.automatic_pairs is True
    assert initial.requested_pairs == 6
    assert initial.expected_cells == ()
    assert {record.pair_index for record in initial.records} == {1}
    assert initial.order_supercycle_length is None
    assert initial.is_jointly_balanced is False

    cells: tuple[_Cell, ...] = (
        ("impl-a", "case", "single_call_latency"),
        ("impl-b", "case", "single_call_latency"),
    )

    def retry_factory(variant: str, order_index: int, call_index: int) -> tuple[int, dict[str, object]]:
        scheduled = balanced_cell_order(cells, order_index=order_index, random_seed=29)
        return 0, _payload(scheduled, value=1.0 + call_index / 1000.0, commit=f"{variant}-commit")

    retry_calls = _install_paired_runner(monkeypatch, retry_factory)
    resumed = collect_paired_benchmark_runs((), (), output, resume=True, retry_failed=True)

    assert len(retry_calls) == 16
    assert resumed.automatic_pairs is True
    assert resumed.requested_pairs == 8
    assert resumed.complete_pair_count == 8
    assert resumed.is_jointly_balanced is True
    assert [record.pair_index for record in resumed.records[:4]] == [1, 1, 1, 1]
    assert [record.pair_index for record in resumed.records[4:]] == [index for index in range(2, 9) for _ in range(2)]
    assert load_paired_benchmark_run_group(output) == resumed


def test_compare_rejects_complete_explicit_partial_supercycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "case", "single_call_latency"),)
    _install_paired_runner(
        monkeypatch,
        lambda variant, _row, call_index: (
            0,
            _payload(cells, value=1.0 + call_index / 1000.0, commit=f"{variant}-commit"),
        ),
    )
    group = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        tmp_path / "explicit-partial-cycle",
        pair_count=3,
    )

    assert group.is_complete is True
    assert group.automatic_pairs is False
    assert group.is_jointly_balanced is False
    with pytest.raises(BenchmarkCollectionError, match="whole AB/BA-by-balanced-row supercycle"):
        _ = group.compare()


def test_failed_pair_block_is_excluded_and_retry_reruns_both_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)

    def initial_factory(variant: str, pair_index: int, call_index: int) -> tuple[int, dict[str, object] | None]:
        if call_index <= 2 and variant == "candidate":
            return 7, None
        return 0, _payload(cells, value=1.0 + call_index / 100.0, commit=f"{variant}-commit")

    _install_paired_runner(monkeypatch, initial_factory)
    output = tmp_path / "retry"
    initial = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        output,
        pair_count=2,
        random_seed=2,
    )

    assert initial.complete_pair_count == 1
    assert initial.orphan_success_count == 1
    assert initial.incomplete_pair_indexes == (1,)
    with pytest.raises(BenchmarkCollectionError, match="finish or retry every requested block"):
        _ = initial.compare()

    retry_calls = _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, call_index: (
            0,
            _payload(cells, value=1.1 + call_index / 100.0, commit=f"{variant}-commit"),
        ),
    )
    retried = collect_paired_benchmark_runs((), (), output, resume=True, retry_failed=True)

    assert retried.is_complete is True
    assert retried.complete_pair_count == 2
    assert retried.orphan_success_count == 1
    assert [record.block_attempt for record in retried.records if record.pair_index == 1] == [1, 1, 2, 2]
    assert [variant for variant, _seed, _index, _cwd in retry_calls] == list(
        make_paired_ab_ba_schedule(2, random_seed=2, cell_count=1)[0].variants
    )
    assert retried.complete_pairs[0].block_attempt == 2
    assert load_paired_benchmark_run_group(output) == retried

    pair_one_retry = tuple(record for record in retried.records if record.pair_index == 1 and record.block_attempt == 2)
    pair_two = tuple(record for record in retried.records if record.pair_index == 2)
    pair_one_initial = tuple(
        record for record in retried.records if record.pair_index == 1 and record.block_attempt == 1
    )
    non_chronological = tuple(
        replace(record, index=index)
        for index, record in enumerate((*pair_one_retry, *pair_two, *pair_one_initial), start=1)
    )
    with pytest.raises(ValueError, match="chronological per pair"):
        _ = replace(retried, records=non_chronological)
    snapshot = BenchmarkPairedCollectionSnapshot.from_group(retried)
    with pytest.raises(ValueError, match="chronological per pair"):
        _ = replace(snapshot, records=non_chronological)

    reversed_block = tuple(
        replace(record, index=index)
        for index, record in enumerate((*retried.records[:-2], *reversed(retried.records[-2:])), start=1)
    )
    with pytest.raises(ValueError, match="scheduled AB/BA order"):
        _ = replace(retried, records=reversed_block)
    with pytest.raises(ValueError, match="scheduled AB/BA order"):
        _ = replace(snapshot, records=reversed_block)

    split_block = tuple(
        replace(record, index=index)
        for index, record in enumerate(
            (pair_one_initial[0], *pair_two, pair_one_initial[1], *pair_one_retry),
            start=1,
        )
    )
    with pytest.raises(ValueError, match="adjacent records"):
        _ = replace(retried, records=split_block)
    with pytest.raises(ValueError, match="adjacent records"):
        _ = replace(snapshot, records=split_block)

    failed_candidate = next(record for record in pair_one_initial if record.status == "failed")
    successful_candidate = next(record for record in pair_one_retry if record.variant == failed_candidate.variant)
    promoted = replace(
        failed_candidate,
        status="succeeded",
        returncode=0,
        error=None,
        commit=successful_candidate.commit,
        environment_fingerprint=successful_candidate.environment_fingerprint,
    )
    demoted = replace(
        successful_candidate,
        status="failed",
        returncode=1,
        error="forced failure",
        warnings=(),
        commit=None,
        environment_fingerprint=None,
    )
    retry_after_complete = tuple(
        promoted if record is failed_candidate else demoted if record is successful_candidate else record
        for record in retried.records
    )
    with pytest.raises(ValueError, match="cannot retry a pair after a complete block"):
        _ = replace(retried, records=retry_after_complete)
    with pytest.raises(ValueError, match="cannot retry a pair after a complete block"):
        _ = replace(snapshot, records=retry_after_complete)


def test_resume_discards_partial_block_and_restarts_adjacent_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    calls = 0

    def interrupted_runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        assert check is False
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        variant = "baseline" if command[0] == "baseline-pytest" else "candidate"
        output_argument = next(argument for argument in command if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        _ = output_path.write_text(
            json.dumps(_payload(cells, value=1.0, commit=f"{variant}-commit")),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(list(command), 0)

    monkeypatch.setattr(collection_module.subprocess, "run", interrupted_runner)
    output = tmp_path / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        _ = collect_paired_benchmark_runs(
            ("baseline-pytest",),
            ("candidate-pytest",),
            output,
            pair_count=1,
        )

    interrupted = load_paired_benchmark_run_group(output)
    assert interrupted.complete_pair_count == 0
    assert len(interrupted.records) == 1

    resume_calls = _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, _call_index: (
            0,
            _payload(cells, value=1.0, commit=f"{variant}-commit"),
        ),
    )
    resumed = collect_paired_benchmark_runs((), (), output, resume=True)

    assert resumed.is_complete is True
    assert len(resume_calls) == 2
    assert [record.block_attempt for record in resumed.records] == [1, 2, 2]
    assert resumed.orphan_success_count == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pair_count": 2}, "pair_count 2 does not match"),
        ({"random_seed": 2}, "random_seed 2 does not match"),
        ({"baseline_command": ("other",)}, "baseline command does not match"),
        ({"candidate_command": ("other",)}, "candidate command does not match"),
    ],
)
def test_resume_rejects_settings_that_differ_from_paired_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    message: str,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, _call_index: (
            0,
            _payload(cells, value=1.0, commit=f"{variant}-commit"),
        ),
    )
    output = tmp_path / "resume-mismatch"
    _ = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        output,
        pair_count=1,
        random_seed=1,
    )
    baseline_command = cast(Sequence[str], kwargs.get("baseline_command", ()))
    candidate_command = cast(Sequence[str], kwargs.get("candidate_command", ()))

    with pytest.raises(collection_module.BenchmarkCollectionError, match=message):
        _ = collect_paired_benchmark_runs(
            baseline_command,
            candidate_command,
            output,
            pair_count=cast(int | None, kwargs.get("pair_count")),
            random_seed=cast(int | None, kwargs.get("random_seed")),
            resume=True,
        )


@pytest.mark.parametrize(
    ("pair_count", "random_seed", "retry_failed", "message"),
    [
        (0, None, False, "pair_count must be"),
        (True, None, False, "pair_count must be"),
        (None, -1, False, "random_seed must be"),
        (None, True, False, "random_seed must be"),
        (None, None, True, "requires resume"),
    ],
)
def test_collect_paired_rejects_invalid_lifecycle_arguments(
    tmp_path: Path,
    pair_count: object,
    random_seed: object,
    retry_failed: bool,
    message: str,
) -> None:
    with pytest.raises(collection_module.BenchmarkCollectionError, match=message):
        _ = collect_paired_benchmark_runs(
            ("baseline-pytest",),
            ("candidate-pytest",),
            tmp_path / "invalid",
            pair_count=cast(int | None, pair_count),
            random_seed=cast(int | None, random_seed),
            retry_failed=retry_failed,
        )


def test_collect_paired_supports_distinct_working_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    baseline_cwd = tmp_path / "baseline-cwd"
    candidate_cwd = tmp_path / "candidate-cwd"
    baseline_cwd.mkdir()
    candidate_cwd.mkdir()
    calls = _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, _call_index: (
            0,
            _payload(cells, value=1.0, commit=f"{variant}-commit"),
        ),
    )

    group = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        tmp_path / "distinct-working-directories",
        pair_count=1,
        baseline_cwd=baseline_cwd,
        candidate_cwd=candidate_cwd,
    )

    cwd_by_variant = {variant: cwd for variant, _seed, _index, cwd in calls}
    assert cwd_by_variant == {"baseline": baseline_cwd, "candidate": candidate_cwd}
    assert group.baseline_cwd == baseline_cwd
    assert group.candidate_cwd == candidate_cwd


def test_paired_collection_rejects_observed_cell_order_that_ignores_schedule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells: tuple[_Cell, ...] = (
        ("impl-a", "small", "single_call_latency"),
        ("impl-b", "small", "single_call_latency"),
    )

    def reversed_factory(variant: str, order_index: int, _call_index: int) -> tuple[int, dict[str, object]]:
        scheduled = balanced_cell_order(cells, order_index=order_index, random_seed=11)
        return 0, _payload(tuple(reversed(scheduled)), value=1.0, commit=f"{variant}-commit")

    _install_paired_runner(monkeypatch, reversed_factory)
    group = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        tmp_path / "wrong-order",
        pair_count=1,
        random_seed=11,
    )

    assert group.complete_pair_count == 0
    assert group.successful_count == 0
    assert all("scheduled balanced order" in cast(str, record.error) for record in group.records)


def test_paired_manifest_rejects_tampered_schedule_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, _call_index: (
            0,
            _payload(cells, value=1.0, commit=f"{variant}-commit"),
        ),
    )
    group = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        tmp_path / "tampered",
        pair_count=1,
        random_seed=7,
    )
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    records = cast(list[dict[str, object]], manifest["runs"])
    records[0]["cell_order_index"] = 2
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match="differs from the deterministic schedule"):
        _ = load_paired_benchmark_run_group(group.manifest_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("producer", "other", "Unsupported producer"),
        ("kind", "other", "Unsupported paired benchmark manifest kind"),
        ("schema_version", 2, "Unsupported paired benchmark manifest schema"),
        ("created_at", "today", "ISO 8601"),
        ("baseline_command", [], "non-empty list"),
        ("candidate_command", [""], "non-empty string"),
        ("baseline_cwd", "", "non-empty string"),
        ("baseline_commit", "", "non-empty string"),
        ("baseline_environment_fingerprint", "bad", "SHA-256"),
        ("requested_pairs", 0, "positive integer"),
        ("automatic_pairs", 1, "Expected boolean"),
        ("random_seed", -1, "non-negative integer"),
        ("expected_cells", "bad", "Expected list"),
        ("runs", "bad", "Expected list"),
    ],
)
def test_load_paired_manifest_rejects_invalid_root_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, _call_index: (
            0,
            _payload(cells, value=1.0, commit=f"{variant}-commit"),
        ),
    )
    group = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        tmp_path / field,
        pair_count=1,
    )
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    manifest[field] = value
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_paired_benchmark_run_group(group.manifest_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("index", 0, "positive integer"),
        ("pair_index", 2, "exceeds requested_pairs"),
        ("block_attempt", 0, "positive integer"),
        ("variant", "other", "Unsupported paired variant"),
        ("pair_order", "AA", "Unsupported paired order"),
        ("order_position", 2, "inconsistent"),
        ("path", "/tmp/outside.json", "relative in-directory"),
        ("returncode", True, "Expected integer"),
        ("duration_seconds", -1, "finite non-negative"),
        ("warnings", [""], "non-empty string"),
        ("environment_fingerprint", "bad", "SHA-256"),
    ],
)
def test_load_paired_manifest_rejects_invalid_record_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, _call_index: (
            0,
            _payload(cells, value=1.0, commit=f"{variant}-commit"),
        ),
    )
    group = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        tmp_path / field,
        pair_count=1,
    )
    manifest = cast(dict[str, object], json.loads(group.manifest_path.read_text()))
    records = cast(list[dict[str, object]], manifest["runs"])
    records[0][field] = value
    _ = group.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_paired_benchmark_run_group(group.manifest_path)


def test_load_paired_group_reports_missing_and_malformed_manifest(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkJsonError, match="Could not read"):
        _ = load_paired_benchmark_run_group(tmp_path / "missing")

    malformed = tmp_path / "malformed.json"
    _ = malformed.write_text("{", encoding="utf-8")
    with pytest.raises(BenchmarkJsonError, match="Invalid JSON"):
        _ = load_paired_benchmark_run_group(malformed)


def test_load_paired_manifest_rejects_duplicate_paths_and_block_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, _call_index: (
            0,
            _payload(cells, value=1.0, commit=f"{variant}-commit"),
        ),
    )
    group = collect_paired_benchmark_runs(
        ("baseline-pytest",),
        ("candidate-pytest",),
        tmp_path / "structural-tamper",
        pair_count=1,
    )
    original = cast(dict[str, object], json.loads(group.manifest_path.read_text()))

    duplicate_path = cast(dict[str, object], json.loads(json.dumps(original)))
    duplicate_records = cast(list[dict[str, object]], duplicate_path["runs"])
    duplicate_records[1]["path"] = duplicate_records[0]["path"]
    _ = group.manifest_path.write_text(json.dumps(duplicate_path), encoding="utf-8")
    with pytest.raises(BenchmarkJsonError, match="run paths must be unique"):
        _ = load_paired_benchmark_run_group(group.manifest_path)

    duplicate_variant = cast(dict[str, object], json.loads(json.dumps(original)))
    variant_records = cast(list[dict[str, object]], duplicate_variant["runs"])
    variant_records[1]["variant"] = variant_records[0]["variant"]
    variant_records[1]["order_position"] = variant_records[0]["order_position"]
    _ = group.manifest_path.write_text(json.dumps(duplicate_variant), encoding="utf-8")
    with pytest.raises(BenchmarkJsonError, match="cannot repeat a variant"):
        _ = load_paired_benchmark_run_group(group.manifest_path)


def test_paired_resume_rejects_missing_manifest_and_working_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(BenchmarkCollectionError, match="does not exist"):
        _ = collect_paired_benchmark_runs((), (), missing, resume=True)

    malformed = tmp_path / "malformed"
    malformed.mkdir()
    _ = (malformed / collection_module.RUN_GROUP_MANIFEST).write_text("{", encoding="utf-8")
    with pytest.raises(BenchmarkCollectionError, match="Could not resume paired collection"):
        _ = collect_paired_benchmark_runs((), (), malformed, resume=True)

    unavailable = tmp_path / "unavailable"
    with pytest.raises(BenchmarkCollectionError, match="working directory is unavailable"):
        _ = collect_paired_benchmark_runs(
            ("baseline",),
            ("candidate",),
            tmp_path / "new-invalid-cwd",
            pair_count=1,
            baseline_cwd=unavailable,
        )

    cells: tuple[_Cell, ...] = (("impl", "small", "single_call_latency"),)
    baseline_cwd = tmp_path / "baseline-cwd-resume"
    baseline_cwd.mkdir()
    _install_paired_runner(
        monkeypatch,
        lambda variant, _pair_index, _call_index: (
            0,
            _payload(cells, value=1.0, commit=f"{variant}-commit"),
        ),
    )
    output = tmp_path / "resume-cwd"
    _ = collect_paired_benchmark_runs(
        ("baseline",),
        ("candidate",),
        output,
        pair_count=1,
        baseline_cwd=baseline_cwd,
    )
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    with pytest.raises(BenchmarkCollectionError, match="working directory does not match"):
        _ = collect_paired_benchmark_runs((), (), output, resume=True, baseline_cwd=other_cwd)
    _ = baseline_cwd.rename(tmp_path / "moved-baseline-cwd")
    with pytest.raises(BenchmarkCollectionError, match="working directory is unavailable"):
        _ = collect_paired_benchmark_runs((), (), output, resume=True)
