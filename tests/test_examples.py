"""Tests that shipped examples remain collectable."""

from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "example_module",
    [
        pytest.param("test_factorial_benchmarks.py", id="explicit"),
        pytest.param("test_factorial_benchmarks_simplified.py", id="generated"),
    ],
)
def test_factorial_examples_collect_expected_matrix(example_module: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-cov",
            str(_PROJECT_ROOT / "examples" / example_module),
        ],
        cwd=_PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "12 tests collected" in result.stdout
    for metric_name, implementation_name, case_name in itertools.product(
        ("single_call_latency", "batch_throughput", "tail_latency"),
        ("iterative", "recursive"),
        ("small", "medium"),
    ):
        node_id = (
            f"examples/{example_module}::test_factorial_benchmark_matrix"
            f"[{metric_name}::{implementation_name}::{case_name}]"
        )
        assert node_id in result.stdout
