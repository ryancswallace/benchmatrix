"""Tests for versioned comparison report documents."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from benchmatrix import (
    BenchmarkCollectionSnapshot,
    BenchmarkComparisonReport,
    BenchmarkEvidence,
    BenchmarkJsonError,
    BenchmarkPolicyProvenance,
    BenchmarkRun,
    BenchmarkRunGroup,
    BenchmarkRunRecord,
    BenchmarkThresholdProvenance,
    EvidencePolicy,
    ParsedBenchmarkRow,
    RegressionPolicy,
    RunCompatibilityPolicy,
    compare_benchmark_run_groups,
    format_comparison_report_markdown,
    load_comparison_report,
    write_comparison_report,
    write_comparison_report_markdown,
)

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "comparison_reports" / "v1-regression.json"


def _row(value: float) -> ParsedBenchmarkRow:
    """Return one latency row with complete repeated-run evidence."""
    samples = (value * 0.98, value * 0.99, value, value * 1.01, value * 1.02)
    return ParsedBenchmarkRow(
        benchmark_name="test_benchmark[impl-small]",
        metric_name="single_call_latency",
        implementation_name="impl",
        case_name="small",
        stats={
            "mean": value,
            "median": value,
            "min": min(samples),
            "rounds": 5,
            "iterations": 1,
        },
        extra_info={
            "benchmatrix_producer": "benchmatrix",
            "benchmatrix_schema_version": 1,
            "metric_name": "single_call_latency",
            "implementation_name": "impl",
            "case_name": "small",
            "case_fresh_inputs": False,
        },
        derived={
            "latency_mean": value,
            "latency_median": value,
            "latency_min": min(samples),
        },
        samples=samples,
    )


def _run(value: float, source: Path) -> BenchmarkRun:
    """Return one benchmark run with stable environment metadata."""
    return BenchmarkRun(
        rows=(_row(value),),
        metadata={
            "version": "5.2.3",
            "commit_info": {"id": "abc123"},
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
                    "flags": ["avx2"],
                },
            },
        },
        source=source,
    )


def _report(tmp_path: Path, *, incomplete_collection: bool = False) -> BenchmarkComparisonReport:
    """Return a representative report with evidence and collection provenance."""
    baseline = _run(1.0, tmp_path / "baseline.json")
    candidate = _run(1.1, tmp_path / "candidate.json")
    regression_policy = RegressionPolicy(
        default_threshold_percent=5.0,
        by_metric={"single_call_latency": 6.0},
    )
    comparison = compare_benchmark_run_groups(
        (baseline,),
        (candidate,),
        compatibility_policy=RunCompatibilityPolicy(mode="permissive"),
        regression_policy=regression_policy,
        evidence_policy=EvidencePolicy(minimum_runs=1, minimum_samples_per_run=5),
    )
    requested_runs = 2 if incomplete_collection else 1
    record = BenchmarkRunRecord(
        index=1,
        status="succeeded",
        path=baseline.source or tmp_path / "baseline.json",
        returncode=0,
        started_at="2026-07-30T12:00:00Z",
        duration_seconds=1.25,
        commit="abc123",
        environment_fingerprint="sha256:" + "0" * 64,
    )
    group = BenchmarkRunGroup(
        runs=(baseline,),
        records=(record,),
        command=("uv", "run", "pytest", "benchmarks.py"),
        created_at="2026-07-30T12:00:00Z",
        cwd=tmp_path,
        commit="abc123",
        environment_fingerprint="sha256:" + "0" * 64,
        expected_cells=(("impl", "small", "single_call_latency"),),
        requested_runs=requested_runs,
        manifest_path=tmp_path / "benchmatrix-manifest.json",
    )
    return BenchmarkComparisonReport.from_comparison(
        comparison,
        baselines=(baseline.source or "baseline.json",),
        candidates=(candidate.source or "candidate.json",),
        baseline_collections=(group,),
        policy_provenance=BenchmarkPolicyProvenance(
            selection="discovered",
            configuration_file=str(tmp_path / "pyproject.toml"),
            configured_fields=("regression.by_metric.single_call_latency",),
        ),
        threshold_provenance=(
            BenchmarkThresholdProvenance(
                scope="metric",
                origin="configuration",
                field="regression.by_metric.single_call_latency",
            ),
        ),
    )


def _write_payload(tmp_path: Path, payload: object) -> Path:
    """Write one report JSON payload."""
    path = tmp_path / "report.json"
    _ = path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fixture_payload() -> dict[str, object]:
    """Return a mutable copy of the golden version 1 report."""
    return cast(dict[str, object], json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_load_golden_v1_report_fixture() -> None:
    report = load_comparison_report(FIXTURE)

    assert isinstance(report, BenchmarkComparisonReport)
    assert report.producer == "benchmatrix"
    assert report.kind == "benchmark_comparison"
    assert report.schema_version == 1
    assert report.baseline == "baseline.json"
    assert report.candidate == "candidate.json"
    assert report.passed is False
    assert report.comparison_passed is False
    assert report.is_comparable is True
    assert report.has_regressions is True
    assert len(report.regressed) == 1
    assert report.unchanged == ()
    assert report.inconclusive == ()
    assert report.not_comparable == ()
    assert report.threshold_provenance[0].origin == "built_in"


def test_golden_v1_report_has_deterministic_round_trip(tmp_path: Path) -> None:
    report = load_comparison_report(FIXTURE)
    output = tmp_path / "round-trip.json"

    write_comparison_report(report, output)

    assert output.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")
    assert load_comparison_report(output) == report


def test_markdown_report_renders_golden_comparison() -> None:
    report = load_comparison_report(FIXTURE)

    markdown = format_comparison_report_markdown(report)

    assert markdown.startswith("# Benchmark comparison\n")
    assert markdown.endswith("\n")
    assert "**Overall:** FAIL" in markdown
    assert "**Environment compatibility:** compatible" in markdown
    assert "## Summary" in markdown
    assert "| 0 | 0 | 1 | 0 | 0 |" in markdown
    assert "| impl | small | single_call_latency | regressed |" in markdown
    assert "5.00% (default/built_in)" in markdown
    assert "- Baseline: not available" in markdown
    assert "No environment differences were reported." in markdown
    assert "- Selection: `defaults`" in markdown


def test_markdown_report_preserves_lifecycle_evidence_and_policy(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    markdown = format_comparison_report_markdown(report)
    output = tmp_path / "comparison.md"

    write_comparison_report_markdown(report, output)

    assert output.read_text(encoding="utf-8") == markdown
    assert "### Collection lifecycle" in markdown
    assert "| 1 | 1 | 1 | 0 | 0 | yes |" in markdown
    assert "| impl | small | single_call_latency | regressed |" in markdown
    assert "6.00% (metric/configuration)" in markdown
    assert "runs 1/1; rounds [5]; iterations [1]" in markdown
    assert "CV 1.41%" in markdown
    configuration_path = str(tmp_path / "pyproject.toml").replace("\\", "\\\\")
    assert "- Configuration: " + configuration_path in markdown
    assert "`regression.by_metric.single_call_latency`" in markdown


def test_markdown_report_escapes_table_content(tmp_path: Path) -> None:
    report = _report(tmp_path)
    cell = replace(report.comparisons[0], reason="Noisy | evidence")
    escaped = replace(
        report,
        baselines=("baseline|main\nsecond",),
        comparisons=(cell,),
    )

    markdown = format_comparison_report_markdown(escaped)

    assert "baseline\\|main<br>second" in markdown
    assert "- Diagnostic: Noisy \\| evidence" in markdown


def test_markdown_report_rejects_wrong_type(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="BenchmarkComparisonReport"):
        _ = format_comparison_report_markdown(cast(Any, object()))
    with pytest.raises(TypeError, match="BenchmarkComparisonReport"):
        write_comparison_report_markdown(cast(Any, object()), tmp_path / "report.md")


def test_report_from_comparison_preserves_evidence_policy_and_collection(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    payload = report.to_dict()
    output = tmp_path / "report.json"

    write_comparison_report(report, output)
    loaded = load_comparison_report(output)

    assert report.passed is False
    assert report.comparison_passed is False
    assert report.has_regressions is True
    assert report.evidence_policy.minimum_samples_per_run == 5
    assert report.regression_policy.by_metric == {"single_call_latency": 6.0}
    assert report.comparisons[0].baseline_evidence is not None
    assert report.comparisons[0].baseline_evidence.sample_count == 5
    assert report.baseline_collections[0].complete is True
    assert payload["producer"] == "benchmatrix"
    assert payload["schema_version"] == 1
    assert loaded.to_dict() == payload


def test_incomplete_collection_fails_report_lifecycle_gate(tmp_path: Path) -> None:
    report = _report(tmp_path, incomplete_collection=True)

    assert report.baseline_collections[0].successful_runs == 1
    assert report.baseline_collections[0].attempted_runs == 1
    assert report.baseline_collections[0].failed_runs == 0
    assert report.baseline_collections[0].complete is False
    assert report.passed is False


def test_collection_snapshot_can_be_created_from_group(tmp_path: Path) -> None:
    report = _report(tmp_path)
    snapshot = report.baseline_collections[0]

    assert isinstance(snapshot, BenchmarkCollectionSnapshot)
    assert snapshot.command == ("uv", "run", "pytest", "benchmarks.py")
    assert snapshot.expected_cells == (("impl", "small", "single_call_latency"),)
    assert snapshot.records[0].status == "succeeded"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("producer", "other", "Unsupported benchmark comparison report producer"),
        ("kind", "other", "Unsupported benchmark comparison report kind"),
        ("schema_version", 2, "Unsupported benchmark comparison report schema version"),
        ("baseline", "other.json", "must equal the first baselines"),
        ("passed", True, "inconsistent derived values"),
        ("has_regressions", False, "inconsistent derived values"),
    ],
)
def test_load_report_rejects_invalid_root_values(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _fixture_payload()
    payload[field] = value

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_load_report_rejects_missing_and_unknown_keys(tmp_path: Path) -> None:
    payload = _fixture_payload()
    _ = payload.pop("summary")
    payload["surprise"] = True

    with pytest.raises(BenchmarkJsonError, match=r"missing summary; unknown surprise"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("comparison", "metric_name", "unknown", "Unsupported metric"),
        ("comparison", "threshold_percent", 7.0, "does not match the effective regression policy"),
        ("threshold", "field", "regression.by_case.small", "field is inconsistent"),
        ("threshold", "origin", "configuration", "origin does not match"),
        ("summary", "regressed", 0, "inconsistent derived values"),
        ("compatibility", "is_compatible", False, "is inconsistent with findings"),
        ("evidence_policy", "minimum_runs", 0, "positive integer"),
    ],
)
def test_load_report_rejects_inconsistent_nested_values(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _fixture_payload()
    if section == "comparison":
        comparisons = cast(list[dict[str, object]], payload["comparisons"])
        comparisons[0][field] = value
    elif section == "threshold":
        comparisons = cast(list[dict[str, object]], payload["comparisons"])
        threshold = cast(dict[str, object], comparisons[0]["threshold_source"])
        threshold[field] = value
    else:
        nested = cast(dict[str, object], payload[section])
        nested[field] = value

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_load_report_rejects_missing_and_malformed_files(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkJsonError, match="Could not read"):
        _ = load_comparison_report(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    _ = malformed.write_text("{", encoding="utf-8")
    with pytest.raises(BenchmarkJsonError, match="Invalid JSON"):
        _ = load_comparison_report(malformed)


def test_write_report_rejects_wrong_type(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="BenchmarkComparisonReport"):
        write_comparison_report(cast(Any, object()), tmp_path / "report.json")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"baselines": ()}, "baselines"),
        ({"candidates": ("",)}, "candidates"),
        ({"threshold_provenance": ()}, "requires threshold provenance"),
        ({"compatibility": object()}, "RunCompatibilityReport"),
        ({"evidence_policy": object()}, "EvidencePolicy"),
        ({"regression_policy": object()}, "RegressionPolicy"),
        ({"policy_provenance": object()}, "BenchmarkPolicyProvenance"),
    ],
)
def test_report_rejects_invalid_direct_construction(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    report = _report(tmp_path)

    with pytest.raises((TypeError, ValueError), match=message):
        _ = replace(report, **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"selection": "other"}, "Unsupported policy selection"),
        ({"configuration_file": ""}, "configuration_file"),
        ({"configured_fields": ("",)}, "non-empty strings"),
    ],
)
def test_policy_provenance_rejects_invalid_values(
    changes: dict[str, object],
    message: str,
) -> None:
    provenance = BenchmarkPolicyProvenance(selection="defaults")

    with pytest.raises(ValueError, match=message):
        _ = replace(provenance, **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"scope": "other"}, "Unsupported threshold scope"),
        ({"origin": "other"}, "Unsupported threshold origin"),
        ({"field": ""}, "non-empty string"),
    ],
)
def test_threshold_provenance_rejects_invalid_values(
    changes: dict[str, object],
    message: str,
) -> None:
    provenance = BenchmarkThresholdProvenance(
        scope="default",
        origin="built_in",
        field="regression.default_threshold_percent",
    )

    with pytest.raises(ValueError, match=message):
        _ = replace(provenance, **changes)


def test_evidence_type_is_preserved_in_loaded_report(tmp_path: Path) -> None:
    report = _report(tmp_path)
    output = tmp_path / "report.json"
    write_comparison_report(report, output)

    evidence = load_comparison_report(output).comparisons[0].candidate_evidence

    assert isinstance(evidence, BenchmarkEvidence)
    assert evidence.adequate is True


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"manifest": ""}, "manifest"),
        ({"created_at": ""}, "created_at"),
        ({"command": ()}, "command"),
        ({"cwd": ""}, "cwd"),
        ({"commit": ""}, "commit"),
        ({"environment_fingerprint": ""}, "environment fingerprint"),
        ({"requested_runs": 0}, "requested_runs"),
        ({"expected_cells": (("impl", "small", "single_call_latency"),) * 2}, "duplicates"),
        ({"expected_cells": (("", "small", "single_call_latency"),)}, "Invalid collection expected cell"),
    ],
)
def test_collection_snapshot_rejects_invalid_direct_values(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    snapshot = _report(tmp_path).baseline_collections[0]

    with pytest.raises(ValueError, match=message):
        _ = replace(snapshot, **changes)


def test_collection_snapshot_rejects_record_count_and_index_gaps(tmp_path: Path) -> None:
    snapshot = _report(tmp_path).baseline_collections[0]
    second = replace(snapshot.records[0], index=2)

    with pytest.raises(ValueError, match="more successful runs"):
        _ = replace(snapshot, records=(*snapshot.records, second))
    with pytest.raises(ValueError, match="contiguous"):
        _ = replace(snapshot, records=(second,))


def test_collection_snapshot_preserves_retry_attempts(tmp_path: Path) -> None:
    snapshot = _report(tmp_path).baseline_collections[0]
    succeeded_retry = replace(snapshot.records[0], index=2)
    failed_initial = BenchmarkRunRecord(
        index=1,
        status="failed",
        path=tmp_path / "run-001.json",
        returncode=1,
        started_at="2026-07-30T12:00:00Z",
        duration_seconds=0.5,
        error="benchmark command failed",
    )

    retried = replace(snapshot, records=(failed_initial, succeeded_retry))

    assert retried.requested_runs == 1
    assert retried.attempted_runs == 2
    assert retried.successful_runs == 1
    assert retried.failed_runs == 1
    assert retried.pending_runs == 0
    assert retried.retry_attempts == 1
    assert retried.remaining_runs == 0
    assert retried.complete is True


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"baseline_collections": (object(),)}, "BenchmarkCollectionSnapshot"),
        ({"comparisons": (object(),)}, "BenchmarkComparison"),
        ({"threshold_provenance": (object(),)}, "BenchmarkThresholdProvenance"),
    ],
)
def test_report_rejects_invalid_container_members(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    report = _report(tmp_path)

    with pytest.raises(TypeError, match=message):
        _ = replace(report, **changes)


def test_load_report_rejects_candidate_alias_mismatch(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["candidate"] = "other.json"

    with pytest.raises(BenchmarkJsonError, match="first candidates"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


@pytest.mark.parametrize("scope", ["case", "implementation", "cell"])
def test_load_report_preserves_configured_threshold_scopes(
    tmp_path: Path,
    scope: str,
) -> None:
    payload = _fixture_payload()
    policy = cast(dict[str, object], payload["policy"])
    regression = cast(dict[str, object], policy["regression"])
    comparison = cast(list[dict[str, object]], payload["comparisons"])[0]
    threshold_source = cast(dict[str, object], comparison["threshold_source"])
    if scope == "case":
        field = "regression.by_case.small"
        regression["by_case"] = {"small": 5.0}
    elif scope == "implementation":
        field = "regression.by_implementation.impl"
        regression["by_implementation"] = {"impl": 5.0}
    else:
        field = "regression.by_cell.impl.small.single_call_latency"
        regression["by_cell"] = [
            {
                "implementation": "impl",
                "case": "small",
                "metric": "single_call_latency",
                "threshold_percent": 5.0,
            }
        ]
    policy["selection"] = "discovered"
    policy["configuration_file"] = "pyproject.toml"
    policy["configured_fields"] = [field]
    threshold_source.update({"scope": scope, "origin": "configuration", "field": field})

    report = load_comparison_report(_write_payload(tmp_path, payload))

    assert report.threshold_provenance[0].scope == scope
    assert report.threshold_provenance[0].origin == "configuration"


def test_load_report_preserves_compatibility_findings_and_json_values(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    compatibility = cast(dict[str, object], payload["compatibility"])
    compatibility["findings"] = [
        {
            "field": "dependencies",
            "severity": "warning",
            "reason": "Dependencies differ.",
            "baseline_value": ["package-a", {"version": 1}],
            "candidate_value": {"package-a": ["2.0"]},
            "baseline_run": "baseline.json",
            "candidate_run": "candidate.json",
        }
    ]

    report = load_comparison_report(_write_payload(tmp_path, payload))
    markdown = format_comparison_report_markdown(report)

    assert len(report.compatibility.warnings) == 1
    assert report.compatibility.warnings[0].baseline_value == ["package-a", {"version": 1}]
    assert "| warning | dependencies |" in markdown
    assert r'["package-a",{"version":1}]' in markdown
    assert r'{"package-a":["2.0"]}' in markdown
    assert "Dependencies differ." in markdown


def test_load_report_preserves_failed_collection_record(tmp_path: Path) -> None:
    payload = _report(tmp_path).to_dict()
    collections = cast(list[dict[str, object]], payload["baseline_collections"])
    collection = collections[0]
    records = cast(list[dict[str, object]], collection["runs"])
    records[0].update(
        {
            "status": "failed",
            "returncode": None,
            "error": "benchmark command failed",
            "environment_fingerprint": None,
        }
    )
    collection.update(
        {
            "successful_runs": 0,
            "failed_runs": 1,
            "complete": False,
        }
    )
    payload["passed"] = False

    report = load_comparison_report(_write_payload(tmp_path, payload))

    assert report.baseline_collections[0].records[0].returncode is None
    assert report.baseline_collections[0].failed_runs == 1


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload.update({"baselines": "baseline.json"}),
            "Expected list",
        ),
        (
            lambda payload: payload.update({"producer": 1}),
            "Expected string",
        ),
        (
            lambda payload: payload.update({"baseline": ""}),
            "Expected non-empty string",
        ),
        (
            lambda payload: payload.update({"baselines": []}),
            "Expected non-empty list",
        ),
        (
            lambda payload: payload.update({"schema_version": True}),
            "Expected integer",
        ),
        (
            lambda payload: cast(dict[str, object], payload["summary"]).update({"improved": -1}),
            "Expected non-negative integer",
        ),
        (
            lambda payload: cast(list[dict[str, object]], payload["comparisons"])[0].update({"threshold_percent": -1}),
            "Expected non-negative number",
        ),
        (
            lambda payload: payload.update({"passed": 1}),
            "Expected boolean",
        ),
        (
            lambda payload: cast(list[dict[str, object]], payload["comparisons"])[0].update({"baseline_value": "bad"}),
            "Expected finite number",
        ),
        (
            lambda payload: cast(list[dict[str, object]], payload["comparisons"])[0].update({"status": "other"}),
            "Unsupported value",
        ),
        (
            lambda payload: cast(dict[str, object], payload["compatibility"]).update({"mode": "other"}),
            "Unsupported compatibility mode",
        ),
        (
            lambda payload: cast(dict[str, object], payload["policy"]).update({"selection": "other"}),
            "Unsupported policy selection",
        ),
    ],
)
def test_load_report_rejects_scalar_schema_violations(
    tmp_path: Path,
    mutate: Any,
    message: str,
) -> None:
    payload = _fixture_payload()
    mutate(payload)

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_load_report_rejects_invalid_finding_and_non_finite_json_value(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    compatibility = cast(dict[str, object], payload["compatibility"])
    compatibility.update(
        {
            "findings": [
                {
                    "field": "dependencies",
                    "severity": "other",
                    "reason": "Changed.",
                    "baseline_value": None,
                    "candidate_value": None,
                    "baseline_run": None,
                    "candidate_run": None,
                }
            ],
            "is_compatible": True,
        }
    )
    with pytest.raises(BenchmarkJsonError, match="Unsupported compatibility severity"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    finding = cast(list[dict[str, object]], compatibility["findings"])[0]
    finding["severity"] = "warning"
    finding["baseline_value"] = float("nan")
    with pytest.raises(BenchmarkJsonError, match="strict JSON value"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_load_report_rejects_invalid_collection_values(tmp_path: Path) -> None:
    payload = _report(tmp_path).to_dict()
    collection = cast(list[dict[str, object]], payload["baseline_collections"])[0]
    records = cast(list[dict[str, object]], collection["runs"])
    records[0]["status"] = "other"
    with pytest.raises(BenchmarkJsonError, match="Unsupported collection status"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    records[0]["status"] = "succeeded"
    records[0]["returncode"] = 1
    with pytest.raises(BenchmarkJsonError, match="Invalid collection record"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    records[0]["returncode"] = 0
    records.append({**records[0], "index": 2})
    with pytest.raises(BenchmarkJsonError, match="Invalid collection snapshot"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    _ = records.pop()
    collection["attempted_runs"] = 0
    with pytest.raises(BenchmarkJsonError, match="inconsistent derived values"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_load_report_rejects_duplicate_and_invalid_regression_policy(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    policy = cast(dict[str, object], payload["policy"])
    regression = cast(dict[str, object], policy["regression"])
    cell = {
        "implementation": "impl",
        "case": "small",
        "metric": "single_call_latency",
        "threshold_percent": 5.0,
    }
    regression["by_cell"] = [cell, cell]
    with pytest.raises(BenchmarkJsonError, match="Duplicate regression cell"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    regression["by_cell"] = []
    regression["default_threshold_percent"] = -1
    with pytest.raises(BenchmarkJsonError, match="Invalid regression policy"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_load_report_rejects_threshold_scope_inconsistent_with_policy(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    comparison = cast(list[dict[str, object]], payload["comparisons"])[0]
    threshold_source = cast(dict[str, object], comparison["threshold_source"])
    threshold_source.update(
        {
            "scope": "metric",
            "field": "regression.by_metric.single_call_latency",
        }
    )

    with pytest.raises(BenchmarkJsonError, match="scope does not match"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))
