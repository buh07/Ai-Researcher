"""Grant-safe entry point for :func:`preflight_confirmed_objective`."""

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
def preflight_confirmed_objective(objective_confirmation_digest: str, openml_task_id: int, openml_dataset_id: int, data_governance_json: str, feasibility_check_id: str, checked_by: str, checked_at: str, fallback: str, producer_agent_id: str, producer_session_id: str, live: bool=False) -> dict[str, Any]:
    "\n    Run the pinned experiment API's access/identity/license/privacy/API/compute gate.\n\n    Args:\n        objective_confirmation_digest: Exact human objective authority to check.\n        openml_task_id: Pinned OpenML task number named by the confirmed source.\n        openml_dataset_id: Pinned OpenML dataset number named by the confirmation.\n        data_governance_json: Verified license/privacy attestation for the exact dataset.\n        feasibility_check_id: Stable identity for the resulting feasibility record.\n        checked_by: Attributable operator identity.\n        checked_at: ISO-8601 timestamp for the check.\n        fallback: Named fallback requiring fresh human confirmation if used.\n        producer_agent_id: Actual tool-calling agent identity.\n        producer_session_id: Actual tool-calling Omnigent session identity.\n        live: Use pinned live OpenML access when true; otherwise use the tests-only fixture.\n    "
    return _CORE.preflight_confirmed_objective(objective_confirmation_digest=objective_confirmation_digest, openml_task_id=openml_task_id, openml_dataset_id=openml_dataset_id, data_governance_json=data_governance_json, feasibility_check_id=feasibility_check_id, checked_by=checked_by, checked_at=checked_at, fallback=fallback, producer_agent_id=producer_agent_id, producer_session_id=producer_session_id, live=live)
