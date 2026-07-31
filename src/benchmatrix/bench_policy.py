"""Load version-controlled benchmark policies from TOML configuration."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ._schema import MetricName
from .bench_compare import CompatibilityMode, EvidencePolicy, RegressionPolicy, RunCompatibilityPolicy
from .exceptions import BenchmarkPolicyError

_TOOL_KEYS = frozenset({"compatibility", "evidence", "regression"})
_COMPATIBILITY_KEYS = frozenset({"mode"})
_EVIDENCE_KEYS = frozenset(
    {
        "minimum_runs",
        "minimum_samples_per_run",
        "require_rounds",
        "require_iterations",
        "maximum_cv",
        "maximum_outlier_fraction",
    }
)
_REGRESSION_KEYS = frozenset(
    {
        "default_threshold_percent",
        "by_metric",
        "by_implementation",
        "by_case",
        "by_cell",
    }
)
_CELL_KEYS = frozenset({"implementation", "case", "metric", "threshold_percent"})


@dataclass(frozen=True, slots=True)
class BenchmarkPolicyConfig:
    """Resolved benchmatrix policy configuration.

    Attributes:
        compatibility: Run-environment compatibility policy.
        evidence: Repeated-run evidence policy.
        regression: Regression threshold policy.
        source: Selected TOML file, or ``None`` when using built-in defaults.
        configured_fields: Explicit ``tool.benchmatrix`` field paths.
    """

    compatibility: RunCompatibilityPolicy
    evidence: EvidencePolicy
    regression: RegressionPolicy
    source: Path | None = None
    configured_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Normalize the optional source path and configured field set."""
        if not isinstance(self.compatibility, RunCompatibilityPolicy):
            raise TypeError("BenchmarkPolicyConfig.compatibility must be a RunCompatibilityPolicy.")
        if not isinstance(self.evidence, EvidencePolicy):
            raise TypeError("BenchmarkPolicyConfig.evidence must be an EvidencePolicy.")
        if not isinstance(self.regression, RegressionPolicy):
            raise TypeError("BenchmarkPolicyConfig.regression must be a RegressionPolicy.")
        fields = frozenset(self.configured_fields)
        if any(not isinstance(field, str) or not field for field in fields):
            raise ValueError("BenchmarkPolicyConfig.configured_fields must contain non-empty strings.")
        if self.source is not None:
            object.__setattr__(self, "source", Path(self.source))
        object.__setattr__(self, "configured_fields", fields)

    @property
    def is_configured(self) -> bool:
        """Return whether a ``tool.benchmatrix`` table was loaded."""
        return self.source is not None


def default_benchmark_policy() -> BenchmarkPolicyConfig:
    """Return benchmatrix's built-in comparison policies."""
    return BenchmarkPolicyConfig(
        compatibility=RunCompatibilityPolicy(),
        evidence=EvidencePolicy(),
        regression=RegressionPolicy(),
    )


