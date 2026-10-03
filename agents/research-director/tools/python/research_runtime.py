"""Omnigent tools for the local research journal and execution harness."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from omnigent_client.tools import tool


def _repo_root() -> Path:
    configured = os.environ.get("AI_RESEARCHER_ROOT")
    candidates = [Path(configured)] if configured else []
    candidates.extend([Path.cwd(), *Path(__file__).resolve().parents])
    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / "src" / "ai_researcher").is_dir() and (
            root / "harness" / "orchestrator_harness"
        ).is_dir():
            return root
    raise RuntimeError(
        "AI Researcher checkout not found; set AI_RESEARCHER_ROOT to the repository root"
    )


def _adapter():
    root = _repo_root()
    for path in (root / "src", root / "harness"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from ai_researcher import HarnessAdapter

    return HarnessAdapter(root)


def _object(payload: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


@tool
def record_research_record(record_json: str, source: str) -> dict[str, Any]:
    """
    Validate and append one immutable scientific record to the local journal.

    Args:
        record_json: A JSON object matching a documented research handoff schema.
        source: Provenance label such as omnigent:evidence-researcher.
    """
    adapter = _adapter()
    record = _object(record_json, "record_json")
    return adapter.journal.append(record, source=source)


@tool
def request_experiment_approval(
    experiment_candidates_json: str,
    safety_review_json: str,
) -> dict[str, Any]:
    """
    Validate a reviewed experiment and return its exact human-approval request.

    Args:
        experiment_candidates_json: Complete experiment-candidates/v1 JSON.
        safety_review_json: Complete safety-review/v1 JSON for the selected experiment.
    """
    return _adapter().approval_request(
        _object(experiment_candidates_json, "experiment_candidates_json"),
        _object(safety_review_json, "safety_review_json"),
    )


@tool
def stage_approved_experiment(
    experiment_candidates_json: str,
    safety_review_json: str,
    human_approval_json: str,
) -> dict[str, Any]:
    """
    Bind an exact human approval and stage one harness task without launching it.

    Args:
        experiment_candidates_json: Complete experiment-candidates/v1 JSON.
        safety_review_json: Complete safety-review/v1 JSON for the selected experiment.
        human_approval_json: Human-approval/v1 JSON binding the exact experiment digest.
    """
    prepared = _adapter().prepare(
        _object(experiment_candidates_json, "experiment_candidates_json"),
        _object(safety_review_json, "safety_review_json"),
        _object(human_approval_json, "human_approval_json"),
    )
    return {
        "status": "STAGED",
        "experiment_id": prepared.experiment_id,
        "experiment_digest": prepared.experiment_digest,
        "approval_digest": prepared.approval_digest,
        "lane_id": prepared.lane_id,
        "task_card_path": str(prepared.task_card_path),
        "next_action": (
            "Ask the human to confirm the approval digest before calling "
            "launch_approved_experiment."
        ),
    }


@tool
def launch_approved_experiment(
    experiment_id: str,
    approval_digest_confirmation: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    """
    Launch an already staged experiment through the harness after exact confirmation.

    Args:
        experiment_id: The selected, staged experiment identity.
        approval_digest_confirmation: Exact digest shown after staging and reconfirmed by the human.
        provider: Harness provider identifier such as codex or claude-code.
        model: Explicit provider model identifier.
    """
    adapter = _adapter()
    binding = adapter.status(experiment_id)
    if binding is None:
        raise ValueError("experiment is not staged")
    task_path = Path(binding["task_card_path"])
    task_card = json.loads(task_path.read_text(encoding="utf-8"))
    from ai_researcher.harness_adapter import PreparedExperiment

    prepared = PreparedExperiment(
        experiment_id=binding["experiment_id"],
        experiment_digest=binding["experiment_digest"],
        approval_digest=binding["approval_digest"],
        lane_id=binding["lane_id"],
        task_card_path=task_path,
        task_card=task_card,
    )
    return adapter.launch(
        prepared,
        confirmation=approval_digest_confirmation,
        provider=provider,
        model=model,
    )


@tool
def get_experiment_status(experiment_id: str) -> dict[str, Any]:
    """
    Read the durable binding and lifecycle status for one experiment.

    Args:
        experiment_id: The selected experiment identity.
    """
    status = _adapter().status(experiment_id)
    return status or {"experiment_id": experiment_id, "status": "NOT_FOUND"}


@tool
def record_experiment_result(result_json: str) -> dict[str, Any]:
    """
    Validate and persist a harness experiment-result/v1 record.

    Args:
        result_json: Complete experiment-result/v1 JSON returned by the harness.
    """
    return _adapter().record_result(_object(result_json, "result_json"))
