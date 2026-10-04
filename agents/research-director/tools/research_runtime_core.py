"""Omnigent tools for the authoritative research journal and execution harness."""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
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


def _ensure_agent_record_allowed(record: dict[str, Any]) -> None:
    schema = record.get("schema")
    if schema in {"objective-confirmation/v1", "human-approval/v1"}:
        raise ValueError(
            "human authority records require scripts/record_human_authority.py; "
            "agents cannot create them"
        )
    if schema == "experiment-result/v1":
        raise ValueError(
            "experiment-result/v1 must use record_experiment_result so the launched "
            "binding and exact execution snapshot are enforced"
        )


def _links(payload: str) -> tuple[tuple[str, str], ...]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("parent_links_json must be valid JSON") from exc
    if not isinstance(value, list):
        raise ValueError("parent_links_json must be a JSON list")
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each parent link must be an object")
        parent = item.get("parent_digest")
        relation = item.get("relation")
        if not isinstance(parent, str) or not isinstance(relation, str):
            raise ValueError("each parent link requires parent_digest and relation strings")
        result.append((parent, relation))
    return tuple(result)


def _branch_event_path(token: str) -> Path:
    if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) is None:
        raise ValueError("invalid branch invocation token")
    directory = _repo_root() / "runtime" / "branch-invocations"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{token}.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _start_branch_event(
    branch_id: str, producer_agent_id: str, producer_session_id: str
) -> dict[str, Any]:
    if not all(
        isinstance(value, str) and value.strip()
        for value in (branch_id, producer_agent_id, producer_session_id)
    ):
        raise ValueError("branch and producer identities must be non-empty")
    token = secrets.token_urlsafe(32)
    invocation_id = "branch-invocation:" + hashlib.sha256(token.encode("utf-8")).hexdigest()
    payload = {
        "invocation_id": invocation_id,
        "invocation_status": "RUNNING",
        "branch_id": branch_id,
        "producer_agent_id": producer_agent_id,
        "producer_session_id": producer_session_id,
        "invocation_started_at": _utc_now(),
        "invocation_completed_at": None,
        "consumed": False,
    }
    path = _branch_event_path(token)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
    return {"invocation_token": token, **payload}


def _finish_branch_event(token: str) -> dict[str, Any]:
    path = _branch_event_path(token)
    if not path.is_file():
        raise ValueError("unknown branch invocation token")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("invocation_completed_at") is not None or payload.get("consumed"):
        raise ValueError("branch invocation is already finished")
    payload["invocation_completed_at"] = _utc_now()
    payload["invocation_status"] = "COMPLETED"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return {"invocation_token": token, **payload}


def _consume_branch_event(
    token: str, record: dict[str, Any], producer_agent_id: str, producer_session_id: str
) -> tuple[dict[str, Any], str, str]:
    path = _branch_event_path(token)
    if not path.is_file():
        raise ValueError("unknown branch invocation token")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("consumed") or not payload.get("invocation_completed_at"):
        raise ValueError("branch invocation must be finished exactly once before recording")
    expected = {
        "branch_id": record.get("branch_id"),
        "producer_agent_id": producer_agent_id,
        "producer_session_id": producer_session_id,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("branch invocation token does not match record producer identity")
    normalized = dict(record)
    normalized.update(
        {
            "invocation_id": payload["invocation_id"],
            "invocation_status": payload["invocation_status"],
            "producer_agent_id": producer_agent_id,
            "producer_session_id": producer_session_id,
            "started_at": payload["invocation_started_at"],
            "completed_at": payload["invocation_completed_at"],
        }
    )
    return normalized, payload["invocation_started_at"], payload["invocation_completed_at"]


def _mark_branch_event_consumed(token: str) -> None:
    path = _branch_event_path(token)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("consumed"):
        raise ValueError("branch invocation was already consumed")
    payload["consumed"] = True
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _export_omnigent_session(provider_session_id: str) -> bytes:
    """Fetch one session through Omnigent's controlled export command.

    No caller-selected path or payload crosses this boundary. The temporary
    export is created below the application runtime directory and deleted after
    verification.
    """

    if not isinstance(provider_session_id, str) or not provider_session_id.strip():
        raise ValueError("provider_session_id must be non-empty")
    executable = shutil.which("omnigent")
    if executable is None:
        raise RuntimeError("omnigent executable is unavailable for session attestation")
    runtime = _repo_root() / "runtime" / "provider-session-exports"
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime) as directory:
        export_path = Path(directory) / "session.jsonl"
        command = [
            executable,
            "session",
            "export",
            "--id",
            provider_session_id,
            "--output",
            str(export_path),
        ]
        server = os.environ.get("AI_RESEARCHER_OMNIGENT_SERVER")
        if server:
            command.extend(("--server", server))
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0 or not export_path.is_file():
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Omnigent session export failed: {detail}")
        return export_path.read_bytes()


