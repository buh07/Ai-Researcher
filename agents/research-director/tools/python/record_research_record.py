"""Grant-safe entry point for :func:`record_research_record`."""

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
def record_research_record(record_json: str, source: str, parent_links_json: str, producer_agent_id: str, producer_session_id: str, invocation_token: str='', provider_session_id: str='') -> dict[str, Any]:
    '\n    Append one immutable record with explicit semantic and producer provenance.\n\n    Args:\n        record_json: A JSON object matching a documented research handoff schema.\n            For updated-decision/v1, omit decision timing fields; the journal\n            adds them from the accepted Harness binding and its own clock.\n        source: Provenance channel, for example omnigent:evidence-researcher.\n        parent_links_json: JSON list of parent_digest/relation objects; use [] only for a root question.\n        producer_agent_id: Actual agent or human identity that produced the record.\n        producer_session_id: Actual Omnigent session or attributable human-turn identity.\n        invocation_token: Local dispatch marker for a finished parallel branch; it cannot prove overlap.\n        provider_session_id: Omnigent child-session ID. The tool independently exports and verifies it.\n    '
    return _CORE.record_research_record(record_json=record_json, source=source, parent_links_json=parent_links_json, producer_agent_id=producer_agent_id, producer_session_id=producer_session_id, invocation_token=invocation_token, provider_session_id=provider_session_id)
