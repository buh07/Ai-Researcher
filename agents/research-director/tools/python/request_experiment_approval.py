"""Grant-safe entry point for :func:`request_experiment_approval`."""

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
def request_experiment_approval(objective_confirmation_digest: str, experiment_candidates_json: str, safety_review_json: str) -> dict[str, Any]:
    '\n    Return an exact approval request for a complete journaled authority chain.\n\n    Args:\n        objective_confirmation_digest: Exact current human objective authority.\n        experiment_candidates_json: Exact journaled experiment-candidates/v1 JSON.\n        safety_review_json: Exact journaled safety-review/v1 JSON.\n    '
    return _CORE.request_experiment_approval(objective_confirmation_digest=objective_confirmation_digest, experiment_candidates_json=experiment_candidates_json, safety_review_json=safety_review_json)
