"""Tests for version-controlled benchmatrix policy configuration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from benchmatrix import (
    BenchmarkPolicyConfig,
    BenchmarkPolicyError,
    EvidencePolicy,
    RegressionPolicy,
    RunCompatibilityPolicy,
    default_benchmark_policy,
    load_benchmark_policy,
)

pytestmark = pytest.mark.unit


def _write_config(tmp_path: Path, text: str, *, filename: str = "pyproject.toml") -> Path:
    """Write a TOML configuration file."""
    path = tmp_path / filename
    _ = path.write_text(text, encoding="utf-8")
    return path


def test_default_policy_matches_library_defaults() -> None:
    config = default_benchmark_policy()

    assert config.compatibility == RunCompatibilityPolicy()
    assert config.evidence == EvidencePolicy()
    assert config.regression == RegressionPolicy()
    assert config.source is None
    assert config.configured_fields == frozenset()
    assert config.is_configured is False


def test_load_policy_parses_all_supported_sections(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        """
[project]
name = "example"

[tool.benchmatrix.compatibility]
mode = "strict"

[tool.benchmatrix.evidence]
minimum_runs = 3
minimum_samples_per_run = 7
require_rounds = false
require_iterations = false
maximum_cv = 0.1
maximum_outlier_fraction = 0.05

[tool.benchmatrix.regression]
default_threshold_percent = 6.0

[tool.benchmatrix.regression.by_metric]
tail_latency = 8.0

[tool.benchmatrix.regression.by_implementation]
reference = 3.0

[tool.benchmatrix.regression.by_case]
large = 10.0

[[tool.benchmatrix.regression.by_cell]]
implementation = "reference"
case = "large"
metric = "tail_latency"
threshold_percent = 12.0
""",
    )

    config = load_benchmark_policy(path)

    assert config.source == path.resolve()
    assert config.is_configured is True
    assert config.compatibility.mode == "strict"
    assert config.evidence == EvidencePolicy(
        minimum_runs=3,
        minimum_samples_per_run=7,
        require_rounds=False,
        require_iterations=False,
        maximum_cv=0.1,
        maximum_outlier_fraction=0.05,
    )
    assert config.regression.default_threshold_percent == 6.0
    assert config.regression.by_metric == {"tail_latency": 8.0}
    assert config.regression.by_implementation == {"reference": 3.0}
    assert config.regression.by_case == {"large": 10.0}
    assert config.regression.by_cell == {("reference", "large", "tail_latency"): 12.0}
    assert config.regression.threshold_scope_for("reference", "large", "tail_latency") == "cell"
    assert config.configured_fields == {
        "compatibility.mode",
        "evidence.minimum_runs",
        "evidence.minimum_samples_per_run",
        "evidence.require_rounds",
        "evidence.require_iterations",
        "evidence.maximum_cv",
        "evidence.maximum_outlier_fraction",
        "regression.default_threshold_percent",
        "regression.by_metric.tail_latency",
        "regression.by_implementation.reference",
        "regression.by_case.large",
        "regression.by_cell.reference.large.tail_latency",
    }


def test_discovery_uses_nearest_pyproject_and_accepts_file_search_location(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    nested = project / "src" / "package"
    nested.mkdir(parents=True)
    path = _write_config(
        project,
        """
[tool.benchmatrix.regression]
default_threshold_percent = 9.0
""",
    )
    source_file = nested / "module.py"
    _ = source_file.write_text("", encoding="utf-8")

    config = load_benchmark_policy(search_from=source_file)

    assert config.source == path.resolve()
    assert config.regression.default_threshold_percent == 9.0


def test_discovery_stops_at_nearest_project_without_benchmatrix_table(
    tmp_path: Path,
) -> None:
    _ = _write_config(
        tmp_path,
        """