def _verified_provider_invocation(
    *, branch_id: str, provider_session_id: str, producer_agent_id: str
):
    root = _repo_root()
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    from ai_researcher.journal import _verify_omnigent_session_export

    return _verify_omnigent_session_export(
        _export_omnigent_session(provider_session_id),
        expected_branch_id=branch_id,
        expected_session_id=provider_session_id,
        expected_agent_id=producer_agent_id,
    )


@tool
def start_parallel_branch(
    branch_id: str, producer_agent_id: str, producer_session_id: str
) -> dict[str, Any]:
    """
    Create a single-use local dispatch marker before starting one child session.

    Its local timestamp is operational bookkeeping only and can never establish
    provider execution or parallel overlap.

    Args:
        branch_id: Stable identity that the later parallel-branch/v1 will carry.
        producer_agent_id: Omnigent specialist agent name. This must be
            ``evidence-researcher``; do not pass the shared durable agent ID.
        producer_session_id: Exact independent Omnigent session identity.
    """

    if producer_agent_id != "evidence-researcher":
        raise ValueError(
            "producer_agent_id must be the Omnigent agent name "
            "'evidence-researcher', not a durable agent ID"
        )
    return _start_branch_event(branch_id, producer_agent_id, producer_session_id)


@tool
def finish_parallel_branch(invocation_token: str) -> dict[str, Any]:
    """
    Close a local dispatch marker after the independent response arrives.

    Its local timestamp is not scientific timing evidence. Only verified
    in-session provider execution-marker tool results can establish overlap.

    Args:
        invocation_token: Opaque token returned by start_parallel_branch.
    """

    return _finish_branch_event(invocation_token)


@tool
def record_research_record(
    record_json: str,
    source: str,
    parent_links_json: str,
    producer_agent_id: str,
    producer_session_id: str,
    invocation_token: str = "",
    provider_session_id: str = "",
) -> dict[str, Any]:
    """
    Append one immutable record with explicit semantic and producer provenance.

    Args:
        record_json: A JSON object matching a documented research handoff schema.
            For updated-decision/v1, omit decision timing fields; the journal
            adds them from the accepted Harness binding and its own clock.
        source: Provenance channel, for example omnigent:evidence-researcher.
        parent_links_json: JSON list of parent_digest/relation objects; use [] only for a root question.
        producer_agent_id: Actual agent or human identity that produced the record.
        producer_session_id: Actual Omnigent session or attributable human-turn identity.
        invocation_token: Local dispatch marker for a finished parallel branch; it cannot prove overlap.
        provider_session_id: Omnigent child-session ID. The tool independently exports and verifies it.
    """
    adapter = _adapter()
    record = _object(record_json, "record_json")
    _ensure_agent_record_allowed(record)
    kwargs: dict[str, Any] = {
        "source": source,
        "links": _links(parent_links_json),
        "producer_agent_id": producer_agent_id,
        "producer_session_id": producer_session_id,
    }
    if record.get("schema") == "parallel-branch/v1":
        if not invocation_token:
            raise ValueError("parallel branch requires a local dispatch marker")
        if not provider_session_id:
            raise ValueError(
                "parallel branch requires an independently exported Omnigent provider session"
            )
        record, _local_started, _local_completed = _consume_branch_event(
            invocation_token, record, producer_agent_id, producer_session_id
        )
        provider = _verified_provider_invocation(
            branch_id=str(record["branch_id"]),
            provider_session_id=provider_session_id,
            producer_agent_id=producer_agent_id,
        )
        receipt = provider.payload
        record.update(
            {
                "producer_agent_id": receipt["agent_id"],
                "producer_session_id": receipt["provider_session_id"],
                "invocation_id": receipt["provider_session_id"],
                "invocation_status": receipt["status"],
                "provider_session_id": receipt["provider_session_id"],
                "provider_receipt_digest": receipt["receipt_digest"],
                "started_at": receipt["started_at"],
                "completed_at": receipt["completed_at"],
            }
        )
        kwargs.update(
            producer_agent_id=receipt["agent_id"],
            producer_session_id=receipt["provider_session_id"],
            invocation_id=receipt["provider_session_id"],
            invocation_status=receipt["status"],
            provider_invocation=provider,
            invocation_started_at=receipt["started_at"],
            invocation_completed_at=receipt["completed_at"],
        )
    elif invocation_token or provider_session_id:
        raise ValueError(
            "invocation_token and provider_session_id are valid only for parallel-branch/v1"
        )
    stored = adapter.journal.append(record, **kwargs)
    if invocation_token:
        _mark_branch_event_consumed(invocation_token)
    return stored


