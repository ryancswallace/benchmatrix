"""Tests for the benchmatrix command-line interface."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

import benchmatrix.bench_collection as collection_module
from benchmatrix import __version__, load_comparison_report
from benchmatrix.cli import main

pytestmark = pytest.mark.unit


def test_cli_reports_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _ = main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"benchmatrix {__version__}\n"


def _environment_metadata(*, system: str = "Linux") -> dict[str, object]:
    """Return complete, stable pytest-benchmark environment metadata."""
    return {
        "version": "5.2.3",
        "machine_info": {
            "system": system,
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
    }


def _write_run(
    tmp_path: Path,
    filename: str,
    values: dict[tuple[str, str], float],
    *,
    system: str = "Linux",
) -> Path:
    """Write a valid latency-only benchmatrix run."""
    payload = _run_payload(values, system=system)
    path = tmp_path / filename
    _ = path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_payload(
    values: dict[tuple[str, str], float],
    *,
    system: str = "Linux",
) -> dict[str, object]:
    """Return a valid latency-only benchmatrix run payload."""
    payload = _environment_metadata(system=system)
    payload["commit_info"] = {"id": "abc123"}
    payload["benchmarks"] = [
        {
            "name": f"test_benchmark[{implementation_name}-{case_name}]",
            "extra_info": {
                "benchmatrix_producer": "benchmatrix",
                "benchmatrix_schema_version": 1,
                "metric_name": "single_call_latency",
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
        for (implementation_name, case_name), value in values.items()
    ]
    return payload


def _install_collection_runner(
    monkeypatch: pytest.MonkeyPatch,
    values: Sequence[float | None],
) -> tuple[list[tuple[str, ...]], list[str | None]]:
    """Install a subprocess runner that emits deterministic benchmark files."""
    call_count = 0
    commands: list[tuple[str, ...]] = []
    pytest_addopts: list[str | None] = []

    def runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
        stdout: int | None = None,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        assert check is False
        assert cwd == Path.cwd().resolve()
        assert stdout in {None, subprocess.PIPE}
        assert text is (stdout == subprocess.PIPE)
        commands.append(tuple(command))
        pytest_addopts.append(os.environ.get("PYTEST_ADDOPTS"))
        value = values[call_count]
        call_count += 1
        if value is None:
            return subprocess.CompletedProcess(list(command), 1)
        output_argument = next(argument for argument in command if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        payload = _run_payload({("impl", "small"): value})
        _ = output_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0)

    monkeypatch.setattr(collection_module.subprocess, "run", runner)
    return commands, pytest_addopts


def test_compare_cli_displays_text_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 0.9})

    exit_code = main(["compare", str(baseline), str(candidate), "--minimum-runs", "1"])

    output = capsys.readouterr()
    assert exit_code == 0
    assert output.err == ""
    assert "Compatibility: compatible (0 blocking, 0 warning)" in output.out
    assert "impl | small | single_call_latency | improved | +10.00% | 5.00%" in output.out
    assert "Summary: 1 improved, 0 unchanged, 0 regressed, 0 not comparable" in output.out
    assert "Overall: PASS" in output.out


def test_compare_cli_summary_omits_cell_evidence_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.1})

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--minimum-runs",
            "1",
            "--summary",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert output.err == ""
    assert "impl | small | single_call_latency | regressed | -10.00% | 5.00%" in output.out
    assert "Summary: 0 improved, 0 unchanged, 1 regressed, 0 not comparable" in output.out
    assert "Overall: FAIL" in output.out
    assert "baseline evidence:" not in output.out
    assert "candidate evidence:" not in output.out
    assert "repeated effect range:" not in output.out


def test_compare_cli_summary_rejects_non_text_format(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    exit_code = main(["compare", str(baseline), str(candidate), "--summary", "--format", "json"])

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.out == ""
    assert "--summary requires --format text" in output.err


def test_compare_cli_failure_gate_honors_percentage_threshold(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.1})

    failing_exit = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--fail-on-regression",
            "--threshold",
            "5%",
            "--minimum-runs",
            "1",
        ]
    )
    failing_output = capsys.readouterr().out
    passing_exit = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--fail-on-regression",
            "--threshold",
            "10%",
            "--minimum-runs",
            "1",
        ]
    )
    passing_output = capsys.readouterr().out

    assert failing_exit == 1
    assert "regressed" in failing_output
    assert "Overall: FAIL" in failing_output
    assert passing_exit == 0
    assert "unchanged" in passing_output
    assert "Overall: PASS" in passing_output


def test_compare_cli_without_gate_reports_failure_but_exits_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 2.0})

    exit_code = main(["compare", str(baseline), str(candidate)])

    assert exit_code == 0
    assert "Overall: FAIL" in capsys.readouterr().out


def test_compare_cli_gate_fails_for_incomplete_matrix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(
        tmp_path,
        "baseline.json",
        {("impl", "small"): 1.0, ("impl", "large"): 2.0},
    )
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    exit_code = main(["compare", str(baseline), str(candidate), "--fail-on-regression"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "missing_candidate" in output
    assert "1 not comparable" in output


def test_compare_cli_strict_compatibility_blocks_environment_change(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0}, system="Linux")
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 0.5}, system="Darwin")

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--compatibility",
            "strict",
            "--fail-on-regression",
        ]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Compatibility: blocked" in output
    assert "BLOCKING os.system" in output
    assert "not_comparable" in output


def test_compare_cli_emits_machine_readable_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.2})

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--format",
            "json",
            "--threshold",
            "5",
            "--minimum-runs",
            "1",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    payload = cast(dict[str, object], json.loads(output))
    assert payload["baseline"] == str(baseline)
    assert payload["candidate"] == str(candidate)
    assert payload["producer"] == "benchmatrix"
    assert payload["kind"] == "benchmark_comparison"
    assert payload["schema_version"] == 1
    assert payload["passed"] is False
    assert payload["has_regressions"] is True
    assert payload["summary"] == {
        "improved": 0,
        "inconclusive": 0,
        "not_comparable": 0,
        "regressed": 1,
        "unchanged": 0,
    }
    comparisons = cast(list[dict[str, object]], payload["comparisons"])
    assert comparisons[0]["regression"] == "regressed"
    assert comparisons[0]["threshold_percent"] == 5.0

    report_path = tmp_path / "comparison.json"
    _ = report_path.write_text(output, encoding="utf-8")
    report = load_comparison_report(report_path)
    assert report.to_dict() == payload
    assert report.regressed == report.comparisons


def test_compare_cli_emits_markdown_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.2})

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--format",
            "markdown",
            "--minimum-runs",
            "1",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert output.err == ""
    assert output.out.startswith("# Benchmark comparison\n")
    assert "**Overall:** FAIL" in output.out
    assert "| impl | small | single_call_latency | regressed |" in output.out
    assert "## Evidence and diagnostics" in output.out
    assert "- CLI overrides: `evidence.minimum_runs`" in output.out


def test_compare_cli_appends_github_step_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 0.9})
    summary = tmp_path / "step-summary.md"
    _ = summary.write_text("# Existing summary\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--format",
            "json",
            "--minimum-runs",
            "1",
            "--github-summary",
        ]
    )

    output = capsys.readouterr()
    payload = cast(dict[str, object], json.loads(output.out))
    summary_text = summary.read_text(encoding="utf-8")
    assert exit_code == 0
    assert output.err == ""
    assert payload["comparison_passed"] is True
    assert summary_text.startswith("# Existing summary\n\n# Benchmark comparison\n")
    assert "**Overall:** PASS" in summary_text
    assert "| impl | small | single_call_latency | improved |" in summary_text


def test_compare_cli_github_summary_requires_environment_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", "")

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--minimum-runs",
            "1",
            "--github-summary",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.out == ""
    assert "--github-summary requires GITHUB_STEP_SUMMARY" in output.err


def test_compare_cli_reports_invalid_benchmark_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = tmp_path / "bad.json"
    _ = baseline.write_text("not json", encoding="utf-8")
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    exit_code = main(["compare", str(baseline), str(candidate)])

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.out == ""
    assert output.err.startswith("benchmatrix: error: Invalid JSON")


def test_compare_cli_combines_repeated_files_and_reports_trust_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline_one = _write_run(tmp_path, "baseline-1.json", {("impl", "small"): 1.0})
    baseline_two = _write_run(tmp_path, "baseline-2.json", {("impl", "small"): 1.02})
    candidate_one = _write_run(tmp_path, "candidate-1.json", {("impl", "small"): 1.1})
    candidate_two = _write_run(tmp_path, "candidate-2.json", {("impl", "small"): 1.12})

    exit_code = main(
        [
            "compare",
            str(baseline_one),
            str(candidate_one),
            "--baseline-run",
            str(baseline_two),
            "--candidate-run",
            str(candidate_two),
            "--fail-on-regression",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Runs: 2 baseline, 2 candidate" in output
    assert "Environment pairs checked: 3" in output
    assert (
        "baseline evidence: adequate; runs=2/2; rounds=[5,5]; iterations=[1,1]; " + "sample_counts=[5,5]; samples=10"
    ) in output
    assert "IQR=" in output
    assert "CV=" in output
    assert "outliers=" in output
    assert "repeated effect range:" in output
    assert "regressed" in output


def test_compare_cli_marks_single_file_evidence_inconclusive_by_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.2})

    exit_code = main(["compare", str(baseline), str(candidate), "--fail-on-regression"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "inconclusive" in output
    assert "Inadequate evidence:" in output
    assert "only 1 run(s) contain the cell; 2 required" in output


def test_compare_cli_repeated_json_lists_sources_and_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline_one = _write_run(tmp_path, "baseline-1.json", {("impl", "small"): 1.0})
    baseline_two = _write_run(tmp_path, "baseline-2.json", {("impl", "small"): 1.01})
    candidate_one = _write_run(tmp_path, "candidate-1.json", {("impl", "small"): 1.0})
    candidate_two = _write_run(tmp_path, "candidate-2.json", {("impl", "small"): 1.01})

    exit_code = main(
        [
            "compare",
            str(baseline_one),
            str(candidate_one),
            "--baseline-run",
            str(baseline_two),
            "--candidate-run",
            str(candidate_two),
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert payload["baselines"] == [str(baseline_one), str(baseline_two)]
    assert payload["candidates"] == [str(candidate_one), str(candidate_two)]
    evidence_policy = cast(dict[str, object], payload["evidence_policy"])
    assert evidence_policy["minimum_runs"] == 2
    comparisons = cast(list[dict[str, object]], payload["comparisons"])
    baseline_evidence = cast(dict[str, object], comparisons[0]["baseline_evidence"])
    assert baseline_evidence["rounds"] == [5, 5]
    assert baseline_evidence["sample_count"] == 10
    assert baseline_evidence["adequate"] is True


def test_compare_cli_discovers_policy_and_reports_selector_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / "pyproject.toml").write_text(
        """
