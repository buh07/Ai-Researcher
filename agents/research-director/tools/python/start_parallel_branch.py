"""Grant-safe entry point for :func:`start_parallel_branch`."""

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
def start_parallel_branch(branch_id: str, producer_agent_id: str, producer_session_id: str) -> dict[str, Any]:
    '\n    Create a single-use local dispatch marker before starting one child session.\n\n    Its local timestamp is operational bookkeeping only and can never establish\n    provider execution or parallel overlap.\n\n    Args:\n        branch_id: Stable identity that the later parallel-branch/v1 will carry.\n        producer_agent_id: Exact specialist agent identity to dispatch.\n        producer_session_id: Exact independent Omnigent session identity.\n    '
    return _CORE.start_parallel_branch(branch_id=branch_id, producer_agent_id=producer_agent_id, producer_session_id=producer_session_id)
