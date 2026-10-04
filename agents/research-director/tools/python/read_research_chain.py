"""Grant-safe entry point for :func:`read_research_chain`."""

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
def read_research_chain(question_id: str) -> dict[str, Any]:
    '\n    Read the immutable records, links, and real producer metadata for one question.\n\n    Args:\n        question_id: Exact research-question identity; no implicit latest lookup is allowed.\n    '
    return _CORE.read_research_chain(question_id=question_id)