[tool.benchmatrix.compatibility]
mode = "off"

[tool.benchmatrix.evidence]
minimum_runs = 1
minimum_samples_per_run = 5
require_rounds = true
require_iterations = true
maximum_cv = 1.0
maximum_outlier_fraction = 1.0

[tool.benchmatrix.regression]
default_threshold_percent = 20

[tool.benchmatrix.regression.by_metric]
single_call_latency = 15

[tool.benchmatrix.regression.by_implementation]
impl = 10

[tool.benchmatrix.regression.by_case]
special = 5

[[tool.benchmatrix.regression.by_cell]]
implementation = "impl"
case = "exact"
metric = "single_call_latency"
threshold_percent = 2
""",
        encoding="utf-8",
    )
    baseline = _write_run(
        tmp_path,
        "baseline.json",
        {
            ("other", "default"): 1.0,
            ("impl", "implementation"): 1.0,
            ("impl", "special"): 1.0,
            ("impl", "exact"): 1.0,
        },
    )
    candidate = _write_run(
        tmp_path,
        "candidate.json",
        {
            ("other", "default"): 1.08,
            ("impl", "implementation"): 1.08,
            ("impl", "special"): 1.08,
            ("impl", "exact"): 1.08,
        },
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(["compare", str(baseline), str(candidate), "--format", "json"])

    assert exit_code == 0
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    policy = cast(dict[str, object], payload["policy"])
    assert policy["selection"] == "discovered"
    assert policy["configuration_file"] == str((tmp_path / "pyproject.toml").resolve())
    assert policy["cli_overrides"] == []
    assert cast(dict[str, object], payload["compatibility"])["mode"] == "off"
    evidence = cast(dict[str, object], payload["evidence_policy"])
    assert evidence["maximum_cv"] == 1.0
    assert evidence["maximum_outlier_fraction"] == 1.0

    comparisons = cast(list[dict[str, object]], payload["comparisons"])
    by_cell = {(cast(str, cell["implementation_name"]), cast(str, cell["case_name"])): cell for cell in comparisons}
    assert by_cell[("other", "default")]["threshold_percent"] == 15.0
    assert by_cell[("impl", "implementation")]["threshold_percent"] == 10.0
    assert by_cell[("impl", "special")]["threshold_percent"] == 5.0
    assert by_cell[("impl", "exact")]["threshold_percent"] == 2.0
    assert cast(dict[str, object], by_cell[("other", "default")]["threshold_source"]) == {
        "field": "regression.by_metric.single_call_latency",
        "origin": "configuration",
        "scope": "metric",
    }
    assert cast(dict[str, object], by_cell[("impl", "implementation")]["threshold_source"])["scope"] == (
        "implementation"
    )
    assert cast(dict[str, object], by_cell[("impl", "special")]["threshold_source"])["scope"] == "case"
    assert cast(dict[str, object], by_cell[("impl", "exact")]["threshold_source"])["scope"] == "cell"


def test_compare_cli_overrides_only_corresponding_configured_scalars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "policy.toml"
    _ = config.write_text(
        """