@tool
def read_research_chain(question_id: str) -> dict[str, Any]:
    """
    Read the immutable records, links, and real producer metadata for one question.

    Args:
        question_id: Exact research-question identity; no implicit latest lookup is allowed.
    """
    return _adapter().journal.reconstruct_chain(question_id)


@tool
def get_learning_receipt(question_id: str, final: bool = False) -> dict[str, Any]:
    """
    Project a deterministic learning receipt from one exact scientific chain.

    Args:
        question_id: Exact research-question identity.
        final: Require every terminal result, decision, and acceleration record when true.
    """
    return _adapter().journal.learning_receipt(question_id, final=final)


@tool
def preflight_confirmed_objective(
    objective_confirmation_digest: str,
    openml_task_id: int,
    openml_dataset_id: int,
    data_governance_json: str,
    feasibility_check_id: str,
    checked_by: str,
    checked_at: str,
    fallback: str,
    producer_agent_id: str,
    producer_session_id: str,
    live: bool = False,
) -> dict[str, Any]:
    """
    Run the pinned experiment API's access/identity/license/privacy/API/compute gate.

    Args:
        objective_confirmation_digest: Exact human objective authority to check.
        openml_task_id: Pinned OpenML task number named by the confirmed source.
        openml_dataset_id: Pinned OpenML dataset number named by the confirmation.
        data_governance_json: Verified license/privacy attestation for the exact dataset.
        feasibility_check_id: Stable identity for the resulting feasibility record.
        checked_by: Attributable operator identity.
        checked_at: ISO-8601 timestamp for the check.
        fallback: Named fallback requiring fresh human confirmation if used.
        producer_agent_id: Actual tool-calling agent identity.
        producer_session_id: Actual tool-calling Omnigent session identity.
        live: Use pinned live OpenML access when true; otherwise use the tests-only fixture.
    """
    adapter = _adapter()
    objective = adapter.journal.get(objective_confirmation_digest)
    if objective is None or objective.get("schema") != "objective-confirmation/v1":
        raise ValueError("objective_confirmation_digest is not a journaled objective")
    question = adapter.journal.get(objective["question_digest"])
    if question is None:
        raise ValueError("objective's research question is unavailable")

    from ai_researcher.experiment import HumanObjective, preflight

    human_objective = HumanObjective(
        objective=question["question"],
        primary_metric=objective["primary_metric"],
        openml_task_id=openml_task_id,
        dataset_identifier=objective["dataset"]["identifier"],
        openml_dataset_id=openml_dataset_id,
        openml_dataset_version=int(objective["dataset"]["version"]),
        dataset_digest=objective["dataset"]["digest"],
        risk_tolerance=objective["risk_tolerance"]["level"],
        execution_scope=objective["execution_scope"],
        data_governance=_object(data_governance_json, "data_governance_json"),
        confirmed_by=objective["confirmed_by"],
        confirmed_at=objective["confirmed_at"],
        objective_confirmation_digest=objective_confirmation_digest,
    )
    # Live preflight is read-only and non-consequential. The experiment API
    # verifies the objective against this journal, but does not require an
    # experiment approval or launched binding merely to check availability.
    preflight_kwargs: dict[str, Any] = {
        "live": live,
        "journal_path": adapter.journal.path,
    }
    report = preflight(human_objective, **preflight_kwargs)
    expected_dataset = objective["dataset"]
    if report.dataset["sha256"] != expected_dataset["digest"]:
        raise ValueError("preflight dataset digest differs from the confirmed dataset")
    record = report.as_feasibility_check(
        feasibility_check_id=feasibility_check_id,
        question_id=objective["question_id"],
        checked_by=checked_by,
        checked_at=checked_at,
        fallback=fallback,
        journal_path=adapter.journal.path,
    )
    return adapter.journal.append(
        record,
        source="operator:preflight",
        links=((objective_confirmation_digest, "checks-feasibility"),),
        producer_agent_id=producer_agent_id,
        producer_session_id=producer_session_id,
    )


