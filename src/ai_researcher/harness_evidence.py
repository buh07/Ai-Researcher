"""Read terminal execution evidence only from the configured harness runtime.

The research layer must not treat a caller-provided JSON file as proof that a
Harness run completed.  This module resolves the Harness-owned runtime from its
validated local configuration and delegates all record/sibling validation to
the Harness implementation itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from orchestrator_harness.config import load_config
from orchestrator_harness.core import content_hash, read_json
from orchestrator_harness.lanes import LaneError, find_active_lane
from orchestrator_harness.records import read_record
from orchestrator_harness.review import (
    ACCEPTANCE_SCHEMA,
    COMPLETION_REVIEW_SCHEMA,
    validate_lane_acceptance_chain,
)
from orchestrator_harness.terminal_evidence import (
    TERMINAL_EVIDENCE_SCHEMA,
    TerminalEvidenceError,
    publication_dir,
    read_terminal_evidence,
)


class HarnessEvidenceError(RuntimeError):
    """Configured Harness state is missing, invalid, or contradictory."""


def active_harness_run(
    harness_root: str | Path, *, lane_id: str
) -> tuple[str, dict[str, Any]]:
    """Return the authoritative active epoch and lane record."""

    try:
        config = load_config(Path(harness_root).resolve())
        epoch_id, lane = find_active_lane(config.runtime_root, lane_id)
    except (OSError, ValueError, LaneError) as exc:
        raise HarnessEvidenceError(
            f"cannot resolve active Harness lane {lane_id!r}: {exc}"
        ) from exc
    return epoch_id, lane


def verified_terminal_evidence(
    harness_root: str | Path,
    *,
    lane_id: str,
    run_id: str,
    supplied: Mapping[str, Any],
    authority: Mapping[str, Any],
    scientific_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Return exact terminal evidence after validating its Harness-owned source.

    Enhanced Harness lanes publish ``native-terminal-evidence/v1``. Ordinary
    lanes publish the same hashed completion-review/acceptance pair without a
    native envelope. ``supplied`` is only a consistency copy in either case.
    """

    if not isinstance(supplied, Mapping):
        raise HarnessEvidenceError("terminal Harness evidence must be an object")
    if not isinstance(scientific_result, Mapping):
        raise HarnessEvidenceError("scientific result must be an object")
    epoch_id, lane = active_harness_run(harness_root, lane_id=lane_id)
    if lane.get("run_id") != run_id:
        raise HarnessEvidenceError("active Harness lane run does not match the launch binding")
    try:
        config = load_config(Path(harness_root).resolve())
        native = read_terminal_evidence(
            config.runtime_root, epoch_id, lane_id, run_id=run_id
        )
    except (OSError, ValueError, TerminalEvidenceError) as exc:
        raise HarnessEvidenceError(f"Harness terminal evidence is invalid: {exc}") from exc

    if native is not None:
        retained = native
    else:
        folder = publication_dir(config.runtime_root, epoch_id, lane)
        try:
            review = read_record(folder / "COMPLETION_REVIEW.json", COMPLETION_REVIEW_SCHEMA)
            acceptance = read_record(
                folder / "ORCHESTRATOR_ACCEPTANCE.json", ACCEPTANCE_SCHEMA
            )
        except (OSError, ValueError) as exc:
            raise HarnessEvidenceError(
                f"Harness completion review evidence is unavailable: {exc}"
            ) from exc
        if not validate_lane_acceptance_chain(review, acceptance, lane):
            raise HarnessEvidenceError(
                "Harness completion review does not match the active lane"
            )
        result_path = Path(str(lane.get("worktree_path", ""))) / "RESULT.json"
        try:
            harness_result = read_record(result_path, "result/v1")
        except (OSError, ValueError) as exc:
            raise HarnessEvidenceError(
                f"Harness-reviewed result is unavailable: {exc}"
            ) from exc
        if (
            harness_result.get("content_hash") != content_hash(harness_result)
            or harness_result.get("lane_id") != lane_id
            or harness_result.get("run_id") != run_id
            or review.get("result_hash") != harness_result["content_hash"]
        ):
            raise HarnessEvidenceError(
                "Harness-reviewed result does not match its completion review"
            )
        retained = {
            "schema": "harness-acceptance-evidence/v1",
            "epoch_id": epoch_id,
            "lane_id": lane_id,
            "run_id": run_id,
            "review": review,
            "acceptance": acceptance,
            "result": harness_result,
        }
    if dict(supplied) != retained:
        raise HarnessEvidenceError(
            "supplied terminal evidence differs from the Harness-owned record"
        )

    acceptance = retained.get("acceptance")
    review = retained.get("review")
    if not isinstance(acceptance, Mapping) or acceptance.get("approval") != "ACCEPTED":
        raise HarnessEvidenceError("native terminal evidence was not accepted by ROOT")
    if not isinstance(review, Mapping) or review.get("review_outcome") != "PASS":
        raise HarnessEvidenceError("native terminal evidence does not record a passing review")

    if retained.get("schema") == TERMINAL_EVIDENCE_SCHEMA:
        task_card = retained.get("task_card")
    else:
        task_path = Path(str(authority.get("task_card_path", "")))
        try:
            task_card = read_json(task_path)
        except (OSError, ValueError) as exc:
            raise HarnessEvidenceError(
                f"bound research task card is unavailable: {exc}"
            ) from exc
        if (
            task_card.get("content_hash") != content_hash(task_card)
            or task_card["content_hash"] != lane.get("task_card_hash")
        ):
            raise HarnessEvidenceError(
                "Harness lane does not attest the bound research task card"
            )
    research_authority = (
        task_card.get("research_authority") if isinstance(task_card, Mapping) else None
    )
    if not isinstance(research_authority, Mapping):
        raise HarnessEvidenceError("native task card omits research authority")
    for field in (
        "objective_confirmation_digest",
        "experiment_digest",
        "approval_digest",
    ):
        if research_authority.get(field) != authority.get(field):
            raise HarnessEvidenceError(
                f"native task card {field} does not match the launch binding"
            )
    return retained


