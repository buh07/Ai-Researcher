"""Grant-safe entry point for :func:`build_harness_result`."""

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
def build_harness_result(experiment_id: str, result_json: str, summary: str, evidence_json: str, completed_at: str) -> dict[str, Any]:
    'Convert an exact matched outcome into the Harness RESULT.json contract.\n\n    The launched worker must write the returned object unchanged as RESULT.json;\n    this tool does not mutate a worker worktree or bypass Harness review.\n    '
    return _CORE.build_harness_result(experiment_id=experiment_id, result_json=result_json, summary=summary, evidence_json=evidence_json, completed_at=completed_at)
