"""Grant-safe entry point for :func:`get_learning_receipt`."""

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
def get_learning_receipt(question_id: str, final: bool=False) -> dict[str, Any]:
    '\n    Project a deterministic learning receipt from one exact scientific chain.\n\n    Args:\n        question_id: Exact research-question identity.\n        final: Require every terminal result, decision, and acceleration record when true.\n    '
    return _CORE.get_learning_receipt(question_id=question_id, final=final)