[tool.benchmatrix.regression]
default_threshold_percent = 99.0
""",
    )
    child = tmp_path / "child"
    nested = child / "src"
    nested.mkdir(parents=True)
    _ = _write_config(child, '[project]\nname = "child"\n')

    config = load_benchmark_policy(search_from=nested)

    assert config.source is None
    assert config.regression.default_threshold_percent == 5.0


def test_discovery_without_pyproject_uses_defaults(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()

    config = load_benchmark_policy(search_from=isolated)

    assert config == default_benchmark_policy()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not toml =", "Invalid TOML"),
        ('tool = "bad"', "Expected table at tool"),
        ("[tool]\nother = true\n", r"does not contain \[tool\.benchmatrix\]"),
        ("[tool.benchmatrix]\nunknown = true\n", r"Unknown key\(s\)"),
        ('[tool.benchmatrix]\ncompatibility = "strict"\n', "Expected table"),
        ('[tool.benchmatrix.compatibility]\nmode = "unknown"\n', "Unsupported run compatibility mode"),
        ("[tool.benchmatrix.evidence]\nminimum_runs = 0\n", "positive integer"),
        ("[tool.benchmatrix.evidence]\nrequire_rounds = 1\n", "must be a boolean"),
        ("[tool.benchmatrix.regression]\ndefault_threshold_percent = -1\n", "must not be negative"),
        (
            "[tool.benchmatrix.regression.by_metric]\nunknown = 1\n",
            "Unsupported regression policy metric",
        ),
        ('[tool.benchmatrix.regression]\nby_cell = "bad"\n', "Expected array"),
        ('[[tool.benchmatrix.regression.by_cell]]\nimplementation = "impl"\n', "Missing key"),
        (
            """
[[tool.benchmatrix.regression.by_cell]]
implementation = ""
case = "large"
metric = "tail_latency"
threshold_percent = 1
""",
            "Expected non-empty string",
        ),
        (
            """
[[tool.benchmatrix.regression.by_cell]]
implementation = "impl"
case = "large"
metric = "unknown"
threshold_percent = 1
""",
            "Unsupported regression policy metric",
        ),
        (
            """
[[tool.benchmatrix.regression.by_cell]]
implementation = "impl"
case = "large"
metric = "tail_latency"
threshold_percent = 1
surprise = true
""",
            "Unknown key",
        ),
        (
            """
[[tool.benchmatrix.regression.by_cell]]
implementation = "impl"
case = "large"
metric = "tail_latency"
threshold_percent = 1

[[tool.benchmatrix.regression.by_cell]]
implementation = "impl"
case = "large"
metric = "tail_latency"
threshold_percent = 2
""",
            "Duplicate exact-cell",
        ),
    ],
)
def test_explicit_policy_rejects_invalid_configuration(
    tmp_path: Path,
    text: str,
    message: str,
) -> None:
    path = _write_config(tmp_path, text)

    with pytest.raises(BenchmarkPolicyError, match=message):
        _ = load_benchmark_policy(path)


def test_explicit_policy_reports_missing_file_and_missing_table(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkPolicyError, match="Could not read"):
        _ = load_benchmark_policy(tmp_path / "missing.toml")

    path = _write_config(tmp_path, '[project]\nname = "example"\n')
    with pytest.raises(BenchmarkPolicyError, match=r"does not contain \[tool\.benchmatrix\]"):
        _ = load_benchmark_policy(path)


def test_empty_benchmatrix_table_selects_file_with_defaults(tmp_path: Path) -> None:
    path = _write_config(tmp_path, "[tool.benchmatrix]\n")

    config = load_benchmark_policy(path)

    assert config.source == path.resolve()
    assert config.compatibility == RunCompatibilityPolicy()
    assert config.evidence == EvidencePolicy()
    assert config.regression == RegressionPolicy()
    assert config.configured_fields == frozenset()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("compatibility", object(), "RunCompatibilityPolicy"),
        ("evidence", object(), "EvidencePolicy"),
        ("regression", object(), "RegressionPolicy"),
        ("configured_fields", frozenset({""}), "non-empty strings"),
    ],
)
def test_policy_config_rejects_invalid_direct_construction(
    field: str,
    value: object,
    message: str,
) -> None:
    config = default_benchmark_policy()

    with pytest.raises((TypeError, ValueError), match=message):
        _ = replace(config, **{field: value})


def test_policy_config_normalizes_source_and_fields(tmp_path: Path) -> None:
    config = BenchmarkPolicyConfig(
        compatibility=RunCompatibilityPolicy(),
        evidence=EvidencePolicy(),
        regression=RegressionPolicy(),
        source=tmp_path / "policy.toml",
        configured_fields=cast(frozenset[str], {"regression.default_threshold_percent"}),
    )

    assert config.source == tmp_path / "policy.toml"
    assert config.configured_fields == frozenset({"regression.default_threshold_percent"})
