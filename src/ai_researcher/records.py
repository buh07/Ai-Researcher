"""Validation and stable identity for scientific handoff records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class RecordValidationError(ValueError):
    """A scientific record is incomplete, inconsistent, or unsupported."""


ID_FIELDS = {
    "research-question/v1": "question_id",
    "evidence-package/v1": "question_id",
    "hypothesis-portfolio/v1": "question_id",
    "experiment-candidates/v1": "question_id",
    "safety-review/v1": "experiment_id",
    "human-approval/v1": "approval_id",
    "experiment-result/v1": "run_id",
    "updated-decision/v1": "run_id",
}


def canonical_json(value: Mapping[str, Any]) -> bytes:
    """Return the canonical UTF-8 representation used for record identity."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RecordValidationError("record must be finite JSON") from exc


def record_digest(record: Mapping[str, Any]) -> str:
    """Hash a record without trusting a caller-provided digest field."""

    payload = {key: value for key, value in record.items() if key != "record_digest"}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def selected_experiment(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact selected experiment from a validated portfolio."""

    normalized = validate_record(record, "experiment-candidates/v1")
    selected = normalized["selected_experiment_id"]
    return next(item for item in normalized["candidates"] if item["experiment_id"] == selected)


def experiment_digest(record: Mapping[str, Any]) -> str:
    """Return the digest of only the selected executable specification."""

    return hashlib.sha256(canonical_json(selected_experiment(record))).hexdigest()


def validate_record(
    record: Mapping[str, Any], expected_schema: str | None = None
) -> dict[str, Any]:
    """Validate and return a normalized scientific record."""

    if not isinstance(record, Mapping):
        raise RecordValidationError("record must be a JSON object")
    normalized = json.loads(canonical_json(record).decode("utf-8"))
    schema = _required_str(normalized, "schema")
    if expected_schema is not None and schema != expected_schema:
        raise RecordValidationError(
            f"expected schema {expected_schema!r}, received {schema!r}"
        )
    if schema not in ID_FIELDS:
        raise RecordValidationError(f"unsupported schema: {schema!r}")
    _required_str(normalized, ID_FIELDS[schema])

    validator = {
        "research-question/v1": _validate_question,
        "evidence-package/v1": _validate_evidence,
        "hypothesis-portfolio/v1": _validate_hypotheses,
        "experiment-candidates/v1": _validate_experiments,
        "safety-review/v1": _validate_safety,
        "human-approval/v1": _validate_approval,
        "experiment-result/v1": _validate_result,
        "updated-decision/v1": _validate_decision,
    }[schema]
    validator(normalized)

    claimed_digest = normalized.get("record_digest")
    actual_digest = record_digest(normalized)
    if claimed_digest is not None and claimed_digest != actual_digest:
        raise RecordValidationError("record_digest does not match the record payload")
    normalized["record_digest"] = actual_digest
    return normalized


def primary_id(record: Mapping[str, Any]) -> str:
    normalized = validate_record(record)
    return str(normalized[ID_FIELDS[normalized["schema"]]])


def _required_str(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RecordValidationError(f"{field} must be a non-empty string")
    return value


def _string_list(record: Mapping[str, Any], field: str, *, allow_empty: bool = True) -> None:
    value = record.get(field)
    if not isinstance(value, list) or (not allow_empty and not value) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        qualifier = "a" if allow_empty else "a non-empty"
        raise RecordValidationError(f"{field} must be {qualifier} list of strings")


def _validate_question(record: dict[str, Any]) -> None:
    for field in ("question", "measurable_outcome", "primary_metric"):
        _required_str(record, field)
    _string_list(record, "constraints")
    _string_list(record, "assumptions")


def _validate_evidence(record: dict[str, Any]) -> None:
    claims = record.get("claims")
    if not isinstance(claims, list):
        raise RecordValidationError("claims must be a list")
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise RecordValidationError("each evidence claim must be an object")
        for field in ("evidence_id", "claim", "source_type", "support"):
            _required_str(claim, field)
        citation = claim.get("citation")
        if not isinstance(citation, Mapping):
            raise RecordValidationError("each evidence claim requires a citation object")
        for field in ("title", "url", "authors_or_organization", "retrieved_at"):
            _required_str(citation, field)
    _string_list(record, "conflicts")
    _string_list(record, "coverage_gaps")


def _validate_hypotheses(record: dict[str, Any]) -> None:
    hypotheses = record.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise RecordValidationError("hypotheses must be a non-empty list")
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, Mapping):
            raise RecordValidationError("each hypothesis must be an object")
        for field in ("hypothesis_id", "statement", "prediction", "falsification_condition"):
            _required_str(hypothesis, field)
        _string_list(hypothesis, "supporting_evidence_ids")


def _validate_experiments(record: dict[str, Any]) -> None:
    _required_str(record, "hypothesis_id")
    candidates = record.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise RecordValidationError("at least two experiment candidates are required")
    identifiers: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise RecordValidationError("each experiment candidate must be an object")
        identifier = _required_str(candidate, "experiment_id")
        if identifier in identifiers:
            raise RecordValidationError("experiment_id values must be unique")
        identifiers.add(identifier)
        for field in ("method", "baseline", "success_threshold", "expected_learning"):
            _required_str(candidate, field)
        if not isinstance(candidate.get("parameters"), Mapping):
            raise RecordValidationError("experiment parameters must be an object")
        if not isinstance(candidate.get("metrics"), list) or not candidate["metrics"]:
            raise RecordValidationError("each experiment needs at least one metric")
    selected = _required_str(record, "selected_experiment_id")
    if selected not in identifiers:
        raise RecordValidationError("selected_experiment_id is not a candidate")
    _required_str(record, "selection_rationale")


def _validate_safety(record: dict[str, Any]) -> None:
    verdict = _required_str(record, "verdict")
    if verdict not in {"APPROVAL_REQUIRED", "REVISE", "REJECT"}:
        raise RecordValidationError("safety verdict is invalid")
    for field in ("risks", "required_controls", "prohibited_actions", "review_limitations"):
        _string_list(record, field)
    if verdict == "APPROVAL_REQUIRED":
        _required_str(record, "approval_question")


def _validate_approval(record: dict[str, Any]) -> None:
    for field in ("experiment_id", "experiment_digest", "approved_by", "approved_at"):
        _required_str(record, field)
    if record.get("approved") is not True:
        raise RecordValidationError("human approval must contain approved=true")
    if record.get("scope") != "execute-exact-experiment":
        raise RecordValidationError("approval scope must be execute-exact-experiment")
    _string_list(record, "constraints")


def _validate_result(record: dict[str, Any]) -> None:
    for field in (
        "experiment_id",
        "execution_source",
        "code_identity",
        "dataset_identity",
        "environment_identity",
        "started_at",
        "completed_at",
        "status",
    ):
        _required_str(record, field)
    if not isinstance(record.get("metrics"), Mapping):
        raise RecordValidationError("metrics must be an object")
    if not isinstance(record.get("parameters"), Mapping):
        raise RecordValidationError("parameters must be an object")
    _string_list(record, "artifact_refs")
    _string_list(record, "limitations")


def _validate_decision(record: dict[str, Any]) -> None:
    for field in ("question_id", "hypothesis_id", "experiment_id", "rationale"):
        _required_str(record, field)
    if record.get("decision") not in {"support", "revise", "reject", "inconclusive"}:
        raise RecordValidationError("updated decision is invalid")
    _string_list(record, "supporting_evidence_ids")
    _string_list(record, "remaining_uncertainty")
    if not isinstance(record.get("next_experiment"), Mapping):
        raise RecordValidationError("next_experiment must be an object")
