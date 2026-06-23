"""Integration tests for third-party runtime and packaging behavior."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Protocol, TypeVar

import pytest

from benchmatrix import BenchmarkCase, BenchmarkConfig, benchmark_batch_throughput

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


def _uv() -> str:
    """Return the uv executable path, or skip when unavailable."""
    uv_path = shutil.which("uv")
    if uv_path is None:
        pytest.skip("uv is required for packaging smoke tests")

    return uv_path


def test_harness_runs_with_real_pytest_benchmark_fixture(benchmark: _BenchmarkFixture) -> None:
    case = BenchmarkCase.from_values("real", [1, 2, 3], work_units=3, work_unit_name="items", fresh_inputs=True)
    stream = io.StringIO()

    record = benchmark_batch_throughput(
        benchmark,
        "len",
        len,
        "real",
        case,
        config=BenchmarkConfig(pedantic_rounds=1, warmup_rounds=0, stream_progress=True),
        stream=stream,
    )

    assert record.metric_name == "batch_throughput"
    assert record.extra_info["metric_name"] == "batch_throughput"
    assert record.extra_info["implementation_name"] == "len"
    assert record.extra_info["case_name"] == "real"
    assert record.extra_info["work_units"] == 3.0
    assert benchmark.extra_info == record.extra_info
    assert "[benchmark invoked] metric=batch_throughput implementation=len case=real" in stream.getvalue()


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

    _, case_name, pytest_imported = result.stdout.strip().splitlines()
    assert case_name == "case"
    assert pytest_imported == "False"