@tool
def request_experiment_approval(
    objective_confirmation_digest: str,
    experiment_candidates_json: str,
    safety_review_json: str,
) -> dict[str, Any]:
    """
    Return an exact approval request for a complete journaled authority chain.

    Args:
        objective_confirmation_digest: Exact current human objective authority.
        experiment_candidates_json: Exact journaled experiment-candidates/v1 JSON.
        safety_review_json: Exact journaled safety-review/v1 JSON.
    """
    return _adapter().approval_request(
        _object(experiment_candidates_json, "experiment_candidates_json"),
        _object(safety_review_json, "safety_review_json"),
        objective_confirmation_digest=objective_confirmation_digest,
    )


@tool
def stage_approved_experiment(
    objective_confirmation_digest: str,
    experiment_candidates_json: str,
    safety_review_json: str,
    human_approval_digest: str,
) -> dict[str, Any]:
    """
    Bind exact objective and experiment approval and stage without launching.

    Args:
        objective_confirmation_digest: Exact current human objective authority.
        experiment_candidates_json: Exact journaled experiment-candidates/v1 JSON.
        safety_review_json: Exact journaled safety-review/v1 JSON.
        human_approval_digest: Digest of human-approval/v1 already recorded through the operator-only path.
    """
    prepared = _adapter().prepare(
        _object(experiment_candidates_json, "experiment_candidates_json"),
        _object(safety_review_json, "safety_review_json"),
        objective_confirmation_digest=objective_confirmation_digest,
        approval_digest=human_approval_digest,
    )
    return {
        "status": "STAGED",
        "experiment_id": prepared.experiment_id,
        "objective_confirmation_digest": prepared.objective_confirmation_digest,
        "experiment_digest": prepared.experiment_digest,
        "approval_digest": prepared.approval_digest,
        "task_card_digest": prepared.task_card_digest,
        "lane_id": prepared.lane_id,
        "task_card_path": str(prepared.task_card_path),
        "next_action": "Ask the human to confirm the exact approval digest before launch.",
    }


