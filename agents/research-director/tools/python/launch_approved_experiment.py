"""Grant-safe entry point for :func:`launch_approved_experiment`."""

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
def launch_approved_experiment(experiment_id: str, approval_digest_confirmation: str, provider: str, model: str, provider_options_json: str) -> dict[str, Any]:
    '\n    Launch an intact staged snapshot after exact confirmation and environment gate.\n\n    Args:\n        experiment_id: The selected staged experiment identity.\n        approval_digest_confirmation: Exact displayed approval digest reconfirmed by the human.\n        provider: Harness provider identifier such as codex or claude-code.\n        model: Explicit provider model identifier.\n        provider_options_json: Explicit provider options object. Codex requires\n            reasoning_effort and service_tier; Claude Code requires effort;\n            Qwen Code requires an empty object.\n    '
    return _CORE.launch_approved_experiment(experiment_id=experiment_id, approval_digest_confirmation=approval_digest_confirmation, provider=provider, model=model, provider_options_json=provider_options_json)