[tool.benchmatrix.compatibility]
mode = "strict"

[tool.benchmatrix.evidence]
minimum_runs = 4
minimum_samples_per_run = 9

[tool.benchmatrix.regression]
default_threshold_percent = 20

[tool.benchmatrix.regression.by_case]
special = 10
""",
        encoding="utf-8",
    )
    baseline = _write_run(
        tmp_path,
        "baseline.json",
        {("impl", "default"): 1.0, ("impl", "special"): 1.0},
    )
    candidate = _write_run(
        tmp_path,
        "candidate.json",
        {("impl", "default"): 1.08, ("impl", "special"): 1.08},
    )
    monkeypatch.chdir(tmp_path / "..")

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--config",
            str(config),
            "--threshold",
            "1",
            "--compatibility",
            "off",
            "--minimum-runs",
            "1",
            "--minimum-samples",
            "5",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    policy = cast(dict[str, object], payload["policy"])
    assert policy["selection"] == "explicit"
    assert policy["cli_overrides"] == [
        "compatibility.mode",
        "regression.default_threshold_percent",
        "evidence.minimum_runs",
        "evidence.minimum_samples_per_run",
    ]
    regression = cast(dict[str, object], policy["regression"])
    assert regression["default_threshold_percent"] == 1.0
    assert regression["by_case"] == {"special": 10.0}
    comparisons = cast(list[dict[str, object]], payload["comparisons"])
    by_case = {cast(str, cell["case_name"]): cell for cell in comparisons}
    assert by_case["default"]["regression"] == "regressed"
    assert by_case["special"]["regression"] == "unchanged"
    assert cast(dict[str, object], by_case["default"]["threshold_source"])["origin"] == "cli"
    assert cast(dict[str, object], by_case["special"]["threshold_source"])["origin"] == "configuration"


def test_compare_cli_no_config_disables_discovered_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / "pyproject.toml").write_text(
        """
