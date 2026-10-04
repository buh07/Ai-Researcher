"""Grant-safe entry point for :func:`stage_approved_experiment`."""

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
def stage_approved_experiment(objective_confirmation_digest: str, experiment_candidates_json: str, safety_review_json: str, human_approval_digest: str) -> dict[str, Any]:
    '\n    Bind exact objective and experiment approval and stage without launching.\n\n    Args:\n        objective_confirmation_digest: Exact current human objective authority.\n        experiment_candidates_json: Exact journaled experiment-candidates/v1 JSON.\n        safety_review_json: Exact journaled safety-review/v1 JSON.\n        human_approval_digest: Digest of human-approval/v1 already recorded through the operator-only path.\n    '
    return _CORE.stage_approved_experiment(objective_confirmation_digest=objective_confirmation_digest, experiment_candidates_json=experiment_candidates_json, safety_review_json=safety_review_json, human_approval_digest=human_approval_digest)
