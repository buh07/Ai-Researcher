"""Grant-safe entry point for :func:`retire_experiment`."""

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
def retire_experiment(experiment_id: str, approval_digest_confirmation: str) -> dict[str, Any]:
    'Retire one accepted lane using its Harness-owned acceptance reference.'
    return _CORE.retire_experiment(experiment_id=experiment_id, approval_digest_confirmation=approval_digest_confirmation)
