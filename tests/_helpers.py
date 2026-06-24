"""Shared helpers for tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def load_script_module(module_name: str) -> Any:
    """Load a repository script as an importable module."""
    script_path = SCRIPTS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None

    scripts_path = str(SCRIPTS_DIR)
    inserted = False
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
        inserted = True

    previous_module = sys.modules.get(module_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(cast(ModuleType, module))
    except Exception:
        if previous_module is None:
            _ = sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
        raise
    finally:
        if inserted:
            sys.path.remove(scripts_path)

    return module
