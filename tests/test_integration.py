"""Integration tests for third-party runtime and packaging behavior."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Protocol, TypeVar, cast

import pytest

from benchmatrix import (
    BenchmarkCase,
    BenchmarkConfig,
    BenchmarkHookContext,
    MetricName,
    balanced_cell_order,
    benchmark_batch_throughput,
    collect_paired_benchmark_runs,
)

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
T = TypeVar("T")


class _BenchmarkFixture(Protocol):
    """Small public surface needed from pytest-benchmark's fixture."""

    extra_info: MutableMapping[str, object]

    def __call__(self, target: Callable[..., T], *args: object, **kwargs: object) -> T:
        """Benchmark a callable."""
        ...

    def pedantic(
        self,
        target: Callable[..., T],
        *,
        args: Sequence[object] | None = None,
        kwargs: Mapping[str, object] | None = None,
        setup: Callable[[], tuple[Sequence[object], Mapping[str, object]]] | None = None,
        teardown: Callable[..., object] | None = None,
        rounds: int = 100,
        warmup_rounds: int = 10,
        iterations: int = 1,
    ) -> T:
        """Benchmark a callable in pedantic mode."""
        ...


def _run_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command and capture useful failure output."""
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def _venv_python(venv_path: Path) -> Path:
    """Return the Python executable inside a virtual environment."""
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"

    return venv_path / "bin" / "python"


def _venv_script(venv_path: Path, name: str) -> Path:
    """Return a console-script path inside a virtual environment."""
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_path / scripts_dir / f"{name}{suffix}"


def _uv() -> str:
    """Return the uv executable path, or skip when unavailable."""
    uv_path = shutil.which("uv")
    if uv_path is None:
        pytest.skip("uv is required for packaging smoke tests")

    return uv_path


def test_harness_runs_with_real_pytest_benchmark_fixture(benchmark: _BenchmarkFixture) -> None:
    case = BenchmarkCase.from_values("real", [1, 2, 3], work_units=3, work_unit_name="items", fresh_inputs=True)
    stream = io.StringIO()
    hook_events: list[str] = []

    def before(context: BenchmarkHookContext) -> None:
        assert context.case is case
        hook_events.append("before")

    def validate(context: BenchmarkHookContext, result: object) -> None:
        assert context.implementation_name == "len"
        assert result == 3
        hook_events.append("validate")

    def after(context: BenchmarkHookContext) -> None:
        assert context.metric_name == "batch_throughput"
        hook_events.append("after")

    record = benchmark_batch_throughput(
        benchmark,
        "len",
        len,
        "real",
        case,
        config=BenchmarkConfig(
            pedantic_rounds=1,
            warmup_rounds=0,
            stream_progress=True,
            before_benchmark=before,
            validate_result=validate,
            after_benchmark=after,
        ),
        stream=stream,
    )

    assert record.metric_name == "batch_throughput"
    assert record.extra_info["metric_name"] == "batch_throughput"
    assert record.extra_info["implementation_name"] == "len"
    assert record.extra_info["case_name"] == "real"
    assert record.extra_info["work_units"] == 3.0
    assert benchmark.extra_info == record.extra_info
    assert "[benchmark invoked] metric=batch_throughput implementation=len case=real" in stream.getvalue()
    assert hook_events == ["before", "validate", "after"]


def test_make_benchmark_test_is_collected_by_real_pytest(tmp_path: Path) -> None:
    benchmark_module = tmp_path / "test_generated_matrix.py"
    _ = benchmark_module.write_text(
        textwrap.dedent(
            """
            from benchmatrix import BenchmarkCase, make_benchmark_test


            def identity(value: int) -> int:
                return value


            def doubled(value: int) -> int:
                return value * 2


            test_generated_matrix = make_benchmark_test(
                {"identity": identity, "doubled": doubled},
                [
                    BenchmarkCase.from_values("small", 1),
                    BenchmarkCase.from_values("large", 100),
                ],
                metrics=("single_call_latency", "batch_throughput"),
            )
            """
        ),
        encoding="utf-8",
    )

    result = _run_command(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(benchmark_module)],
        cwd=tmp_path,
    )

    expected_ids = {
        "single_call_latency::identity::small",
        "single_call_latency::identity::large",
        "single_call_latency::doubled::small",
        "single_call_latency::doubled::large",
        "batch_throughput::identity::small",
        "batch_throughput::identity::large",
        "batch_throughput::doubled::small",
        "batch_throughput::doubled::large",
    }
    assert "8 tests collected" in result.stdout
    for parameter_id in expected_ids:
        assert f"test_generated_matrix[{parameter_id}]" in result.stdout


@pytest.mark.slow
def test_paired_collector_controls_real_pytest_benchmark_json_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark_module = tmp_path / "test_balanced_matrix.py"
    _ = benchmark_module.write_text(
        textwrap.dedent(
            """
            from benchmatrix import BenchmarkCase, BenchmarkConfig, make_benchmark_test


            def identity(value: int) -> int:
                return value


            def doubled(value: int) -> int:
                return value * 2


            test_balanced_matrix = make_benchmark_test(
                {"identity": identity, "doubled": doubled},
                [
                    BenchmarkCase.from_values("small", 1),
                    BenchmarkCase.from_values("large", 100),
                ],
                metrics=("single_call_latency",),
                config=BenchmarkConfig(pedantic_rounds=1, warmup_rounds=0),
            )
            """
        ),
        encoding="utf-8",
    )
    command = (
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "pytest_benchmark.plugin",
        "-q",
        str(benchmark_module),
    )
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    cells: tuple[tuple[str, str, MetricName], ...] = (
        ("identity", "small", "single_call_latency"),
        ("identity", "large", "single_call_latency"),
        ("doubled", "small", "single_call_latency"),
        ("doubled", "large", "single_call_latency"),
    )

    group = collect_paired_benchmark_runs(
        command,
        command,
        tmp_path / "paired-results",
        pair_count=1,
        random_seed=37,
        baseline_cwd=tmp_path,
        candidate_cwd=tmp_path,
    )

    assert group.is_complete is True
    assert len(group.complete_pairs) == 1
    for pair in group.complete_pairs:
        expected = balanced_cell_order(
            cells,
            order_index=pair.baseline_record.cell_order_index,
            random_seed=37,
        )
        baseline_order = tuple((row.implementation_name, row.case_name, row.metric_name) for row in pair.baseline.rows)
        candidate_order = tuple(
            (row.implementation_name, row.case_name, row.metric_name) for row in pair.candidate.rows
        )

        assert expected != cells
        assert pair.cell_order == expected
        assert baseline_order == candidate_order == expected
        for record in (pair.baseline_record, pair.candidate_record):
            payload = cast(dict[str, object], json.loads(record.path.read_text(encoding="utf-8")))
            entries = cast(list[dict[str, object]], payload["benchmarks"])
            json_order = tuple(
                (
                    cast(str, extra_info["implementation_name"]),
                    cast(str, extra_info["case_name"]),
                    cast(MetricName, extra_info["metric_name"]),
                )
                for entry in entries
                if (extra_info := cast(dict[str, object], entry["extra_info"]))
            )
            assert json_order == expected


@pytest.mark.slow
def test_built_wheel_can_be_imported_from_clean_virtualenv(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    venv_dir = tmp_path / "venv"
    uv = _uv()

    _ = _run_command(
        [uv, "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=_PROJECT_ROOT,
    )
    wheels = sorted(dist_dir.glob("benchmatrix-*.whl"))
    assert len(wheels) == 1

    _ = _run_command([uv, "venv", "--quiet", str(venv_dir)], cwd=_PROJECT_ROOT)
    python = _venv_python(venv_dir)
    _ = _run_command(
        [uv, "pip", "install", "--quiet", "--python", str(python), "--no-deps", str(wheels[0])], cwd=_PROJECT_ROOT
    )
    import_script = (
        "import benchmatrix; "
        + "print(benchmatrix.__version__); "
        + "print(benchmatrix.BenchmarkCase('case').name); "
        + "print('pytest' in __import__('sys').modules)"
    )
    result = _run_command(
        [
            str(python),
            "-c",
            import_script,
        ],
        cwd=_PROJECT_ROOT,
    )

    package_version, case_name, pytest_imported = result.stdout.strip().splitlines()
    assert case_name == "case"
    assert pytest_imported == "False"

    cli_result = _run_command(
        [str(_venv_script(venv_dir, "benchmatrix")), "--help"],
        cwd=_PROJECT_ROOT,
    )
    assert "Measure repeatable Python benchmark matrices and detect regressions." in cli_result.stdout

    version_result = _run_command(
        [str(_venv_script(venv_dir, "benchmatrix")), "--version"],
        cwd=_PROJECT_ROOT,
    )
    assert version_result.stdout.strip() == f"benchmatrix {package_version}"