def read_verified_terminal_evidence(
    harness_root: str | Path,
    *,
    lane_id: str,
    run_id: str,
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Read one accepted terminal record from Harness-owned storage.

    Unlike :func:`verified_terminal_evidence`, this entry point takes no
    caller-supplied evidence.  It is the production retrieval boundary used by
    status/result-ingestion tools after ROOT has completed its independent
    review.  Authority is still checked against the exact task card launched
    for the research experiment.
    """

    retained = _read_owned_terminal_evidence(
        harness_root, lane_id=lane_id, run_id=run_id
    )
    if retained.get("schema") != TERMINAL_EVIDENCE_SCHEMA:
        _epoch_id, lane = active_harness_run(harness_root, lane_id=lane_id)
        task_path = Path(str(authority.get("task_card_path", "")))
        try:
            task_card = read_json(task_path)
        except (OSError, ValueError) as exc:
            raise HarnessEvidenceError(
                f"bound research task card is unavailable: {exc}"
            ) from exc
        if (
            task_card.get("content_hash") != content_hash(task_card)
            or task_card.get("content_hash") != lane.get("task_card_hash")
        ):
            raise HarnessEvidenceError(
                "Harness lane does not attest the bound research task card"
            )
    _verify_terminal_authority(retained, authority=authority)
    return retained


def acceptance_reference(
    harness_root: str | Path,
    *,
    lane_id: str,
    run_id: str,
    authority: Mapping[str, Any],
) -> Path:
    """Return the validated Harness-owned acceptance path for retirement."""

    read_verified_terminal_evidence(
        harness_root,
        lane_id=lane_id,
        run_id=run_id,
        authority=authority,
    )
    epoch_id, lane = active_harness_run(harness_root, lane_id=lane_id)
    if lane.get("run_id") != run_id:
        raise HarnessEvidenceError("active Harness lane run changed before retirement")
    try:
        config = load_config(Path(harness_root).resolve())
    except (OSError, ValueError) as exc:
        raise HarnessEvidenceError(f"Harness configuration is invalid: {exc}") from exc
    path = publication_dir(config.runtime_root, epoch_id, lane) / "ORCHESTRATOR_ACCEPTANCE.json"
    try:
        acceptance = read_record(path, ACCEPTANCE_SCHEMA)
    except (OSError, ValueError) as exc:
        raise HarnessEvidenceError(f"Harness acceptance reference is invalid: {exc}") from exc
    if acceptance.get("approval") != "ACCEPTED":
        raise HarnessEvidenceError("Harness result was not accepted and cannot be retired")
    return path.resolve()


def _read_owned_terminal_evidence(
    harness_root: str | Path, *, lane_id: str, run_id: str
) -> dict[str, Any]:
    """Read and validate native or ordinary accepted Harness evidence."""

    epoch_id, lane = active_harness_run(harness_root, lane_id=lane_id)
    if lane.get("run_id") != run_id:
        raise HarnessEvidenceError("active Harness lane run does not match the launch binding")
    try:
        config = load_config(Path(harness_root).resolve())
        native = read_terminal_evidence(
            config.runtime_root, epoch_id, lane_id, run_id=run_id
        )
    except (OSError, ValueError, TerminalEvidenceError) as exc:
        raise HarnessEvidenceError(f"Harness terminal evidence is invalid: {exc}") from exc

    if native is not None:
        retained = native
    else:
        folder = publication_dir(config.runtime_root, epoch_id, lane)
        try:
            review = read_record(folder / "COMPLETION_REVIEW.json", COMPLETION_REVIEW_SCHEMA)
            acceptance = read_record(
                folder / "ORCHESTRATOR_ACCEPTANCE.json", ACCEPTANCE_SCHEMA
            )
        except (OSError, ValueError) as exc:
            raise HarnessEvidenceError(
                f"Harness completion review evidence is unavailable: {exc}"
            ) from exc
        if not validate_lane_acceptance_chain(review, acceptance, lane):
            raise HarnessEvidenceError(
                "Harness completion review does not match the active lane"
            )
        result_path = Path(str(lane.get("worktree_path", ""))) / "RESULT.json"
        try:
            harness_result = read_record(result_path, "result/v1")
        except (OSError, ValueError) as exc:
            raise HarnessEvidenceError(
                f"Harness-reviewed result is unavailable: {exc}"
            ) from exc
        if (
            harness_result.get("content_hash") != content_hash(harness_result)
            or harness_result.get("lane_id") != lane_id
            or harness_result.get("run_id") != run_id
            or review.get("result_hash") != harness_result["content_hash"]
        ):
            raise HarnessEvidenceError(
                "Harness-reviewed result does not match its completion review"
            )
        retained = {
            "schema": "harness-acceptance-evidence/v1",
            "epoch_id": epoch_id,
            "lane_id": lane_id,
            "run_id": run_id,
            "review": review,
            "acceptance": acceptance,
            "result": harness_result,
        }

    acceptance = retained.get("acceptance")
    review = retained.get("review")
    if not isinstance(acceptance, Mapping) or acceptance.get("approval") != "ACCEPTED":
        raise HarnessEvidenceError("terminal evidence was not accepted by ROOT")
    if not isinstance(review, Mapping) or review.get("review_outcome") != "PASS":
        raise HarnessEvidenceError("terminal evidence does not record a passing review")
    return retained


def _verify_terminal_authority(
    retained: Mapping[str, Any], *, authority: Mapping[str, Any]
) -> None:
    """Verify retained task-card authority against the durable binding."""

    if retained.get("schema") == TERMINAL_EVIDENCE_SCHEMA:
        task_card = retained.get("task_card")
    else:
        task_path = Path(str(authority.get("task_card_path", "")))
        try:
            task_card = read_json(task_path)
        except (OSError, ValueError) as exc:
            raise HarnessEvidenceError(
                f"bound research task card is unavailable: {exc}"
            ) from exc
    research_authority = (
        task_card.get("research_authority") if isinstance(task_card, Mapping) else None
    )
    if not isinstance(research_authority, Mapping):
        raise HarnessEvidenceError("terminal task card omits research authority")
    for field in (
        "objective_confirmation_digest",
        "experiment_digest",
        "approval_digest",
    ):
        if research_authority.get(field) != authority.get(field):
            raise HarnessEvidenceError(
                f"terminal task card {field} does not match the launch binding"
            )