[tool.benchmatrix.evidence]
minimum_runs = 1

[tool.benchmatrix.regression]
default_threshold_percent = 99
""",
        encoding="utf-8",
    )
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.1})
    monkeypatch.chdir(tmp_path)

    configured_exit = main(["compare", str(baseline), str(candidate), "--format", "json"])
    configured = cast(dict[str, object], json.loads(capsys.readouterr().out))
    disabled_exit = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--no-config",
            "--minimum-runs",
            "1",
            "--format",
            "json",
        ]
    )
    disabled = cast(dict[str, object], json.loads(capsys.readouterr().out))

    assert configured_exit == 0
    assert cast(list[dict[str, object]], configured["comparisons"])[0]["regression"] == "unchanged"
    assert disabled_exit == 0
    disabled_policy = cast(dict[str, object], disabled["policy"])
    assert disabled_policy["selection"] == "disabled"
    assert disabled_policy["configuration_file"] is None
    assert cast(list[dict[str, object]], disabled["comparisons"])[0]["regression"] == "regressed"


def test_compare_cli_text_reports_policy_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "policy.toml"
    _ = config.write_text(
        """
[tool.benchmatrix.evidence]
minimum_runs = 1
""",
        encoding="utf-8",
    )
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})
    monkeypatch.chdir(tmp_path / "..")

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--config",
            str(config),
            "--threshold",
            "7",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert f"Policy: {config.resolve()} (explicit)" in output.out
    assert "Policy CLI overrides: regression.default_threshold_percent" in output.out


def test_compare_cli_reports_invalid_explicit_policy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "policy.toml"
    _ = config.write_text('[project]\nname = "example"\n', encoding="utf-8")
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--config",
            str(config),
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.out == ""
    assert "does not contain [tool.benchmatrix]" in output.err


def test_compare_cli_rejects_config_and_no_config_together(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    with pytest.raises(SystemExit, match="2"):
        _ = main(
            [
                "compare",
                str(baseline),
                str(candidate),
                "--config",
                str(tmp_path / "policy.toml"),
                "--no-config",
            ]
        )

    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("threshold", ["", "%", "bad", "nan", "inf", "-1%"])
def test_compare_cli_rejects_invalid_threshold(
    tmp_path: Path,
    threshold: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    with pytest.raises(SystemExit, match="2"):
        _ = main(["compare", str(baseline), str(candidate), f"--threshold={threshold}"])

    assert "percentage" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--minimum-runs", "0"),
        ("--minimum-runs", "1.5"),
        ("--minimum-samples", "-1"),
    ],
)
def test_compare_cli_rejects_invalid_evidence_counts(
    tmp_path: Path,
    option: str,
    value: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    with pytest.raises(SystemExit, match="2"):
        _ = main(["compare", str(baseline), str(candidate), option, value])

    error = capsys.readouterr().err
    assert "count" in error or "integer" in error


def test_collect_cli_creates_first_class_group_and_json_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_collection_runner(monkeypatch, (1.0, 1.01))
    output = tmp_path / "collection"

    exit_code = main(
        [
            "collect",
            "--runs",
            "2",
            "--output",
            str(output),
            "--format",
            "json",
            "--",
            "uv",
            "run",
            "pytest",
            "benchmarks.py",
        ]
    )

    assert exit_code == 0
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert set(payload) == {
        "attempted_runs",
        "command",
        "commit",
        "complete",
        "created_at",
        "cwd",
        "environment_fingerprint",
        "expected_cells",
        "failed_runs",
        "manifest",
        "pending_runs",
        "remaining_runs",
        "requested_runs",
        "retry_attempts",
        "runs",
        "successful_runs",
    }
    assert payload["complete"] is True
    assert payload["successful_runs"] == 2
    assert payload["failed_runs"] == 0
    assert payload["command"] == ["uv", "run", "pytest", "benchmarks.py"]
    assert Path(cast(str, payload["manifest"])).exists()
    assert payload["environment_fingerprint"] is not None
    cells = cast(list[dict[str, object]], payload["expected_cells"])
    assert cells
    assert all(set(cell) == {"implementation_name", "case_name", "metric_name"} for cell in cells)


def test_collect_json_routes_real_child_stdout_to_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps(_run_payload({("impl", "small"): 1.0}))
    script = tmp_path / "write_benchmark.py"
    _ = script.write_text(
        "\n".join(
            (
                "import sys",
                "from pathlib import Path",
                f"payload = {payload!r}",
                "argument = next(value for value in sys.argv if value.startswith('--benchmark-json='))",
                "Path(argument.split('=', 1)[1]).write_text(payload, encoding='utf-8')",
                "print('child benchmark output')",
            )
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "collect",
            "--runs",
            "1",
            "--output",
            str(tmp_path / "collection"),
            "--format",
            "json",
            "--",
            sys.executable,
            str(script),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert cast(dict[str, object], json.loads(captured.out))["complete"] is True
    assert "child benchmark output" not in captured.out
    assert "child benchmark output" in captured.err


def test_measure_cli_builds_isolated_pytest_command_and_forwards_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--cov=benchmatrix")
    commands, child_addopts = _install_collection_runner(monkeypatch, (1.0, 1.01))
    output = tmp_path / "measure"

    exit_code = main(
        [
            "measure",
            "--runs",
            "2",
            "--output",
            str(output),
            "--format",
            "json",
            "benchmarks.py",
            "other_benchmarks.py",
            "--",
            "-k",
            "small",
        ]
    )

    assert exit_code == 0
    expected = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--benchmark-quiet",
        "-o",
        "addopts=",
        "benchmarks.py",
        "other_benchmarks.py",
        "-k",
        "small",
    ]
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert payload["command"] == expected
    assert [list(command[:-1]) for command in commands] == [expected, expected]
    assert child_addopts == [None, None]
    assert os.environ["PYTEST_ADDOPTS"] == "--cov=benchmatrix"


def test_measure_cli_can_inherit_pytest_addopts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "-ra")
    _, child_addopts = _install_collection_runner(monkeypatch, (1.0,))

    exit_code = main(
        [
            "measure",
            "--runs",
            "1",
            "--output",
            str(tmp_path / "inherited"),
            "--format",
            "json",
            "--inherit-pytest-addopts",
            "benchmarks.py",
        ]
    )

    assert exit_code == 0
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert payload["command"] == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--benchmark-quiet",
        "benchmarks.py",
    ]
    assert child_addopts == ["-ra"]


@pytest.mark.parametrize("argument", ["--benchmark-json=custom.json", "--benchmark-disable", "--benchmark-skip"])
def test_measure_cli_rejects_conflicting_pytest_arguments(
    tmp_path: Path,
    argument: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "measure",
            "--output",
            str(tmp_path / "invalid"),
            "benchmarks.py",
            "--",
            argument,
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.out == ""
    assert argument.split("=", maxsplit=1)[0] in output.err


def test_measure_cli_requires_a_target_for_new_collection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["measure", "--output", str(tmp_path / "missing")])

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.out == ""
    assert "At least one pytest target is required" in output.err


def test_measure_cli_resumes_without_repeating_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "resume-measure"
    _install_collection_runner(monkeypatch, (1.0, None))
    assert main(["measure", "--runs", "2", "--output", str(output), "benchmarks.py"]) == 1
    _ = capsys.readouterr()

    commands, _ = _install_collection_runner(monkeypatch, (1.01,))
    assert main(["measure", "--retry-failed", "--output", str(output)]) == 0

    assert list(commands[0][:-1]) == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--benchmark-quiet",
        "-o",
        "addopts=",
        "benchmarks.py",
    ]


def test_collect_cli_records_partial_failures_and_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_collection_runner(monkeypatch, (1.0, None))

    exit_code = main(
        [
            "collect",
            "--runs",
            "2",
            "--output",
            str(tmp_path / "partial"),
            "--",
            "pytest",
            "benchmarks.py",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 1
    assert output.err == ""
    assert "Collection: 1/2 succeeded, 1 failed" in output.out
    assert "run 002: failed" in output.out
    assert "Overall: FAIL" in output.out


def test_collect_cli_retries_failed_runs_without_repeating_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "retry"
    _install_collection_runner(monkeypatch, (1.0, None))
    assert (
        main(
            [
                "collect",
                "--runs",
                "2",
                "--output",
                str(output),
                "--",
                "pytest",
                "benchmarks.py",
            ]
        )
        == 1
    )
    _ = capsys.readouterr()

    _install_collection_runner(monkeypatch, (1.01,))
    exit_code = main(
        [
            "collect",
            "--output",
            str(output),
            "--retry-failed",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert payload["complete"] is True
    assert payload["requested_runs"] == 2
    assert payload["successful_runs"] == 2
    assert payload["failed_runs"] == 1
    assert payload["attempted_runs"] == 3
    assert payload["retry_attempts"] == 1
    assert payload["pending_runs"] == 0
    assert payload["remaining_runs"] == 0
    records = cast(list[dict[str, object]], payload["runs"])
    assert [record["status"] for record in records] == ["succeeded", "failed", "succeeded"]
    assert all(
        set(record)
        == {
            "commit",
            "duration_seconds",
            "environment_fingerprint",
            "error",
            "index",
            "path",
            "returncode",
            "started_at",
            "status",
            "warnings",
        }
        for record in records
    )


def test_collect_cli_resume_rejects_changed_command_and_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "resume-validation"
    _install_collection_runner(monkeypatch, (1.0,))
    assert main(["collect", "--runs", "1", "--output", str(output), "--", "pytest"]) == 0
    _ = capsys.readouterr()

    command_exit = main(
        [
            "collect",
            "--resume",
            "--output",
            str(output),
            "--",
            "pytest",
            "other.py",
        ]
    )
    command_output = capsys.readouterr()
    assert command_exit == 2
    assert "Resume command does not match" in command_output.err

    count_exit = main(
        [
            "collect",
            "--resume",
            "--runs",
            "2",
            "--output",
            str(output),
        ]
    )
    count_output = capsys.readouterr()
    assert count_exit == 2
    assert "does not match the manifest target" in count_output.err


def test_compare_cli_expands_collection_directories_and_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_collection_runner(monkeypatch, (1.0, 1.01))
    baseline = tmp_path / "baseline"
    assert main(["collect", "--runs", "2", "--output", str(baseline), "--", "pytest"]) == 0
    _ = capsys.readouterr()

    _install_collection_runner(monkeypatch, (1.2, 1.21))
    candidate = tmp_path / "candidate"
    assert main(["collect", "--runs", "2", "--output", str(candidate), "--", "pytest"]) == 0
    _ = capsys.readouterr()

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate / "benchmatrix-manifest.json"),
            "--fail-on-regression",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 1
    assert output.err == ""
    assert "Baseline collection: complete; 2/2 succeeded" in output.out
    assert "Candidate collection: complete; 2/2 succeeded" in output.out
    assert "Runs: 2 baseline, 2 candidate" in output.out
    assert "regressed" in output.out


def test_compare_cli_rejects_duplicate_and_overlapping_run_sources(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _write_run(tmp_path, "baseline.json", {("impl", "small"): 1.0})
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    duplicate_exit = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--baseline-run",
            str(baseline),
        ]
    )
    duplicate_output = capsys.readouterr()
    assert duplicate_exit == 2
    assert "Duplicate benchmark run source" in duplicate_output.err

    overlap_exit = main(["compare", str(baseline), str(baseline)])
    overlap_output = capsys.readouterr()
    assert overlap_exit == 2
    assert "Baseline and candidate run sources overlap" in overlap_output.err


def test_compare_cli_incomplete_collection_cannot_pass_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_collection_runner(monkeypatch, (1.0, None))
    baseline = tmp_path / "baseline"
    assert main(["collect", "--runs", "2", "--output", str(baseline), "--", "pytest"]) == 1
    _ = capsys.readouterr()
    _install_collection_runner(monkeypatch, (1.0, 1.0))
    candidate = tmp_path / "candidate"
    assert main(["collect", "--runs", "2", "--output", str(candidate), "--", "pytest"]) == 0
    _ = capsys.readouterr()

    exit_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--minimum-runs",
            "1",
            "--fail-on-regression",
            "--format",
            "json",
        ]
    )

    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert exit_code == 1
    assert payload["comparison_passed"] is True
    assert payload["passed"] is False
    collections = cast(list[dict[str, object]], payload["baseline_collections"])
    assert collections[0]["complete"] is False


def test_collect_cli_reports_invalid_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["collect", "--output", str(tmp_path / "runs"), "--"])

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.out == ""
    assert "pytest command is required" in output.err


def test_compare_cli_rejects_collection_without_successful_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_collection_runner(monkeypatch, (None,))
    failed = tmp_path / "failed"
    assert main(["collect", "--runs", "1", "--output", str(failed), "--", "pytest"]) == 1
    _ = capsys.readouterr()
    candidate = _write_run(tmp_path, "candidate.json", {("impl", "small"): 1.0})

    exit_code = main(["compare", str(failed), str(candidate)])

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.out == ""
    assert "contains no successful runs" in output.err


def test_policy_show_reports_complete_effective_policy_as_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "policy.toml"
    _ = config.write_text(
        """
