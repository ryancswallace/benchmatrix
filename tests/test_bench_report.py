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
    BenchmarkPairedCollectionSnapshot,
    BenchmarkPairedRunGroup,
    BenchmarkPairedRunRecord,
    BenchmarkPolicyProvenance,
    BenchmarkRun,
    BenchmarkRunGroup,
    BenchmarkRunRecord,
    BenchmarkThresholdProvenance,
    EvidencePolicy,
    InferencePolicy,
    ParsedBenchmarkRow,
    PrecisionPolicy,
    RegressionPolicy,
    RunCompatibilityFinding,
    RunCompatibilityPolicy,
    compare_benchmark_run_groups,
    format_comparison_report_markdown,
    load_comparison_report,
    make_paired_ab_ba_schedule,
    write_comparison_report,
    write_comparison_report_markdown,
)

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "comparison_reports" / "v1-regression.json"
V2_FIXTURE = Path(__file__).parent / "fixtures" / "comparison_reports" / "v2-inference.json"


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
        inference_policy=InferencePolicy(method="legacy_consistency", multiplicity="none"),
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


def _inference_report(tmp_path: Path) -> BenchmarkComparisonReport:
    """Return a current report containing formal run-level inference."""
    baseline_values = (0.99, 1.0, 1.01, 1.0, 0.995)
    candidate_values = (1.19, 1.2, 1.21, 1.2, 1.195)
    baselines = tuple(
        _run(value, tmp_path / f"baseline-{index}.json") for index, value in enumerate(baseline_values, start=1)
    )
    candidates = tuple(
        _run(value, tmp_path / f"candidate-{index}.json") for index, value in enumerate(candidate_values, start=1)
    )
    comparison = compare_benchmark_run_groups(
        baselines,
        candidates,
        evidence_policy=EvidencePolicy(),
        inference_policy=InferencePolicy(resamples=1_000, random_seed=17),
    )
    return BenchmarkComparisonReport.from_comparison(
        comparison,
        baselines=tuple(run.source or "baseline.json" for run in baselines),
        candidates=tuple(run.source or "candidate.json" for run in candidates),
        policy_provenance=BenchmarkPolicyProvenance(selection="defaults"),
        threshold_provenance=(
            BenchmarkThresholdProvenance(
                scope="default",
                origin="built_in",
                field="regression.default_threshold_percent",
            ),
        ),
    )


