"""Grant-safe entry point for :func:`record_experiment_result`."""

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
def record_experiment_result(result_json: str, terminal_evidence_json: str, artifact_base_dir: str) -> dict[str, Any]:
    "\n    Persist a result only when it exactly matches a launched authority snapshot.\n\n    Args:\n        result_json: Complete experiment-result/v1 JSON returned by the launched harness run.\n        terminal_evidence_json: Complete native-terminal-evidence/v1 JSON for an enhanced\n            lane, or harness-acceptance-evidence/v1 containing the ordinary lane's exact\n            review, acceptance, and reviewed result records. This is only a consistency\n            copy; the adapter rereads the Harness-owned records and requires their\n            scientific_result to equal result_json.\n        artifact_base_dir: Local directory resolving artifact: URIs; every referenced file is rehashed.\n    "
    return _CORE.record_experiment_result(result_json=result_json, terminal_evidence_json=terminal_evidence_json, artifact_base_dir=artifact_base_dir)