[tool.benchmatrix.compatibility]
mode = "strict"

[tool.benchmatrix.evidence]
minimum_runs = 4
maximum_cv = 0.1

[tool.benchmatrix.regression]
default_threshold_percent = 6

[tool.benchmatrix.regression.by_metric]
tail_latency = 8

[[tool.benchmatrix.regression.by_cell]]
implementation = "impl"
case = "small"
metric = "single_call_latency"
threshold_percent = 3
""",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "policy",
            "show",
            "--config",
            str(config),
            "--format",
            "json",
        ]
    )

    output = capsys.readouterr()
    payload = cast(dict[str, object], json.loads(output.out))
    assert exit_code == 0
    assert output.err == ""
    assert set(payload) == {
        "compatibility",
        "configured",
        "configured_fields",
        "error",
        "evidence",
        "kind",
        "producer",
        "regression",
        "schema_version",
        "selection",
        "source",
        "valid",
    }
    assert payload["producer"] == "benchmatrix"
    assert payload["kind"] == "benchmark_policy"
    assert payload["schema_version"] == 1
    assert payload["valid"] is True
    assert payload["error"] is None
    assert payload["selection"] == "explicit"
    assert payload["source"] == str(config.resolve())
    assert payload["configured"] is True
    compatibility = cast(dict[str, object], payload["compatibility"])
    evidence = cast(dict[str, object], payload["evidence"])
    regression = cast(dict[str, object], payload["regression"])
    assert set(compatibility) == {"mode"}
    assert set(evidence) == {
        "maximum_cv",
        "maximum_outlier_fraction",
        "minimum_runs",
        "minimum_samples_per_run",
        "require_iterations",
        "require_rounds",
    }
    assert set(regression) == {
        "by_case",
        "by_cell",
        "by_implementation",
        "by_metric",
        "default_threshold_percent",
    }
    assert compatibility["mode"] == "strict"
    assert evidence["minimum_runs"] == 4
    assert evidence["maximum_cv"] == 0.1
    assert regression["default_threshold_percent"] == 6.0
    assert regression["by_metric"] == {"tail_latency": 8.0}
    assert regression["by_cell"] == [
        {
            "implementation": "impl",
            "case": "small",
            "metric": "single_call_latency",
            "threshold_percent": 3.0,
        }
    ]

    assert main(["policy", "show", "--config", str(config)]) == 0
    text_output = capsys.readouterr()
    assert "by_metric:" in text_output.out
    assert "tail_latency: 8" in text_output.out
    assert "by_cell:" in text_output.out
    assert "impl/small/single_call_latency: 3" in text_output.out


def test_policy_show_text_can_inspect_defaults_without_discovery(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["policy", "show", "--no-config"])

    output = capsys.readouterr()
    assert exit_code == 0
    assert output.err == ""
    assert "Benchmark policy: valid" in output.out
    assert "Selection: disabled" in output.out
    assert "Source: built-in defaults" in output.out
    assert "minimum_runs: 2" in output.out
    assert "default_threshold_percent: 5" in output.out
    assert "by_metric: none" in output.out


def test_policy_show_discovers_from_explicit_search_location(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    nested = project / "src"
    nested.mkdir(parents=True)
    config = project / "pyproject.toml"
    _ = config.write_text(
        "[tool.benchmatrix.regression]\ndefault_threshold_percent = 9\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "policy",
            "show",
            "--search-from",
            str(nested),
            "--format",
            "json",
        ]
    )

    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert exit_code == 0
    assert payload["selection"] == "discovered"
    assert payload["source"] == str(config.resolve())


def test_policy_validate_supports_text_json_and_quiet_ci_modes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    valid = tmp_path / "valid.toml"
    invalid = tmp_path / "invalid.toml"
    _ = valid.write_text(
        "[tool.benchmatrix.evidence]\nminimum_runs = 3\n",
        encoding="utf-8",
    )
    _ = invalid.write_text(
        "[tool.benchmatrix.evidence]\nminimum_runs = 0\n",
        encoding="utf-8",
    )

    assert main(["policy", "validate", "--config", str(valid)]) == 0
    text_output = capsys.readouterr()
    assert text_output.err == ""
    assert "Benchmark policy is valid:" in text_output.out

    assert main(["policy", "validate", "--config", str(valid), "--quiet"]) == 0
    quiet_output = capsys.readouterr()
    assert quiet_output.out == ""
    assert quiet_output.err == ""

    assert main(["policy", "validate", "--config", str(valid), "--format", "json"]) == 0
    valid_json = capsys.readouterr()
    valid_payload = cast(dict[str, object], json.loads(valid_json.out))
    assert valid_json.err == ""
    assert valid_payload["valid"] is True
    assert valid_payload["selection"] == "explicit"

    assert main(["policy", "validate", "--config", str(invalid)]) == 2
    invalid_text = capsys.readouterr()
    assert invalid_text.out == ""
    assert "minimum_runs must be a positive integer" in invalid_text.err

    assert (
        main(
            [
                "policy",
                "validate",
                "--config",
                str(invalid),
                "--format",
                "json",
            ]
        )
        == 2
    )
    invalid_json = capsys.readouterr()
    payload = cast(dict[str, object], json.loads(invalid_json.out))
    assert invalid_json.err == ""
    assert payload == {
        "error": (
            f"Invalid benchmark policy in {invalid.resolve()}: "
            + "EvidencePolicy.minimum_runs must be a positive integer."
        ),
        "kind": "benchmark_policy",
        "producer": "benchmatrix",
        "schema_version": 1,
        "valid": False,
    }


def test_collect_cli_text_reports_environment_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    call_count = 0

    def runner(
        command: Sequence[str],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        assert check is False
        assert cwd == Path.cwd().resolve()
        call_count += 1
        output_argument = next(argument for argument in command if argument.startswith("--benchmark-json="))
        output_path = Path(output_argument.split("=", maxsplit=1)[1])
        payload = _run_payload({("impl", "small"): 1.0})
        machine = cast(dict[str, object], payload["machine_info"])
        machine["python_version"] = f"3.14.{5 + call_count}"
        _ = output_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0)

    monkeypatch.setattr(collection_module.subprocess, "run", runner)

    exit_code = main(
        [
            "collect",
            "--runs",
            "2",
            "--output",
            str(tmp_path / "warnings"),
            "--",
            "pytest",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert "environment warning(s)" in output.out


def test_cli_requires_a_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        _ = main([])

    assert "the following arguments are required: command" in capsys.readouterr().err
