"""Grant-safe entry point for :func:`ingest_harness_experiment_result`."""

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
def ingest_harness_experiment_result(experiment_id: str, artifact_base_dir: str) -> dict[str, Any]:
    'Ingest only the exact ``scientific_result`` accepted by Harness ROOT.'
    return _CORE.ingest_harness_experiment_result(experiment_id=experiment_id, artifact_base_dir=artifact_base_dir)
