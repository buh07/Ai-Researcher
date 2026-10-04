"""Grant-safe entry point for :func:`review_experiment_completion`."""

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
def review_experiment_completion(experiment_id: str, approval_digest_confirmation: str, review_outcome: str, approval: str, review_summary: str, evidence_json: str) -> dict[str, Any]:
    'Record a separate, explicit ROOT review/acceptance decision.\n\n    This never auto-accepts. Scientific acceptance requires a PASS review;\n    FAIL and BLOCKED can only be rejected, while UNKNOWN must be reviewed again.\n    '
    return _CORE.review_experiment_completion(experiment_id=experiment_id, approval_digest_confirmation=approval_digest_confirmation, review_outcome=review_outcome, approval=approval, review_summary=review_summary, evidence_json=evidence_json)
