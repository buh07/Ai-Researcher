"""Grant-safe entry point for :func:`mark_provider_execution_end`."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from omnigent_client.tools import tool

_CORE_PATH = Path(__file__).resolve().parents[1] / "execution_marker_core.py"
_SPEC = importlib.util.spec_from_file_location(
    "_ai_researcher_execution_marker_core", _CORE_PATH
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load execution marker core from {_CORE_PATH}")
_CORE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CORE)


@tool
def mark_provider_execution_end(
    branch_id: str, start_marker_id: str
) -> dict[str, str]:
    """Mark substantive work ending inside this provider child session.

    Args:
        branch_id: Exact branch identity supplied by the research director.
        start_marker_id: Marker ID returned by mark_provider_execution_start.
    """

    return _CORE.mark_provider_execution_end(
        branch_id=branch_id, start_marker_id=start_marker_id
    )