def load_benchmark_policy(
    path: str | Path | None = None,
    *,
    search_from: str | Path | None = None,
) -> BenchmarkPolicyConfig:
    """Load ``tool.benchmatrix`` policy from TOML.

    With an explicit ``path``, the file must contain ``[tool.benchmatrix]``.
    Otherwise the nearest ``pyproject.toml`` at or above ``search_from`` is
    inspected. Discovery stops at the first pyproject; a project without a
    benchmatrix table uses built-in defaults.

    Args:
        path: Explicit TOML or pyproject path.
        search_from: File or directory from which to discover pyproject.toml.
            Defaults to the current working directory.

    Returns:
        Validated compatibility, evidence, and regression policies.

    Raises:
        BenchmarkPolicyError: If an explicit file is missing, TOML is invalid,
            or the benchmatrix configuration does not satisfy its schema.
    """
    explicit = path is not None
    source = Path(path) if explicit else _discover_pyproject(search_from)
    if source is None:
        return default_benchmark_policy()
    source = source.resolve()

    try:
        with source.open("rb") as stream:
            payload = cast(object, tomllib.load(stream))
    except OSError as exc:
        raise BenchmarkPolicyError(f"Could not read benchmark policy configuration: {source}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise BenchmarkPolicyError(f"Invalid TOML in benchmark policy configuration: {source}") from exc

    root = _mapping(payload, path="root")
    tool = root.get("tool")
    if tool is None:
        if explicit:
            raise BenchmarkPolicyError(f"Configuration does not contain [tool.benchmatrix]: {source}")
        return default_benchmark_policy()
    tool_mapping = _mapping(tool, path="tool")
    raw_config = tool_mapping.get("benchmatrix")
    if raw_config is None:
        if explicit:
            raise BenchmarkPolicyError(f"Configuration does not contain [tool.benchmatrix]: {source}")
        return default_benchmark_policy()

    config = _mapping(raw_config, path="tool.benchmatrix")
    _exact_keys(config, _TOOL_KEYS, path="tool.benchmatrix")
    try:
        compatibility, compatibility_fields = _parse_compatibility(config.get("compatibility"))
        evidence, evidence_fields = _parse_evidence(config.get("evidence"))
        regression, regression_fields = _parse_regression(config.get("regression"))
        return BenchmarkPolicyConfig(
            compatibility=compatibility,
            evidence=evidence,
            regression=regression,
            source=source,
            configured_fields=frozenset((*compatibility_fields, *evidence_fields, *regression_fields)),
        )
    except BenchmarkPolicyError:
        raise
    except (TypeError, ValueError) as exc:
        raise BenchmarkPolicyError(f"Invalid benchmark policy in {source}: {exc}") from exc


def _discover_pyproject(search_from: str | Path | None) -> Path | None:
    """Return the nearest pyproject.toml from a search location."""
    location = Path.cwd() if search_from is None else Path(search_from)
    directory = location.parent if location.is_file() else location
    directory = directory.resolve()
    for candidate_directory in (directory, *directory.parents):
        candidate = candidate_directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _parse_compatibility(
    value: object | None,
) -> tuple[RunCompatibilityPolicy, tuple[str, ...]]:
    """Parse the compatibility policy table."""
    if value is None:
        return RunCompatibilityPolicy(), ()
    section = _mapping(value, path="tool.benchmatrix.compatibility")
    _exact_keys(section, _COMPATIBILITY_KEYS, path="tool.benchmatrix.compatibility")
    fields = tuple(f"compatibility.{key}" for key in section)
    mode = cast(CompatibilityMode, section.get("mode", "permissive"))
    return RunCompatibilityPolicy(mode=mode), fields


def _parse_evidence(value: object | None) -> tuple[EvidencePolicy, tuple[str, ...]]:
    """Parse the evidence policy table."""
    if value is None:
        return EvidencePolicy(), ()
    section = _mapping(value, path="tool.benchmatrix.evidence")
    _exact_keys(section, _EVIDENCE_KEYS, path="tool.benchmatrix.evidence")
    fields = tuple(f"evidence.{key}" for key in section)
    defaults = EvidencePolicy()
    return (
        EvidencePolicy(
            minimum_runs=cast(int, section.get("minimum_runs", defaults.minimum_runs)),
            minimum_samples_per_run=cast(
                int,
                section.get("minimum_samples_per_run", defaults.minimum_samples_per_run),
            ),
            require_rounds=cast(bool, section.get("require_rounds", defaults.require_rounds)),
            require_iterations=cast(
                bool,
                section.get("require_iterations", defaults.require_iterations),
            ),
            maximum_cv=cast(float | None, section.get("maximum_cv", defaults.maximum_cv)),
            maximum_outlier_fraction=cast(
                float | None,
                section.get(
                    "maximum_outlier_fraction",
                    defaults.maximum_outlier_fraction,
                ),
            ),
        ),
        fields,
    )


def _parse_regression(
    value: object | None,
) -> tuple[RegressionPolicy, tuple[str, ...]]:
    """Parse the regression policy table."""
    if value is None:
        return RegressionPolicy(), ()
    section = _mapping(value, path="tool.benchmatrix.regression")
    _exact_keys(section, _REGRESSION_KEYS, path="tool.benchmatrix.regression")
    fields: list[str] = []
    default_threshold = section.get("default_threshold_percent", 5.0)
    if "default_threshold_percent" in section:
        fields.append("regression.default_threshold_percent")

    by_metric: Mapping[MetricName, float] = {}
    by_implementation: Mapping[str, float] = {}
    by_case: Mapping[str, float] = {}
    for key in ("by_metric", "by_implementation", "by_case"):
        if key not in section:
            continue
        selector_mapping = _mapping(section[key], path=f"tool.benchmatrix.regression.{key}")
        fields.extend(f"regression.{key}.{selector}" for selector in selector_mapping)
        if key == "by_metric":
            by_metric = cast(Mapping[MetricName, float], selector_mapping)
        elif key == "by_implementation":
            by_implementation = cast(Mapping[str, float], selector_mapping)
        else:
            by_case = cast(Mapping[str, float], selector_mapping)

    by_cell: Mapping[tuple[str, str, MetricName], float] = {}
    if "by_cell" in section:
        parsed_cells, cell_fields = _parse_cells(section["by_cell"])
        by_cell = cast(Mapping[tuple[str, str, MetricName], float], parsed_cells)
        fields.extend(cell_fields)

    return (
        RegressionPolicy(
            default_threshold_percent=cast(float, default_threshold),
            by_metric=by_metric,
            by_implementation=by_implementation,
            by_case=by_case,
            by_cell=by_cell,
        ),
        tuple(fields),
    )


def _parse_cells(value: object) -> tuple[dict[tuple[str, str, MetricName], object], tuple[str, ...]]:
    """Parse exact-cell threshold array entries."""
    if not isinstance(value, list):
        raise BenchmarkPolicyError("Expected array at tool.benchmatrix.regression.by_cell.")
    cells: dict[tuple[str, str, MetricName], object] = {}
    fields: list[str] = []
    for index, raw_cell in enumerate(value):
        path = f"tool.benchmatrix.regression.by_cell[{index}]"
        cell = _mapping(raw_cell, path=path)
        _exact_keys(cell, _CELL_KEYS, path=path)
        missing = sorted(_CELL_KEYS - set(cell))
        if missing:
            raise BenchmarkPolicyError(f"Missing key(s) at {path}: {', '.join(missing)}.")
        implementation = _non_empty_string(cell["implementation"], path=f"{path}.implementation")
        case = _non_empty_string(cell["case"], path=f"{path}.case")
        metric = _non_empty_string(cell["metric"], path=f"{path}.metric")
        key = (implementation, case, cast(MetricName, metric))
        if key in cells:
            raise BenchmarkPolicyError(f"Duplicate exact-cell policy at {path}: {key!r}.")
        cells[key] = cell["threshold_percent"]
        fields.append(f"regression.by_cell.{implementation}.{case}.{metric}")
    return cells, tuple(fields)


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    """Return a string-keyed mapping or raise a policy error."""
    if not isinstance(value, Mapping):
        raise BenchmarkPolicyError(f"Expected table at {path}, got {type(value).__name__}.")
    if any(not isinstance(key, str) for key in value):
        raise BenchmarkPolicyError(f"Expected string keys at {path}.")
    return cast(Mapping[str, object], value)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], *, path: str) -> None:
    """Reject unknown policy keys."""
    unknown = sorted(set(value) - expected)
    if unknown:
        raise BenchmarkPolicyError(f"Unknown key(s) at {path}: {', '.join(unknown)}.")


def _non_empty_string(value: object, *, path: str) -> str:
    """Return a non-empty string or raise a policy error."""
    if not isinstance(value, str) or not value:
        raise BenchmarkPolicyError(f"Expected non-empty string at {path}.")
    return value