def _paired_report(tmp_path: Path, *, precision: bool = True) -> BenchmarkComparisonReport:
    """Return a paired report with AB/BA provenance and optional planning."""
    baseline_values = (1.0, 1.02, 0.99, 1.01, 0.98, 1.03)
    candidate_values = (0.97, 0.96, 0.98, 0.95, 0.96, 0.99)
    baselines = tuple(
        _run(value, tmp_path / f"paired-baseline-{index}.json") for index, value in enumerate(baseline_values, start=1)
    )
    candidates = tuple(
        _run(value, tmp_path / f"paired-candidate-{index}.json")
        for index, value in enumerate(candidate_values, start=1)
    )
    records: list[BenchmarkPairedRunRecord] = []
    runs: list[BenchmarkRun] = []
    fingerprint = "sha256:" + "1" * 64
    run_index = 1
    for schedule in make_paired_ab_ba_schedule(6, random_seed=23, cell_count=1):
        variants = ("baseline", "candidate") if schedule.pair_order == "AB" else ("candidate", "baseline")
        for order_position, variant in enumerate(variants, start=1):
            run = baselines[schedule.pair_index - 1] if variant == "baseline" else candidates[schedule.pair_index - 1]
            records.append(
                BenchmarkPairedRunRecord(
                    index=run_index,
                    pair_index=schedule.pair_index,
                    block_attempt=1,
                    variant=variant,
                    pair_order=schedule.pair_order,
                    order_position=order_position,
                    cell_order_index=schedule.cell_order_index,
                    status="succeeded",
                    path=run.source or tmp_path / f"paired-{run_index}.json",
                    returncode=0,
                    started_at="2026-07-30T12:00:00Z",
                    duration_seconds=1.0,
                    commit="abc123",
                    environment_fingerprint=fingerprint,
                )
            )
            runs.append(run)
            run_index += 1
    group = BenchmarkPairedRunGroup(
        runs=tuple(runs),
        records=tuple(records),
        baseline_command=("uv", "run", "pytest", "baseline.py"),
        candidate_command=("uv", "run", "pytest", "candidate.py"),
        created_at="2026-07-30T12:00:00Z",
        baseline_cwd=tmp_path,
        candidate_cwd=tmp_path,
        baseline_commit="abc123",
        candidate_commit="abc123",
        baseline_environment_fingerprint=fingerprint,
        candidate_environment_fingerprint=fingerprint,
        expected_cells=(("impl", "small", "single_call_latency"),),
        requested_pairs=6,
        random_seed=23,
        manifest_path=tmp_path / "paired" / "benchmatrix-manifest.json",
        automatic_pairs=False,
    )
    precision_policy = PrecisionPolicy(target_half_width_percent=2.5) if precision else PrecisionPolicy()
    comparison = group.compare(
        evidence_policy=EvidencePolicy(),
        inference_policy=InferencePolicy(resamples=1_000, random_seed=17),
        precision_policy=precision_policy,
    )
    return BenchmarkComparisonReport.from_comparison(
        comparison,
        baselines=tuple(run.source or "baseline.json" for run in group.baseline_runs),
        candidates=tuple(run.source or "candidate.json" for run in group.candidate_runs),
        paired_collections=(group,),
        policy_provenance=BenchmarkPolicyProvenance(selection="defaults"),
        threshold_provenance=(
            BenchmarkThresholdProvenance(
                scope="default",
                origin="built_in",
                field="regression.default_threshold_percent",
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


def _v2_fixture_payload() -> dict[str, object]:
    """Return a mutable copy of the golden version 2 report."""
    return cast(dict[str, object], json.loads(V2_FIXTURE.read_text(encoding="utf-8")))


def test_load_golden_v1_report_fixture_upgrades_to_current_model() -> None:
    report = load_comparison_report(FIXTURE)

    assert isinstance(report, BenchmarkComparisonReport)
    assert report.producer == "benchmatrix"
    assert report.kind == "benchmark_comparison"
    assert report.schema_version == 3
    assert report.inference_policy.method == "legacy_consistency"
    assert report.design == "independent"
    assert report.precision_policy == PrecisionPolicy()
    assert report.paired_collections == ()
    assert report.comparisons[0].inference is None
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


def test_golden_v1_report_writes_current_v3_schema(tmp_path: Path) -> None:
    report = load_comparison_report(FIXTURE)
    output = tmp_path / "round-trip.json"

    write_comparison_report(report, output)

    payload = cast(dict[str, object], json.loads(output.read_text(encoding="utf-8")))
    assert payload["schema_version"] == 3
    assert payload["design"] == "independent"
    assert payload["paired_collections"] == []
    assert cast(dict[str, object], payload["precision_policy"])["target_half_width_percent"] is None
    assert cast(dict[str, object], payload["inference_policy"])["method"] == "legacy_consistency"
    assert cast(list[dict[str, object]], payload["comparisons"])[0]["inference"] is None
    assert load_comparison_report(output) == report


def test_v1_evidence_upgrades_with_unavailable_per_run_diagnostics(tmp_path: Path) -> None:
    payload = _fixture_payload()
    evidence = {
        "provided_run_count": 1,
        "observed_run_count": 1,
        "rounds": [5],
        "iterations": [1],
        "sample_counts": [5],
        "sample_count": 5,
        "iqr": 0.02,
        "coefficient_of_variation": 0.01,
        "outlier_count": 0,
        "outlier_fraction": 0.0,
        "adequate": True,
        "issues": [],
    }
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    cell["baseline_evidence"] = evidence
    cell["candidate_evidence"] = dict(evidence)
    report = load_comparison_report(_write_payload(tmp_path, payload))
    output = tmp_path / "upgraded.json"

    write_comparison_report(report, output)
    upgraded = load_comparison_report(output)

    upgraded_evidence = upgraded.comparisons[0].baseline_evidence
    assert upgraded_evidence is not None
    assert upgraded_evidence.run_iqrs == ()
    assert upgraded == report


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
    assert payload["schema_version"] == 3
    assert loaded.to_dict() == payload


def test_v3_report_round_trip_preserves_formal_inference(tmp_path: Path) -> None:
    report = _inference_report(tmp_path)
    output = tmp_path / "inference-report.json"

    write_comparison_report(report, output)
    payload = cast(dict[str, object], json.loads(output.read_text(encoding="utf-8")))
    loaded = load_comparison_report(output)

    assert payload["schema_version"] == 3
    assert payload["design"] == "independent"
    assert cast(dict[str, object], payload["inference_policy"]) == {
        "confidence_level": 0.95,
        "method": "bca_bootstrap",
        "multiplicity": "bonferroni",
        "random_seed": 17,
        "resamples": 1_000,
    }
    cell_payload = cast(list[dict[str, object]], payload["comparisons"])[0]
    inference_payload = cast(dict[str, object], cell_payload["inference"])
    assert inference_payload["adequate"] is True
    assert inference_payload["family_size"] == 1
    assert inference_payload["pair_count"] is None
    assert inference_payload["estimate_percent"] == cell_payload["improvement_percent"]
    assert inference_payload["confidence_low_percent"] != cell_payload["improvement_low_percent"]
    baseline_evidence = cast(dict[str, object], cell_payload["baseline_evidence"])
    assert len(cast(list[object], baseline_evidence["run_iqrs"])) == 5
    assert loaded == report


def test_load_golden_v2_report_fixture_upgrades_to_current_model(tmp_path: Path) -> None:
    report = load_comparison_report(V2_FIXTURE)
    inference = report.comparisons[0].inference

    assert report.schema_version == 3
    assert report.design == "independent"
    assert report.precision_policy == PrecisionPolicy()
    assert report.paired_collections == ()
    assert report.baselines == tuple(f"frozen-v2/baseline-{index}.json" for index in range(1, 6))
    assert report.candidates == tuple(f"frozen-v2/candidate-{index}.json" for index in range(1, 6))
    assert inference is not None
    assert inference.pair_count is None
    assert inference.confidence_low_percent == pytest.approx(-21.212121212121215)
    assert inference.confidence_high_percent == pytest.approx(-18.31683168316831)
    assert report.comparisons[0].precision is None

    output = tmp_path / "upgraded-v2.json"
    write_comparison_report(report, output)
    payload = cast(dict[str, object], json.loads(output.read_text(encoding="utf-8")))
    assert payload["schema_version"] == 3
    assert load_comparison_report(output) == report


def test_v3_paired_report_round_trip_preserves_design_planning_and_provenance(
    tmp_path: Path,
) -> None:
    report = _paired_report(tmp_path)
    output = tmp_path / "paired-report.json"

    write_comparison_report(report, output)
    payload = cast(dict[str, object], json.loads(output.read_text(encoding="utf-8")))
    loaded = load_comparison_report(output)

    assert payload["schema_version"] == 3
    assert payload["design"] == "paired"
    assert cast(dict[str, object], payload["precision_policy"]) == {"target_half_width_percent": 2.5}
    paired_collections = cast(list[dict[str, object]], payload["paired_collections"])
    assert paired_collections[0]["requested_pairs"] == 6
    assert paired_collections[0]["automatic_pairs"] is False
    assert paired_collections[0]["complete_pairs"] == 6
    assert paired_collections[0]["orphan_successes"] == 0
    records = cast(list[dict[str, object]], paired_collections[0]["runs"])
    assert {cast(str, record["pair_order"]) for record in records} == {"AB", "BA"}
    assert any(record["pair_index"] != record["cell_order_index"] for record in records)
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    inference = cast(dict[str, object], cell["inference"])
    assert inference["pair_count"] == 6
    assert inference["strata_count"] == 2
    plan = cast(dict[str, object], cell["precision"])
    assert plan["method"] == "paired_log_ratio_t"
    assert plan["pilot_pairs"] == 6
    assert plan["minimum_pairs"] == 5
    assert plan["pair_count_multiple"] == 2
    assert plan["strata_count"] == 2
    assert isinstance(plan["unconstrained_required_pairs"], int)
    assert plan["target_half_width_percent"] == 2.5
    assert plan["required_pairs"] == 6
    assert plan["additional_pairs"] == 0
    assert plan["adequate"] is True
    assert isinstance(report.paired_collections[0], BenchmarkPairedCollectionSnapshot)
    assert loaded == report


def test_precision_planning_is_informational_for_report_decisions(tmp_path: Path) -> None:
    planned = _paired_report(tmp_path, precision=True)
    unplanned = _paired_report(tmp_path, precision=False)

    assert planned.passed == unplanned.passed
    assert planned.comparison_passed == unplanned.comparison_passed
    assert tuple(cell.regression for cell in planned.comparisons) == tuple(
        cell.regression for cell in unplanned.comparisons
    )
    assert planned.comparisons[0].precision is not None
    assert unplanned.comparisons[0].precision is None


def test_v3_round_trip_accepts_failed_precision_plan_without_pair_count_result(
    tmp_path: Path,
) -> None:
    report = _paired_report(tmp_path)
    plan = report.comparisons[0].precision
    assert plan is not None
    failed_plan = replace(
        plan,
        critical_value=None,
        unconstrained_required_pairs=None,
        required_pairs=None,
        additional_pairs=None,
        issues=("run-environment compatibility was blocked; precision planning is unavailable",),
    )
    failed_report = replace(
        report,
        comparisons=(replace(report.comparisons[0], precision=failed_plan),),
    )
    output = tmp_path / "failed-plan.json"

    write_comparison_report(failed_report, output)

    assert failed_report.passed == report.passed
    assert load_comparison_report(output) == failed_report


def test_markdown_reports_paired_design_collection_and_precision(tmp_path: Path) -> None:
    markdown = format_comparison_report_markdown(_paired_report(tmp_path))

    assert "**Comparison design:** `paired`" in markdown
    assert "### Paired AB/BA collection lifecycle" in markdown
    assert "| 6 | 12 | 6 | 0 | 0 | yes |" in markdown
    assert "complete pairs 6" in markdown
    assert "AB/BA strata 2" in markdown
    assert "pair-count multiple 2" in markdown
    assert "Precision target half-width: 2.50%" in markdown
    assert "fresh fixed-design pairs 6" in markdown


def test_v3_rejects_paired_source_and_anchor_provenance_corruption(tmp_path: Path) -> None:
    payload = _paired_report(tmp_path).to_dict()
    baselines = cast(list[str], payload["baselines"])
    baselines[0] = "tampered-baseline.json"
    payload["baseline"] = baselines[0]
    with pytest.raises(BenchmarkJsonError, match="same-block record paths"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    collection = cast(list[dict[str, object]], payload["paired_collections"])[0]
    collection["baseline_commit"] = "tampered"
    with pytest.raises(BenchmarkJsonError, match="commits do not match"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    collection = cast(list[dict[str, object]], payload["paired_collections"])[0]
    collection["candidate_environment_fingerprint"] = "sha256:" + "2" * 64
    with pytest.raises(BenchmarkJsonError, match="fingerprint does not match"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_rejects_inference_and_precision_cross_field_corruption(tmp_path: Path) -> None:
    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    cast(dict[str, object], cell["inference"])["pair_count"] = 5
    with pytest.raises(BenchmarkJsonError, match="pair_count does not match"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    cast(dict[str, object], cell["inference"])["strata_count"] = 1
    with pytest.raises(BenchmarkJsonError, match="strata_count does not match"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cast(dict[str, object], payload["precision_policy"])["target_half_width_percent"] = 3.0
    with pytest.raises(BenchmarkJsonError, match="target does not match"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    plan = cast(dict[str, object], cell["precision"])
    plan["required_pairs"] = 7
    with pytest.raises(BenchmarkJsonError, match="required_pairs is inconsistent"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    plan = cast(dict[str, object], cell["precision"])
    plan["family_size"] = 2
    plan["adjusted_confidence_level"] = 0.975
    with pytest.raises(BenchmarkJsonError, match="Invalid precision plan"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    plan = cast(dict[str, object], cell["precision"])
    plan["minimum_pairs"] = 6
    with pytest.raises(BenchmarkJsonError, match="minimum pair count does not match"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    plan = cast(dict[str, object], cell["precision"])
    plan["strata_count"] = 1
    with pytest.raises(BenchmarkJsonError, match="Invalid precision plan"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    plan = cast(dict[str, object], cell["precision"])
    plan["issues"] = ["fabricated failure"]
    plan["adequate"] = False
    with pytest.raises(BenchmarkJsonError, match="Failed precision plans"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_precision_plan_keys_are_strict(tmp_path: Path) -> None:
    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    plan = cast(dict[str, object], cell["precision"])
    _ = plan.pop("assumptions")
    plan["surprise"] = True

    with pytest.raises(BenchmarkJsonError, match=r"missing assumptions; unknown surprise"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_paired_inference_and_collection_keys_are_strict(tmp_path: Path) -> None:
    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    inference = cast(dict[str, object], cell["inference"])
    _ = inference.pop("pair_count")
    inference["surprise"] = True
    with pytest.raises(BenchmarkJsonError, match=r"missing pair_count; unknown surprise"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    collection = cast(list[dict[str, object]], payload["paired_collections"])[0]
    _ = collection.pop("complete_pairs")
    collection["surprise"] = True
    with pytest.raises(BenchmarkJsonError, match=r"missing complete_pairs; unknown surprise"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"manifest": ""}, "manifest"),
        ({"created_at": ""}, "created_at"),
        ({"baseline_command": ()}, "baseline_command"),
        ({"candidate_command": ("",)}, "candidate_command"),
        ({"baseline_cwd": ""}, "baseline_cwd"),
        ({"candidate_cwd": ""}, "candidate_cwd"),
        ({"baseline_commit": ""}, "baseline_commit"),
        ({"candidate_environment_fingerprint": ""}, "candidate_environment_fingerprint"),
        ({"requested_pairs": 0}, "requested_pairs"),
        ({"random_seed": -1}, "random_seed"),
        ({"automatic_pairs": 1}, "automatic_pairs"),
        ({"expected_cells": (("impl", "small", "single_call_latency"),) * 2}, "duplicates"),
        ({"expected_cells": (("", "small", "single_call_latency"),)}, "Invalid paired collection"),
        ({"records": (object(),)}, "BenchmarkPairedRunRecord"),
    ],
)
def test_paired_snapshot_rejects_invalid_direct_values(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    snapshot = _paired_report(tmp_path).paired_collections[0]

    with pytest.raises((TypeError, ValueError), match=message):
        _ = replace(snapshot, **changes)


def test_paired_snapshot_rejects_index_schedule_and_attempt_corruption(tmp_path: Path) -> None:
    snapshot = _paired_report(tmp_path).paired_collections[0]
    records = snapshot.records

    with pytest.raises(ValueError, match="indexes must be contiguous"):
        _ = replace(snapshot, records=(replace(records[0], index=2),))
    with pytest.raises(ValueError, match="pair_index exceeds"):
        _ = replace(snapshot, requested_pairs=4)

    other_order = "BA" if records[0].pair_order == "AB" else "AB"
    other_position = 1 if (records[0].variant == "baseline") == (other_order == "AB") else 2
    with pytest.raises(ValueError, match="deterministic schedule"):
        _ = replace(
            snapshot,
            records=(
                replace(records[0], pair_order=other_order, order_position=other_position),
                *records[1:],
            ),
        )

    with pytest.raises(ValueError, match="chronological"):
        _ = replace(
            snapshot,
            records=(replace(records[0], block_attempt=2), *records[1:]),
        )


def test_paired_snapshot_rejects_duplicate_and_canonically_aliased_record_paths(
    tmp_path: Path,
) -> None:
    snapshot = _paired_report(tmp_path).paired_collections[0]
    records = snapshot.records

    with pytest.raises(ValueError, match="record paths must be unique"):
        _ = replace(snapshot, records=(records[0], replace(records[1], path=records[0].path), *records[2:]))

    aliased_path = records[0].path.parent / "unused-directory" / ".." / records[0].path.name
    with pytest.raises(ValueError, match="record paths must be unique"):
        _ = replace(snapshot, records=(records[0], replace(records[1], path=aliased_path), *records[2:]))


def test_paired_report_rejects_reused_complete_pair_evidence_paths(tmp_path: Path) -> None:
    report = replace(_paired_report(tmp_path), paired_collections=())

    with pytest.raises(ValueError, match="cannot reuse a file as independent evidence"):
        _ = replace(report, baselines=(report.baselines[0], report.baselines[0], *report.baselines[2:]))

    baseline = Path(report.baselines[0])
    alias = str(baseline.parent / "unused-directory" / ".." / baseline.name)
    with pytest.raises(ValueError, match="cannot reuse a file as independent evidence"):
        _ = replace(report, candidates=(alias, *report.candidates[1:]))


def test_paired_snapshot_requires_first_seen_pairs_to_form_a_prefix_and_allows_retries(
    tmp_path: Path,
) -> None:
    snapshot = _paired_report(tmp_path).paired_collections[0]
    records = snapshot.records
    pair_one = records[:2]
    pair_two = records[2:4]

    reordered = tuple(
        replace(record, index=index) for index, record in enumerate((*pair_two, *pair_one, *records[4:]), start=1)
    )
    with pytest.raises(ValueError, match="first appear as a one-based prefix"):
        _ = replace(snapshot, records=reordered)

    no_initial_anchor = (
        replace(pair_one[0], status="failed", returncode=1, error="no matrix"),
        replace(pair_one[1], status="failed", returncode=1, error="no matrix"),
        *records[2:],
    )
    with pytest.raises(ValueError, match="before a successful matrix exists"):
        _ = replace(snapshot, records=no_initial_anchor)

    incomplete_pair_one = (
        pair_one[0],
        replace(pair_one[1], status="failed", returncode=1, error="initial block failed"),
    )
    retry_pair_one = tuple(
        replace(
            record,
            index=len(records) + order_position,
            block_attempt=2,
            path=tmp_path / f"paired-retry-{record.variant}.json",
        )
        for order_position, record in enumerate(pair_one, start=1)
    )
    retried = replace(snapshot, records=(*incomplete_pair_one, *records[2:], *retry_pair_one))

    assert retried.complete_pair_count == snapshot.complete_pair_count
    assert retried.complete is True


def test_automatic_paired_snapshot_validates_provisional_and_joint_design_targets(
    tmp_path: Path,
) -> None:
    report = _paired_report(tmp_path)
    snapshot = report.paired_collections[0]
    first_block = tuple(
        replace(record, status="failed", returncode=1, error="no matrix yet") for record in snapshot.records[:2]
    )
    provisional = replace(
        snapshot,
        automatic_pairs=True,
        requested_pairs=6,
        expected_cells=(),
        baseline_commit=None,
        candidate_commit=None,
        baseline_environment_fingerprint=None,
        candidate_environment_fingerprint=None,
        records=first_block,
    )

    assert provisional.complete is False
    with pytest.raises(ValueError, match="must retain target 6"):
        _ = replace(provisional, requested_pairs=8)
    with pytest.raises(ValueError, match="before a successful matrix exists"):
        _ = replace(
            provisional,
            records=(
                *first_block,
                replace(
                    first_block[0],
                    index=3,
                    pair_index=2,
                    path=tmp_path / "pair-2-before-matrix.json",
                ),
            ),
        )
    with pytest.raises(ValueError, match="smallest complete joint-design supercycle"):
        _ = replace(snapshot, automatic_pairs=True, requested_pairs=5)

    automatic_report = replace(report, paired_collections=(replace(snapshot, automatic_pairs=True),))
    loaded = load_comparison_report(_write_payload(tmp_path, automatic_report.to_dict()))
    assert loaded.paired_collections[0].automatic_pairs is True


def test_paired_snapshot_rejects_invalid_block_membership_and_order(tmp_path: Path) -> None:
    snapshot = _paired_report(tmp_path).paired_collections[0]
    records = snapshot.records
    first = records[0]

    with pytest.raises(ValueError, match="cannot repeat a variant"):
        _ = replace(
            snapshot,
            records=(
                first,
                replace(records[1], variant=first.variant, order_position=first.order_position),
                *records[2:],
            ),
        )

    reversed_block = (
        replace(records[1], index=1),
        replace(records[0], index=2),
        *records[2:],
    )
    with pytest.raises(ValueError, match="scheduled AB/BA order"):
        _ = replace(snapshot, records=reversed_block)

    interleaved = tuple(
        replace(record, index=index)
        for index, record in enumerate(
            (records[0], records[2], records[1], records[3], *records[4:]),
            start=1,
        )
    )
    with pytest.raises(ValueError, match="must be adjacent"):
        _ = replace(snapshot, records=interleaved)

    partial_then_next_pair = tuple(
        replace(record, index=index) for index, record in enumerate((records[0], *records[2:]), start=1)
    )
    with pytest.raises(ValueError, match="partial block must be followed by a retry"):
        _ = replace(snapshot, records=partial_then_next_pair)


def test_paired_snapshot_rejects_invalid_retry_history(tmp_path: Path) -> None:
    snapshot = _paired_report(tmp_path).paired_collections[0]
    records = snapshot.records

    def retry(
        record: BenchmarkPairedRunRecord, *, index: int, attempt: int, succeeded: bool
    ) -> BenchmarkPairedRunRecord:
        return replace(
            record,
            index=index,
            block_attempt=attempt,
            path=record.path.with_name(f"retry-{index}-{record.path.name}"),
            status="succeeded" if succeeded else "failed",
            returncode=0 if succeeded else 1,
            error=None if succeeded else "retry failed",
        )

    with pytest.raises(ValueError, match="attempts must be contiguous"):
        _ = replace(
            snapshot,
            records=(*records, retry(records[0], index=len(records) + 1, attempt=3, succeeded=False)),
        )

    duplicate_complete = (
        *records,
        retry(records[0], index=len(records) + 1, attempt=2, succeeded=True),
        retry(records[1], index=len(records) + 2, attempt=2, succeeded=True),
    )
    with pytest.raises(ValueError, match="two complete blocks"):
        _ = replace(snapshot, records=duplicate_complete)

    with pytest.raises(ValueError, match="cannot retry a pair after"):
        _ = replace(
            snapshot,
            records=(*records, retry(records[0], index=len(records) + 1, attempt=2, succeeded=False)),
        )


def test_paired_snapshot_requires_anchors_to_have_successful_records(tmp_path: Path) -> None:
    snapshot = _paired_report(tmp_path).paired_collections[0]
    records = tuple(
        replace(record, status="failed", returncode=1, error="failed") if record.variant == "baseline" else record
        for record in snapshot.records
    )

    with pytest.raises(ValueError, match="baseline anchors require a successful record"):
        _ = replace(snapshot, records=records)


def test_paired_snapshot_ignores_orphan_successes_when_selecting_complete_pairs(tmp_path: Path) -> None:
    snapshot = _paired_report(tmp_path).paired_collections[0]
    candidate_failed = tuple(
        replace(record, status="failed", returncode=1, error="failed") if record.variant == "candidate" else record
        for record in snapshot.records
    )
    baseline_failed = tuple(
        replace(record, status="failed", returncode=1, error="failed") if record.variant == "baseline" else record
        for record in snapshot.records
    )

    candidate_orphans = replace(
        snapshot,
        candidate_commit=None,
        candidate_environment_fingerprint=None,
        records=candidate_failed,
    )
    baseline_orphans = replace(
        snapshot,
        baseline_commit=None,
        baseline_environment_fingerprint=None,
        records=baseline_failed,
    )

    assert candidate_orphans.complete_pair_records == ()
    assert candidate_orphans.orphan_success_count == 6
    assert baseline_orphans.complete_pair_records == ()
    assert baseline_orphans.orphan_success_count == 6


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"paired_collections": (object(),)}, "BenchmarkPairedCollectionSnapshot"),
        ({"inference_policy": object()}, "InferencePolicy"),
        ({"design": "other"}, "comparison design"),
        ({"precision_policy": object()}, "PrecisionPolicy"),
        ({"precision_policy": PrecisionPolicy(target_half_width_percent=2.5)}, "Independent reports"),
    ],
)
def test_report_rejects_invalid_statistical_design_values(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    report = _report(tmp_path)

    with pytest.raises((TypeError, ValueError), match=message):
        _ = replace(report, **changes)


def test_report_rejects_design_provenance_mismatches(tmp_path: Path) -> None:
    independent = _report(tmp_path)
    paired = _paired_report(tmp_path)

    with pytest.raises(ValueError, match="independent collection provenance"):
        _ = replace(paired, baseline_collections=independent.baseline_collections)
    with pytest.raises(ValueError, match="equal baseline and candidate"):
        _ = replace(paired, candidates=paired.candidates[:-1])
    with pytest.raises(ValueError, match="paired collection provenance"):
        _ = replace(independent, paired_collections=paired.paired_collections)

    without_collection_provenance = replace(paired, paired_collections=())
    assert without_collection_provenance.design == "paired"


def test_report_rejects_inconsistent_precision_plan_family_sizes(tmp_path: Path) -> None:
    report = _paired_report(tmp_path)
    cell = report.comparisons[0]
    plan = cell.precision
    assert plan is not None
    legacy_policy = InferencePolicy(method="legacy_consistency")
    first = replace(cell, inference=None)
    second_plan = replace(plan)
    object.__setattr__(second_plan, "family_size", 2)
    object.__setattr__(second_plan, "adjusted_confidence_level", 0.975)
    second = replace(first, precision=second_plan)

    with pytest.raises(ValueError, match="family sizes are inconsistent across cells"):
        _ = replace(
            report,
            comparisons=(first, second),
            threshold_provenance=report.threshold_provenance * 2,
            inference_policy=legacy_policy,
        )

    with pytest.raises(ValueError, match="family size is inconsistent with planned cells"):
        _ = replace(
            report,
            comparisons=(first, first),
            threshold_provenance=report.threshold_provenance * 2,
            inference_policy=legacy_policy,
        )


def test_report_rejects_inference_policy_and_comparability_mismatches(tmp_path: Path) -> None:
    report = _inference_report(tmp_path)
    cell = report.comparisons[0]

    with pytest.raises(ValueError, match="Legacy-consistency"):
        _ = replace(report, inference_policy=InferencePolicy(method="legacy_consistency"))
    with pytest.raises(ValueError, match="Non-comparable cells"):
        _ = replace(
            report,
            comparisons=(replace(cell, status="incompatible", regression="not_comparable"),),
        )
    with pytest.raises(ValueError, match="require a BenchmarkInference"):
        _ = replace(report, comparisons=(replace(cell, inference=None),))


def test_report_rejects_inference_design_and_policy_mismatches(tmp_path: Path) -> None:
    report = _inference_report(tmp_path)
    cell = report.comparisons[0]
    inference = cell.inference
    assert inference is not None

    paired_inference = replace(inference, design="paired", pair_count=5, strata_count=2)
    with pytest.raises(ValueError, match="design does not match"):
        _ = replace(report, comparisons=(replace(cell, inference=paired_inference),))

    invalid_independent = replace(inference, design="paired", pair_count=5, strata_count=2)
    object.__setattr__(invalid_independent, "design", "independent")
    with pytest.raises(ValueError, match="must not define pair_count"):
        _ = replace(report, comparisons=(replace(cell, inference=invalid_independent),))

    mismatches = (
        (replace(inference, confidence_level=0.9), "confidence level"),
        (replace(inference, multiplicity="none"), "multiplicity"),
        (replace(inference, adjusted_confidence_level=0.96), "adjusted confidence"),
        (replace(inference, estimate_percent=cast(float, inference.estimate_percent) + 1.0), "estimate"),
    )
    for changed, message in mismatches:
        with pytest.raises(ValueError, match=message):
            _ = replace(report, comparisons=(replace(cell, inference=changed),))


def test_report_accepts_unadjusted_and_inadequate_inference(tmp_path: Path) -> None:
    report = _inference_report(tmp_path)
    cell = report.comparisons[0]
    inference = cell.inference
    assert inference is not None

    unadjusted = replace(inference, multiplicity="none")
    unadjusted_report = replace(
        report,
        inference_policy=replace(report.inference_policy, multiplicity="none"),
        comparisons=(replace(cell, inference=unadjusted),),
    )
    assert unadjusted_report.inference_policy.multiplicity == "none"

    inadequate = replace(
        inference,
        estimate_percent=None,
        confidence_low_percent=None,
        confidence_high_percent=None,
        issues=("interval unavailable",),
    )
    inadequate_report = replace(
        report,
        comparisons=(replace(cell, inference=inadequate, regression="inconclusive"),),
    )
    assert inadequate_report.comparisons[0].regression == "inconclusive"

    improved = replace(
        inference,
        confidence_low_percent=6.0,
        confidence_high_percent=7.0,
    )
    improved_report = replace(
        report,
        comparisons=(replace(cell, inference=improved, regression="improved"),),
    )
    assert improved_report.comparisons[0].regression == "improved"


def test_report_rejects_precision_plan_context_mismatches(tmp_path: Path) -> None:
    paired = _paired_report(tmp_path)
    cell = paired.comparisons[0]
    plan = cell.precision
    assert plan is not None
    independent = _inference_report(tmp_path)

    with pytest.raises(ValueError, match="Independent report cells"):
        _ = replace(
            independent,
            comparisons=(replace(independent.comparisons[0], precision=plan),),
        )
    with pytest.raises(ValueError, match="Precision-disabled"):
        _ = replace(paired, precision_policy=PrecisionPolicy())
    with pytest.raises(ValueError, match="Non-matched cells"):
        _ = replace(
            paired,
            comparisons=(
                replace(
                    cell,
                    status="incompatible",
                    regression="not_comparable",
                    inference=None,
                ),
            ),
        )
    with pytest.raises(ValueError, match="Matched cells require"):
        _ = replace(paired, comparisons=(replace(cell, precision=None),))

    not_matched_without_plan = replace(
        paired,
        comparisons=(
            replace(
                cell,
                status="incompatible",
                regression="not_comparable",
                inference=None,
                precision=None,
            ),
        ),
    )
    assert not_matched_without_plan.comparisons[0].precision is None


def test_report_rejects_precision_plan_policy_mismatches(tmp_path: Path) -> None:
    report = _paired_report(tmp_path)
    cell = report.comparisons[0]
    plan = cell.precision
    assert plan is not None
    required_pairs = cast(int, plan.required_pairs)

    def mutated_plan(**changes: object) -> Any:
        """Return a structurally constructed plan with report fields corrupted."""
        changed = replace(plan)
        for name, value in changes.items():
            object.__setattr__(changed, name, value)
        return changed

    mismatches = (
        (replace(plan, pilot_pairs=4, additional_pairs=max(0, required_pairs - 4)), "pilot pair count"),
        (replace(plan, confidence_level=0.9), "confidence level"),
        (replace(plan, multiplicity="none"), "multiplicity"),
        (mutated_plan(strata_count=1), "strata_count does not match"),
        (mutated_plan(pair_count_multiple=4), "does not match paired collection provenance"),
        (mutated_plan(adjusted_confidence_level=0.96), "adjusted confidence"),
        (mutated_plan(pilot_log_ratio_standard_deviation=None), "require variability"),
    )
    for changed, message in mismatches:
        with pytest.raises(ValueError, match=message):
            _ = replace(report, comparisons=(replace(cell, precision=changed),))


def test_report_accepts_unadjusted_precision_plan(tmp_path: Path) -> None:
    report = _paired_report(tmp_path)
    cell = report.comparisons[0]
    inference = cell.inference
    plan = cell.precision
    assert inference is not None
    assert plan is not None

    unadjusted = replace(
        report,
        inference_policy=replace(report.inference_policy, multiplicity="none"),
        comparisons=(
            replace(
                cell,
                inference=replace(inference, multiplicity="none"),
                precision=replace(plan, multiplicity="none"),
            ),
        ),
    )

    assert unadjusted.comparisons[0].precision is not None


def test_v3_loader_rejects_invalid_paired_collection_payloads(tmp_path: Path) -> None:
    payload = _paired_report(tmp_path).to_dict()
    collection = cast(list[dict[str, object]], payload["paired_collections"])[0]
    collection["complete_pairs"] = 4
    with pytest.raises(BenchmarkJsonError, match="inconsistent derived values"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    collection = cast(list[dict[str, object]], payload["paired_collections"])[0]
    record = cast(list[dict[str, object]], collection["runs"])[0]
    record["returncode"] = 1
    with pytest.raises(BenchmarkJsonError, match="Invalid paired collection record"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    collection = cast(list[dict[str, object]], payload["paired_collections"])[0]
    records = cast(list[dict[str, object]], collection["runs"])
    records[1]["path"] = records[0]["path"]
    with pytest.raises(BenchmarkJsonError, match="record paths must be unique"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    collection = cast(list[dict[str, object]], payload["paired_collections"])[0]
    records = cast(list[dict[str, object]], collection["runs"])
    original = Path(cast(str, records[0]["path"]))
    records[1]["path"] = str(original.parent / "unused-directory" / ".." / original.name)
    with pytest.raises(BenchmarkJsonError, match="record paths must be unique"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_loader_rejects_invalid_statistical_policies(tmp_path: Path) -> None:
    payload = _paired_report(tmp_path).to_dict()
    cast(dict[str, object], payload["inference_policy"])["resamples"] = 999
    with pytest.raises(BenchmarkJsonError, match="Invalid inference policy"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cast(dict[str, object], payload["precision_policy"])["target_half_width_percent"] = 0.0
    with pytest.raises(BenchmarkJsonError, match="Invalid precision policy"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_loader_rejects_invalid_inference_and_precision_results(tmp_path: Path) -> None:
    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    cast(dict[str, object], cell["inference"])["pair_count"] = -1
    with pytest.raises(BenchmarkJsonError, match="Invalid benchmark inference"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    cast(dict[str, object], cell["precision"])["adequate"] = False
    with pytest.raises(BenchmarkJsonError, match="Precision-plan adequacy is inconsistent"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    cast(dict[str, object], cell["precision"])["family_size"] = 0
    with pytest.raises(BenchmarkJsonError, match="Expected positive integer"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    plan = cast(dict[str, object], cell["precision"])
    plan["pair_count_multiple"] = cast(int, plan["required_pairs"]) + 1
    with pytest.raises(BenchmarkJsonError, match="Invalid precision plan"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    plan = cast(dict[str, object], cell["precision"])
    plan["unconstrained_required_pairs"] = 99
    with pytest.raises(BenchmarkJsonError, match="Invalid precision plan"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _paired_report(tmp_path).to_dict()
    cast(dict[str, object], payload["precision_policy"])["target_half_width_percent"] = float("nan")
    with pytest.raises(BenchmarkJsonError, match="Expected finite number"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_loader_rejects_inconsistent_evidence_shapes(tmp_path: Path) -> None:
    payload = _inference_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    evidence = cast(dict[str, object], cell["baseline_evidence"])
    _ = cast(list[object], evidence["rounds"]).pop()
    with pytest.raises(BenchmarkJsonError, match="run-aligned fields"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _inference_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    evidence = cast(dict[str, object], cell["baseline_evidence"])
    evidence["sample_count"] = cast(int, evidence["sample_count"]) + 1
    with pytest.raises(BenchmarkJsonError, match="sample_count is inconsistent"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    payload = _inference_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    evidence = cast(dict[str, object], cell["baseline_evidence"])
    evidence["adequate"] = False
    with pytest.raises(BenchmarkJsonError, match="Evidence adequacy is inconsistent"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_loader_rejects_non_mapping_policy(tmp_path: Path) -> None:
    payload = _paired_report(tmp_path).to_dict()
    payload["policy"] = []

    with pytest.raises(BenchmarkJsonError, match="Expected mapping"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_report_accepts_cli_threshold_provenance(tmp_path: Path) -> None:
    report = _report(tmp_path)
    threshold = report.threshold_provenance[0]
    cli_report = replace(
        report,
        policy_provenance=BenchmarkPolicyProvenance(
            selection="explicit",
            cli_overrides=(threshold.field,),
        ),
        threshold_provenance=(replace(threshold, origin="cli"),),
    )

    assert cli_report.threshold_provenance[0].origin == "cli"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (float("nan"), "strict JSON value"),
        ({1: "value"}, "string mapping keys"),
        (object(), "strict JSON value"),
    ],
)
def test_report_serialization_rejects_non_json_compatibility_values(
    tmp_path: Path,
    value: object,
    message: str,
) -> None:
    report = _report(tmp_path)
    finding = RunCompatibilityFinding(
        field="environment",
        baseline_value=value,
        candidate_value=None,
        severity="warning",
        reason="Changed.",
    )
    invalid = replace(
        report,
        compatibility=replace(report.compatibility, findings=(finding,)),
    )

    with pytest.raises(BenchmarkJsonError, match=message):
        _ = invalid.to_dict()


def test_report_serialization_accepts_finite_compatibility_float(tmp_path: Path) -> None:
    report = _report(tmp_path)
    finding = RunCompatibilityFinding(
        field="environment",
        baseline_value=3.5,
        candidate_value=4.5,
        severity="warning",
        reason="Changed.",
    )
    serializable = replace(
        report,
        compatibility=replace(report.compatibility, findings=(finding,)),
    )

    payload = serializable.to_dict()

    compatibility = cast(dict[str, object], payload["compatibility"])
    serialized_finding = cast(list[dict[str, object]], compatibility["findings"])[0]
    assert serialized_finding["baseline_value"] == 3.5


def test_markdown_distinguishes_confidence_interval_from_observed_range(tmp_path: Path) -> None:
    markdown = format_comparison_report_markdown(_inference_report(tmp_path))

    assert "Confidence interval" in markdown
    assert "Observed pairwise range" in markdown
    assert "adjusted confidence 95.00%" in markdown
    assert "Inference method: `bca_bootstrap`" in markdown


def test_v3_report_rejects_inference_inconsistent_with_classification(tmp_path: Path) -> None:
    payload = _inference_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    inference = cast(dict[str, object], cell["inference"])
    inference["confidence_low_percent"] = -1.0
    inference["confidence_high_percent"] = 1.0

    with pytest.raises(BenchmarkJsonError, match="classification is inconsistent"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_report_rejects_inconsistent_inference_adequacy_and_policy(tmp_path: Path) -> None:
    payload = _inference_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    inference = cast(dict[str, object], cell["inference"])
    inference["adequate"] = False
    with pytest.raises(BenchmarkJsonError, match="adequacy is inconsistent"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))

    inference["adequate"] = True
    cast(dict[str, object], payload["inference_policy"])["resamples"] = 2_000
    with pytest.raises(BenchmarkJsonError, match="resamples do not match"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_report_rejects_inconsistent_cell_seed(tmp_path: Path) -> None:
    payload = _inference_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    inference = cast(dict[str, object], cell["inference"])
    inference["random_seed"] = cast(int, inference["random_seed"]) + 1

    with pytest.raises(BenchmarkJsonError, match="random seed is inconsistent"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_report_rejects_inconsistent_inference_family_size(tmp_path: Path) -> None:
    payload = _inference_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    inference = cast(dict[str, object], cell["inference"])
    inference["family_size"] = 2
    inference["adjusted_confidence_level"] = 0.975

    with pytest.raises(BenchmarkJsonError, match="family size is inconsistent"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_v3_report_rejects_misaligned_per_run_diagnostics(tmp_path: Path) -> None:
    payload = _inference_report(tmp_path).to_dict()
    cell = cast(list[dict[str, object]], payload["comparisons"])[0]
    evidence = cast(dict[str, object], cell["baseline_evidence"])
    _ = cast(list[object], evidence["run_iqrs"]).pop()

    with pytest.raises(BenchmarkJsonError, match="Per-run evidence diagnostics"):
        _ = load_comparison_report(_write_payload(tmp_path, payload))


def test_report_version_dispatch_keeps_all_versions_strict(tmp_path: Path) -> None:
    v1_payload = _fixture_payload()
    v1_payload["inference_policy"] = {}
    with pytest.raises(BenchmarkJsonError, match="unknown inference_policy"):
        _ = load_comparison_report(_write_payload(tmp_path, v1_payload))

    v2_payload = _v2_fixture_payload()
    _ = v2_payload.pop("inference_policy")
    with pytest.raises(BenchmarkJsonError, match="missing inference_policy"):
        _ = load_comparison_report(_write_payload(tmp_path, v2_payload))

    v2_payload = _v2_fixture_payload()
    v2_payload["design"] = "independent"
    with pytest.raises(BenchmarkJsonError, match="unknown design"):
        _ = load_comparison_report(_write_payload(tmp_path, v2_payload))

    v3_payload = _inference_report(tmp_path).to_dict()
    _ = v3_payload.pop("precision_policy")
    with pytest.raises(BenchmarkJsonError, match="missing precision_policy"):
        _ = load_comparison_report(_write_payload(tmp_path, v3_payload))


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
        ("schema_version", 4, "Unsupported benchmark comparison report schema version"),
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
