"""Grant-safe entry point for :func:`read_experiment_terminal_evidence`."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from omnigent_client.tools import tool

_CORE_PATH = Path(__file__).resolve().parents[1] / "research_runtime_core.py"
_SPEC = importlib.util.spec_from_file_location(
    "_ai_researcher_research_runtime_core", _CORE_PATH
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load research runtime core from {_CORE_PATH}")
_CORE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CORE)


@tool
def read_experiment_terminal_evidence(experiment_id: str) -> dict[str, Any]:
    'Read accepted evidence directly from the configured Harness runtime.'
    return _CORE.read_experiment_terminal_evidence(experiment_id=experiment_id)