@tool
def launch_approved_experiment(
    experiment_id: str,
    approval_digest_confirmation: str,
    provider: str,
    model: str,
    provider_options_json: str,
) -> dict[str, Any]:
    """
    Launch an intact staged snapshot after exact confirmation and environment gate.

    Args:
        experiment_id: The selected staged experiment identity.
        approval_digest_confirmation: Exact displayed approval digest reconfirmed by the human.
        provider: Harness provider identifier such as codex or claude-code.
        model: Explicit provider model identifier.
        provider_options_json: Explicit provider options object. Codex requires
            reasoning_effort and service_tier; Claude Code requires effort;
            Qwen Code requires an empty object.
    """
    adapter = _adapter()
    binding = adapter.status(experiment_id)
    if binding is None or binding["status"] != "STAGED":
        raise ValueError("experiment is not staged")
    task_path = Path(binding["task_card_path"])
    task_card = json.loads(task_path.read_text(encoding="utf-8"))
    from ai_researcher.harness_adapter import PreparedExperiment

    prepared = PreparedExperiment(
        experiment_id=binding["experiment_id"],
        objective_confirmation_digest=binding["objective_confirmation_digest"],
        experiment_digest=binding["experiment_digest"],
        approval_digest=binding["approval_digest"],
        task_card_digest=binding["task_card_digest"],
        lane_id=binding["lane_id"],
        task_card_path=task_path,
        task_card=task_card,
    )
    return adapter.launch(
        prepared,
        confirmation=approval_digest_confirmation,
        provider=provider,
        model=model,
        provider_options=_object(provider_options_json, "provider_options_json"),
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
def get_harness_experiment_status(experiment_id: str) -> dict[str, Any]:
    """Read the authoritative Harness lane and immutable research binding."""

    return _adapter().harness_status(experiment_id)


@tool
def wait_for_experiment(experiment_id: str, timeout: str) -> dict[str, Any]:
    """Wait read-only for the exact launched lane's review boundary."""

    return _adapter().wait_for_review(experiment_id, timeout=timeout)


@tool
def review_experiment_completion(
    experiment_id: str,
    approval_digest_confirmation: str,
    review_outcome: str,
    approval: str,
    review_summary: str,
    evidence_json: str,
) -> dict[str, Any]:
    """Record a separate, explicit ROOT review/acceptance decision.

    This never auto-accepts. Scientific acceptance requires a PASS review;
    FAIL and BLOCKED can only be rejected, while UNKNOWN must be reviewed again.
    """

    raw = json.loads(evidence_json)
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("evidence_json must be a JSON list of strings")
    return _adapter().review_completion(
        experiment_id,
        confirmation=approval_digest_confirmation,
        review_outcome=review_outcome,
        approval=approval,
        review_summary=review_summary,
        evidence=tuple(raw),
    )


@tool
def read_experiment_terminal_evidence(experiment_id: str) -> dict[str, Any]:
    """Read accepted evidence directly from the configured Harness runtime."""

    return _adapter().terminal_evidence(experiment_id)


@tool
def build_harness_result(
    experiment_id: str,
    result_json: str,
    summary: str,
    evidence_json: str,
    completed_at: str,
) -> dict[str, Any]:
    """Convert an exact matched outcome into the Harness RESULT.json contract.

    The launched worker must write the returned object unchanged as RESULT.json;
    this tool does not mutate a worker worktree or bypass Harness review.
    """

    raw_evidence = json.loads(evidence_json)
    if not isinstance(raw_evidence, list) or any(
        not isinstance(item, str) for item in raw_evidence
    ):
        raise ValueError("evidence_json must be a JSON list of strings")
    return _adapter().build_result_envelope(
        experiment_id,
        _object(result_json, "result_json"),
        summary=summary,
        evidence=tuple(raw_evidence),
        completed_at=completed_at,
    )


@tool
def ingest_harness_experiment_result(
    experiment_id: str, artifact_base_dir: str
) -> dict[str, Any]:
    """Ingest only the exact ``scientific_result`` accepted by Harness ROOT."""

    return _adapter().ingest_harness_result(
        experiment_id, artifact_base_dir=artifact_base_dir
    )


@tool
def force_stop_experiment(
    experiment_id: str, approval_digest_confirmation: str
) -> dict[str, Any]:
    """Hard-stop one exact stuck run after explicit digest confirmation."""

    return _adapter().force_stop(
        experiment_id, confirmation=approval_digest_confirmation
    )


@tool
def read_experiment_cancellation_evidence(experiment_id: str) -> dict[str, Any]:
    """Reread the hash-bound cleanup receipt for one force-stopped exact run."""

    return _adapter().cancellation_evidence(experiment_id)


@tool
def retire_experiment(
    experiment_id: str, approval_digest_confirmation: str
) -> dict[str, Any]:
    """Retire one accepted lane using its Harness-owned acceptance reference."""

    return _adapter().retire(
        experiment_id, confirmation=approval_digest_confirmation
    )


@tool
def shutdown_research_harness(confirmation: str) -> dict[str, Any]:
    """Shut down the entire runtime only with the exact documented phrase."""

    return _adapter().shutdown(confirmation=confirmation)


@tool
def record_experiment_result(
    result_json: str,
    terminal_evidence_json: str,
    artifact_base_dir: str,
) -> dict[str, Any]:
    """
    Persist a result only when it exactly matches a launched authority snapshot.

    Args:
        result_json: Complete experiment-result/v1 JSON returned by the launched harness run.
        terminal_evidence_json: Complete native-terminal-evidence/v1 JSON for an enhanced
            lane, or harness-acceptance-evidence/v1 containing the ordinary lane's exact
            review, acceptance, and reviewed result records. This is only a consistency
            copy; the adapter rereads the Harness-owned records and requires their
            scientific_result to equal result_json.
        artifact_base_dir: Local directory resolving artifact: URIs; every referenced file is rehashed.
    """
    return _adapter().record_result(
        _object(result_json, "result_json"),
        terminal_evidence=_object(terminal_evidence_json, "terminal_evidence_json"),
        artifact_base_dir=artifact_base_dir,
    )
