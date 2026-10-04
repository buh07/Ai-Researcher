"""Strict validation and stable identities for scientific handoff records."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


class RecordValidationError(ValueError):
    """A scientific record is incomplete, inconsistent, or unsupported."""


ID_FIELDS = {
    "research-question/v1": "question_id",
    "objective-confirmation/v1": "objective_confirmation_id",
    "feasibility-check/v1": "feasibility_check_id",
    "evidence-package/v1": "evidence_package_id",
    "parallel-branch/v1": "branch_id",
    "branch-reconciliation/v1": "reconciliation_id",
    "hypothesis-portfolio/v1": "hypothesis_portfolio_id",
    "experiment-candidates/v1": "experiment_candidates_id",
    "safety-review/v1": "experiment_id",
    "human-approval/v1": "approval_id",
    "experiment-result/v1": "run_id",
    "updated-decision/v1": "run_id",
    "acceleration-summary/v1": "acceleration_summary_id",
}

LEGACY_V1_ID_FIELDS = {
    "research-question/v1": "question_id",
    "evidence-package/v1": "evidence_package_id",
    "hypothesis-portfolio/v1": "question_id",
    "experiment-candidates/v1": "question_id",
    "safety-review/v1": "experiment_id",
    "human-approval/v1": "approval_id",
    "experiment-result/v1": "run_id",
    "updated-decision/v1": "run_id",
}

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OBJECTIVE_BOUND_SCHEMAS = frozenset(ID_FIELDS) - {
    "research-question/v1",
    "objective-confirmation/v1",
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
    """Hash a record without trusting caller-provided self-digest fields."""

    payload = {key: value for key, value in record.items() if key != "record_digest"}
    if record.get("schema") == "objective-confirmation/v1":
        payload.pop("objective_confirmation_digest", None)
    if record.get("schema") == "learning-receipt/v1":
        payload.pop("receipt_digest", None)
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def decision_timing_digest(timing: Mapping[str, Any]) -> str:
    """Identify the embedded, immutable decision-timing measurement artifact."""

    return hashlib.sha256(canonical_json(timing)).hexdigest()


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
    """Validate and normalize one scientific record.

    Cross-record identity and provenance checks happen atomically when the
    record enters :class:`ResearchJournal`.
    """

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
    if schema in _OBJECTIVE_BOUND_SCHEMAS:
        _required_digest(normalized, "objective_confirmation_digest")

    validator = {
        "research-question/v1": _validate_question,
        "objective-confirmation/v1": _validate_objective,
        "feasibility-check/v1": _validate_feasibility,
        "evidence-package/v1": _validate_evidence,
        "parallel-branch/v1": _validate_parallel_branch,
        "branch-reconciliation/v1": _validate_reconciliation,
        "hypothesis-portfolio/v1": _validate_hypotheses,
        "experiment-candidates/v1": _validate_experiments,
        "safety-review/v1": _validate_safety,
        "human-approval/v1": _validate_approval,
        "experiment-result/v1": _validate_result,
        "updated-decision/v1": _validate_decision,
        "acceleration-summary/v1": _validate_acceleration,
    }[schema]
    validator(normalized)

    claimed_digest = normalized.get("record_digest")
    actual_digest = record_digest(normalized)
    if claimed_digest is not None and claimed_digest != actual_digest:
        raise RecordValidationError("record_digest does not match the record payload")
    if schema == "objective-confirmation/v1":
        claimed_objective_digest = normalized.get("objective_confirmation_digest")
        if claimed_objective_digest is not None and claimed_objective_digest != actual_digest:
            raise RecordValidationError(
                "objective_confirmation_digest does not match the record payload"
            )
        normalized["objective_confirmation_digest"] = actual_digest
    normalized["record_digest"] = actual_digest
    return normalized


def validate_stored_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a persisted record using strict current or read-only legacy rules.

    Legacy validation exists only for pre-authority ``/v1`` journal payloads.
    It is deliberately not used by :func:`validate_record` or journal append,
    so a legacy payload can be inspected but cannot enter a new authority chain.
    """

    try:
        return validate_record(record)
    except RecordValidationError as current_error:
        try:
            return _validate_legacy_v1(record)
        except RecordValidationError:
            raise current_error


def stored_record_uses_legacy_contract(record: Mapping[str, Any]) -> bool:
    """Return whether a valid stored payload needs the read-only legacy profile."""

    try:
        validate_record(record)
        return False
    except RecordValidationError:
        _validate_legacy_v1(record)
        return True


def primary_id(record: Mapping[str, Any]) -> str:
    normalized = validate_record(record)
    return str(normalized[ID_FIELDS[normalized["schema"]]])


def _required_str(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RecordValidationError(f"{field} must be a non-empty string")
    return value


def _required_digest(record: Mapping[str, Any], field: str) -> str:
    value = _required_str(record, field)
    if _DIGEST.fullmatch(value) is None:
        raise RecordValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _required_mapping(record: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = record.get(field)
    if not isinstance(value, Mapping):
        raise RecordValidationError(f"{field} must be an object")
    return value


def _string_list(
    record: Mapping[str, Any], field: str, *, allow_empty: bool = True
) -> list[str]:
    value = record.get(field)
    if not isinstance(value, list) or (not allow_empty and not value) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        qualifier = "a" if allow_empty else "a non-empty"
        raise RecordValidationError(f"{field} must be {qualifier} list of strings")
    return value


def _required_number(
    record: Mapping[str, Any], field: str, *, minimum: float = 0, integer: bool = False
) -> int | float:
    value = record.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise RecordValidationError(f"{field} must be a finite number")
    if integer and not isinstance(value, int):
        raise RecordValidationError(f"{field} must be an integer")
    if value < minimum:
        raise RecordValidationError(f"{field} must be at least {minimum}")
    return value


def _nullable_number(
    record: Mapping[str, Any],
    field: str,
    *,
    minimum: float = 0,
    integer: bool = False,
) -> int | float | None:
    value = record.get(field)
    if value is None:
        return None
    return _required_number(record, field, minimum=minimum, integer=integer)


def _two_arm_mapping(record: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = _required_mapping(record, field)
    if set(value) != {"baseline", "proposed"}:
        raise RecordValidationError(
            f"{field} must contain exactly baseline and proposed"
        )
    return value


def _dataset_identity(record: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    identity = _required_mapping(record, field)
    for key in ("identifier", "version"):
        _required_str(identity, key)
    _required_digest(identity, "digest")
    return identity


def _timestamp(record: Mapping[str, Any], field: str) -> datetime:
    value = _required_str(record, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecordValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RecordValidationError(f"{field} must include a timezone")
    return parsed


def _validate_question(record: dict[str, Any]) -> None:
    for field in (
        "question",
        "domain",
        "intended_scientific_use",
        "measurable_outcome",
        "primary_metric",
    ):
        _required_str(record, field)
    _string_list(record, "constraints")
    _string_list(record, "assumptions")


def _validate_objective(record: dict[str, Any]) -> None:
    _required_str(record, "question_id")
    _required_digest(record, "question_digest")
    _required_str(record, "primary_metric")
    dataset = _dataset_identity(record, "dataset")
    _required_str(dataset, "source")
    if urlparse(dataset["source"]).scheme not in {"https", "http", "file"}:
        raise RecordValidationError("dataset source must be a stable URL or file URI")

    risk = _required_mapping(record, "risk_tolerance")
    _required_str(risk, "level")
    for field in (
        "allowed_risks",
        "prohibited_actions",
        "privacy_constraints",
        "acceptable_failure_modes",
    ):
        _string_list(risk, field)
    scope = _required_mapping(record, "execution_scope")
    _required_number(scope, "max_trials", minimum=1, integer=True)
    _required_number(scope, "max_runtime_minutes", minimum=0)
    _required_number(scope, "max_cost_usd", minimum=0)
    for field in ("compute", "network_access"):
        _required_str(scope, field)
    _string_list(scope, "mutation_permissions")
    _required_str(record, "confirmed_by")
    _timestamp(record, "confirmed_at")
    if "supersedes_objective_confirmation_digest" in record:
        _required_digest(record, "supersedes_objective_confirmation_digest")


def _validate_feasibility(record: dict[str, Any]) -> None:
    _required_str(record, "question_id")
    _required_str(record, "checked_by")
    _timestamp(record, "checked_at")
    checks = _required_mapping(record, "checks")
    mandatory = {"access", "identity", "license", "privacy", "api", "compute"}
    if set(checks) != mandatory:
        raise RecordValidationError(
            "checks must contain exactly access, identity, license, privacy, api, and compute"
        )
    statuses: list[str] = []
    for name in sorted(mandatory):
        check = _required_mapping(checks, name)
        status = _required_str(check, "status")
        if status not in {"PASS", "FAIL"}:
            raise RecordValidationError(f"checks.{name}.status must be PASS or FAIL")
        statuses.append(status)
        _required_str(check, "evidence")
    expected = "PASS" if all(item == "PASS" for item in statuses) else "FAIL"
    if record.get("overall_status") != expected:
        raise RecordValidationError(f"overall_status must be {expected}")
    _required_str(record, "fallback")


def _validate_evidence(record: dict[str, Any]) -> None:
    _required_str(record, "question_id")
    claims = record.get("claims")
    if not isinstance(claims, list):
        raise RecordValidationError("claims must be a list")
    identifiers: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise RecordValidationError("each evidence claim must be an object")
        identifier = _required_str(claim, "evidence_id")
        if identifier in identifiers:
            raise RecordValidationError("evidence_id values must be unique within a package")
        identifiers.add(identifier)
        if _required_str(claim, "claim_type") != "external-fact":
            raise RecordValidationError(
                "observed measurements require an experiment-result reference, not an external citation"
            )
        for field in ("claim", "source_type", "support", "uncertainty"):
            _required_str(claim, field)
        if claim["source_type"] in {
            "experiment-result",
            "local-run",
            "agent-hypothesis",
        }:
            raise RecordValidationError("source_type is not an external evidence source")
        citation = _required_mapping(claim, "citation")
        for field in (
            "title",
            "authors_or_organization",
            "publisher_or_source",
            "retrieved_at",
            "license_or_access_note",
            "verification_state",
        ):
            _required_str(citation, field)
        _timestamp(citation, "retrieved_at")
        identifiers_present = [
            citation.get(name)
            for name in ("url", "doi", "openalex_id", "arxiv_id", "openml_id")
        ]
        if not any(
            isinstance(value, str) and value.strip() for value in identifiers_present
        ):
            raise RecordValidationError("citation requires a stable external identifier")
        if "url" in citation and urlparse(_required_str(citation, "url")).scheme not in {
            "http",
            "https",
        }:
            raise RecordValidationError("citation url must use http or https")
        if citation["verification_state"] not in {
            "verified",
            "partially-verified",
            "unverified",
        }:
            raise RecordValidationError("citation verification_state is invalid")
    _string_list(record, "conflicts")
    _string_list(record, "coverage_gaps")


def _validate_parallel_branch(record: dict[str, Any]) -> None:
    _required_str(record, "question_id")
    for field in ("bounded_question", "producer_agent_id", "producer_session_id"):
        _required_str(record, field)
    started = _timestamp(record, "started_at")
    completed = _timestamp(record, "completed_at")
    if completed <= started:
        raise RecordValidationError("completed_at must be later than started_at")
    if record.get("status") not in {"COMPLETED", "ERROR", "CANCELLED"}:
        raise RecordValidationError("parallel branch status is invalid")
    if record.get("independent_context") is not True:
        raise RecordValidationError("parallel branch must attest independent_context=true")
    _required_str(record, "invocation_id")
    _required_str(record, "provider_session_id")
    _required_digest(record, "provider_receipt_digest")
    if record.get("invocation_status") != "COMPLETED":
        raise RecordValidationError(
            "parallel branch invocation_status must be COMPLETED"
        )
    if record["status"] == "COMPLETED":
        _required_digest(record, "evidence_package_digest")


def _validate_reconciliation(record: dict[str, Any]) -> None:
    _required_str(record, "question_id")
    digests = _string_list(record, "branch_digests", allow_empty=False)
    if len(digests) < 2 or len(set(digests)) != len(digests):
        raise RecordValidationError(
            "branch_digests must contain at least two unique digests"
        )
    for digest in digests:
        if _DIGEST.fullmatch(digest) is None:
            raise RecordValidationError(
                "branch_digests must be lowercase SHA-256 digests"
            )
    for field in (
        "agreements",
        "conflicts",
        "unresolved_questions",
        "reconciled_evidence_ids",
    ):
        _string_list(record, field)
    status = record.get("parallel_status")
    if status not in {"MET", "UNMET"}:
        raise RecordValidationError("parallel_status must be MET or UNMET")
    pairs = record.get("overlapping_branch_pairs")
    if not isinstance(pairs, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or pair[0] == pair[1]
        or any(not isinstance(item, str) or not item.strip() for item in pair)
        for pair in pairs
    ):
        raise RecordValidationError(
            "overlapping_branch_pairs must contain two-branch ID pairs"
        )
    if status == "MET" and not pairs:
        raise RecordValidationError(
            "parallel_status MET requires an overlapping branch pair"
        )
    if status == "UNMET" and pairs:
        raise RecordValidationError(
            "parallel_status UNMET cannot claim overlapping branches"
        )


def _validate_hypotheses(record: dict[str, Any]) -> None:
    hypotheses = record.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise RecordValidationError("hypotheses must be a non-empty list")
    identifiers: set[str] = set()
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, Mapping):
            raise RecordValidationError("each hypothesis must be an object")
        identifier = _required_str(hypothesis, "hypothesis_id")
        if identifier in identifiers:
            raise RecordValidationError("hypothesis_id values must be unique")
        identifiers.add(identifier)
        for field in (
            "statement",
            "prediction",
            "falsification_condition",
            "uncertainty",
        ):
            _required_str(hypothesis, field)
        _string_list(hypothesis, "supporting_evidence_ids", allow_empty=False)
        _string_list(hypothesis, "competing_explanations")


def _validate_experiments(record: dict[str, Any]) -> None:
    _required_str(record, "question_id")
    _required_str(record, "hypothesis_id")
    _required_str(record, "primary_metric")
    _dataset_identity(record, "dataset_identity")
    bounds = _required_mapping(record, "resource_bounds")
    _required_number(bounds, "max_trials", minimum=1, integer=True)
    _required_number(bounds, "max_runtime_minutes", minimum=0)
    _required_number(bounds, "max_cost_usd", minimum=0)
    for field in ("compute", "network_access"):
        _required_str(bounds, field)
    _string_list(bounds, "mutation_permissions")
    risk_tolerance = _required_mapping(record, "risk_tolerance")
    _required_str(risk_tolerance, "level")
    for field in (
        "allowed_risks",
        "prohibited_actions",
        "privacy_constraints",
        "acceptable_failure_modes",
    ):
        _string_list(risk_tolerance, field)
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
        for field in (
            "method",
            "baseline",
            "success_threshold",
            "expected_learning",
            "risk_level",
        ):
            _required_str(candidate, field)
        for field in ("controls", "inputs", "metrics"):
            _string_list(candidate, field, allow_empty=False)
        if record["primary_metric"] not in candidate["metrics"]:
            raise RecordValidationError(
                "each candidate must include the predeclared primary_metric"
            )
        parameters = _required_mapping(candidate, "parameters")
        if not parameters:
            raise RecordValidationError("candidate parameters must be executable and non-empty")
        trials_per_arm = _required_number(
            parameters, "max_trials_per_arm", minimum=1, integer=True
        )
        seconds_per_arm = _required_number(
            parameters, "max_seconds_per_arm", minimum=0
        )
        _required_number(parameters, "threshold", minimum=-math.inf)
        if trials_per_arm * 2 > bounds["max_trials"]:
            raise RecordValidationError(
                "candidate max_trials_per_arm exceeds resource_bounds"
            )
        if seconds_per_arm * 2 > bounds["max_runtime_minutes"] * 60:
            raise RecordValidationError(
                "candidate max_seconds_per_arm exceeds resource_bounds"
            )
        seeds = candidate.get("random_seeds")
        if not isinstance(seeds, list) or not seeds or any(
            isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds
        ):
            raise RecordValidationError(
                "random_seeds must be a non-empty list of integers"
            )
        _required_number(candidate, "estimated_runtime_minutes", minimum=0)
        _required_number(candidate, "estimated_cost_usd", minimum=0)
        if candidate["estimated_runtime_minutes"] > bounds["max_runtime_minutes"]:
            raise RecordValidationError(
                "candidate estimated runtime exceeds resource_bounds"
            )
        if candidate["estimated_cost_usd"] > bounds["max_cost_usd"]:
            raise RecordValidationError(
                "candidate estimated cost exceeds resource_bounds"
            )
        if candidate["risk_level"] != risk_tolerance["level"]:
            raise RecordValidationError(
                "candidate risk_level must match confirmed risk tolerance"
            )
    selected = _required_str(record, "selected_experiment_id")
    if selected not in identifiers:
        raise RecordValidationError("selected_experiment_id is not a candidate")
    _required_str(record, "selection_rationale")
    rationales = _required_mapping(record, "rejected_candidate_rationales")
    rejected = identifiers - {selected}
    if set(rationales) != rejected or any(
        not isinstance(value, str) or not value.strip()
        for value in rationales.values()
    ):
        raise RecordValidationError(
            "every rejected candidate requires exactly one rationale"
        )


def _validate_safety(record: dict[str, Any]) -> None:
    _required_digest(record, "experiment_digest")
    verdict = _required_str(record, "verdict")
    if verdict not in {"APPROVAL_REQUIRED", "REVISE", "REJECT"}:
        raise RecordValidationError("safety verdict is invalid")
    for field in (
        "risks",
        "required_controls",
        "prohibited_actions",
        "review_limitations",
    ):
        _string_list(record, field)
    if verdict == "APPROVAL_REQUIRED":
        _required_str(record, "approval_question")


def _validate_approval(record: dict[str, Any]) -> None:
    for field in ("experiment_id", "approved_by"):
        _required_str(record, field)
    _required_digest(record, "experiment_digest")
    _timestamp(record, "approved_at")
    if record.get("approved") is not True:
        raise RecordValidationError("human approval must contain approved=true")
    if record.get("scope") != "execute-exact-experiment":
        raise RecordValidationError(
            "approval scope must be execute-exact-experiment"
        )
    _string_list(record, "constraints")


def _validate_result(record: dict[str, Any]) -> None:
    for field in (
        "question_id",
        "experiment_id",
        "execution_source",
        "code_identity",
        "environment_identity",
        "primary_metric",
        "status",
    ):
        _required_str(record, field)
    _dataset_identity(record, "dataset_identity")
    _required_digest(record, "experiment_digest")
    _required_digest(record, "approval_digest")
    _required_digest(record, "task_card_digest")
    started = _timestamp(record, "started_at")
    completed = _timestamp(record, "completed_at")
    if completed < started:
        raise RecordValidationError("completed_at cannot precede started_at")
    metrics = _required_mapping(record, "metrics")
    if "decision_latency_seconds" in metrics:
        raise RecordValidationError(
            "experiment result precedes independent analysis and cannot contain decision latency"
        )
    primary_metric = record["primary_metric"]
    if primary_metric != "trials_to_threshold" or primary_metric not in metrics:
        raise RecordValidationError(
            "the current primary metric must be trials_to_threshold"
        )
    endpoints = _two_arm_mapping(metrics, primary_metric)
    for arm_name, endpoint in endpoints.items():
        if not isinstance(endpoint, Mapping):
            raise RecordValidationError(
                f"{primary_metric}.{arm_name} must be an endpoint object"
            )
        censored = endpoint.get("censored")
        value = endpoint.get("value")
        if not isinstance(censored, bool):
            raise RecordValidationError(
                f"{primary_metric}.{arm_name}.censored must be boolean"
            )
        if censored:
            if value is not None or not isinstance(
                endpoint.get("lower_bound_exclusive"), int
            ):
                raise RecordValidationError(
                    f"{primary_metric}.{arm_name} has invalid censoring"
                )
        elif isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RecordValidationError(
                f"{primary_metric}.{arm_name}.value must be a positive integer"
            )
    required_arm_metrics = {
        "accuracy",
        "elapsed_to_threshold_seconds",
        "total_elapsed_seconds",
        "compute_seconds",
        "interventions",
        "cost_usd",
        "token_usage",
    }
    for metric in required_arm_metrics:
        values = _two_arm_mapping(metrics, metric)
        for arm_name in ("baseline", "proposed"):
            holder = {metric: values[arm_name]}
            if metric in {"interventions", "token_usage"}:
                _nullable_number(holder, metric, integer=True)
            elif metric in {
                "cost_usd",
                "elapsed_to_threshold_seconds",
                "compute_seconds",
            }:
                _nullable_number(holder, metric)
            elif metric == "accuracy":
                _nullable_number(holder, metric, minimum=-math.inf)
            else:
                _required_number(holder, metric, minimum=0)
    parameters = _required_mapping(record, "parameters")
    _required_mapping(parameters, "approved_candidate_parameters")
    _required_mapping(parameters, "observed_preregistration")
    execution_metadata = _required_mapping(parameters, "execution_metadata")
    availability = _required_mapping(execution_metadata, "measurement_availability")
    if set(availability) != {"baseline", "proposed"}:
        raise RecordValidationError(
            "result measurement availability must cover both arms exactly"
        )
    for arm_name, nested_name in (
        ("baseline", "baseline"),
        ("proposed", "evidence_guided"),
    ):
        nested_metrics = _required_mapping(metrics, nested_name)
        nested_availability = _required_mapping(
            nested_metrics, "measurement_availability"
        )
        if availability[arm_name] != nested_availability:
            raise RecordValidationError(
                f"result {arm_name} measurement availability is inconsistent"
            )
        compute_status = nested_availability.get("compute_seconds")
        expected_compute_status = (
            "UNAVAILABLE"
            if metrics["compute_seconds"][arm_name] is None
            else "MEASURED"
        )
        if compute_status != expected_compute_status:
            raise RecordValidationError(
                f"result {arm_name} compute availability contradicts its value"
            )
    if "decision_latency" in availability or "decision_timing_source_digest" in availability:
        raise RecordValidationError(
            "experiment result precedes independent analysis and cannot contain decision timing"
        )
    if record.get("status") not in {"PASS", "FAIL", "ERROR", "CANCELLED"}:
        raise RecordValidationError("result status is invalid")
    seeds = record.get("random_seeds")
    if not isinstance(seeds, list) or any(
        isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds
    ):
        raise RecordValidationError("random_seeds must be a list of integers")
    artifacts = record.get("artifact_refs")
    if not isinstance(artifacts, list):
        raise RecordValidationError("artifact_refs must be a list")
    artifact_digests: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise RecordValidationError(
                "artifact_refs must use structured run references"
            )
        for field in ("uri", "kind"):
            _required_str(artifact, field)
        artifact_digests.add(_required_digest(artifact, "digest"))
    support = _required_mapping(record, "measurement_support")
    if set(support) != set(metrics):
        raise RecordValidationError(
            "measurement_support must cover every metric exactly"
        )
    for metric, digest in support.items():
        if not isinstance(digest, str) or digest not in artifact_digests:
            raise RecordValidationError(
                f"measurement_support for {metric!r} must resolve to an artifact digest"
            )
    if metrics and not artifacts:
        raise RecordValidationError(
            "measured results require at least one immutable artifact reference"
        )
    _string_list(record, "limitations")


def _validate_decision(record: dict[str, Any]) -> None:
    for field in ("question_id", "hypothesis_id", "experiment_id", "rationale"):
        _required_str(record, field)
    _required_digest(record, "result_digest")
    if record.get("decision") not in {
        "support",
        "revise",
        "reject",
        "inconclusive",
    }:
        raise RecordValidationError("updated decision is invalid")
    _string_list(record, "supporting_evidence_ids")
    _string_list(record, "remaining_uncertainty")
    _string_list(record, "interpreted_metrics", allow_empty=False)
    next_experiment = _required_mapping(record, "next_experiment")
    for field in ("question", "rationale"):
        _required_str(next_experiment, field)
    if record.get("human_review_required") is not True:
        raise RecordValidationError("updated decision must require human review")
    timing = _required_mapping(record, "decision_timing")
    if set(timing) != {
        "schema",
        "result_digest",
        "run_id",
        "harness_acceptance_digest",
        "result_accepted_at",
        "decision_completed_at",
        "latency_seconds",
    }:
        raise RecordValidationError(
            "decision_timing must be the exact embedded measurement artifact"
        )
    if timing.get("schema") != "decision-timing-measurement/v1":
        raise RecordValidationError("decision_timing schema is invalid")
    if timing.get("result_digest") != record.get("result_digest"):
        raise RecordValidationError("decision_timing result_digest differs from the decision")
    if timing.get("run_id") != record.get("run_id"):
        raise RecordValidationError("decision_timing run_id differs from the decision")
    _required_digest(timing, "harness_acceptance_digest")
    accepted = _timestamp(timing, "result_accepted_at")
    completed = _timestamp(timing, "decision_completed_at")
    if completed < accepted:
        raise RecordValidationError(
            "decision_completed_at cannot precede result_accepted_at"
        )
    latency = _required_number(timing, "latency_seconds", minimum=0)
    if latency != (completed - accepted).total_seconds():
        raise RecordValidationError(
            "decision latency must equal the two immutable boundary timestamps"
        )
    if _required_digest(record, "decision_timing_source_digest") != decision_timing_digest(
        timing
    ):
        raise RecordValidationError(
            "decision_timing_source_digest does not identify decision_timing"
        )


def _validate_acceleration(record: dict[str, Any]) -> None:
    _required_str(record, "question_id")
    _required_str(record, "experiment_id")
    _required_digest(record, "result_digest")
    _required_digest(record, "updated_decision_digest")
    if _required_str(record, "primary_metric") != "trials_to_threshold":
        raise RecordValidationError(
            "acceleration primary_metric must be trials_to_threshold"
        )
    _dataset_identity(record, "dataset_identity")
    if _required_str(record, "timing_scope") not in {
        "end-to-end-arm-workflow",
        "model-evaluation-only",
    }:
        raise RecordValidationError("acceleration timing_scope is invalid")
    _required_number(record, "decision_latency_seconds", minimum=0)
    _required_digest(record, "decision_timing_source_digest")
    _required_digest(record, "matched_controls_digest")
    _required_mapping(record, "endpoint_rules")
    discovery_claim = record.get("overall_discovery_speed_claim")
    if not isinstance(discovery_claim, bool):
        raise RecordValidationError(
            "overall_discovery_speed_claim must be boolean"
        )
    if record.get("threshold_predeclared") is not True:
        raise RecordValidationError("acceleration threshold must be predeclared")
    if record.get("matched_conditions") is not True:
        raise RecordValidationError("acceleration arms must use matched conditions")
    overhead_included = record.get("overhead_included")
    if not isinstance(overhead_included, bool):
        raise RecordValidationError("overhead_included must be boolean")
    arms = _required_mapping(record, "arms")
    if set(arms) != {"baseline", "proposed"}:
        raise RecordValidationError(
            "arms must contain exactly baseline and proposed"
        )
    reached: dict[str, bool] = {}
    trials: dict[str, int | None] = {}
    elapsed_to_threshold: dict[str, float | None] = {}
    best: dict[str, float | None] = {}
    budgets: dict[str, int] = {}
    for name in ("baseline", "proposed"):
        arm = _required_mapping(arms, name)
        budget = _required_number(arm, "trial_budget", minimum=1, integer=True)
        assert isinstance(budget, int)
        budgets[name] = budget
        attempted = _required_number(
            arm, "trials_attempted", minimum=0, integer=True
        )
        if attempted > budget:
            raise RecordValidationError(
                f"{name} trials_attempted exceeds trial_budget"
            )
        endpoint = _required_mapping(arm, "trials_to_threshold")
        censored = endpoint.get("censored")
        if not isinstance(censored, bool):
            raise RecordValidationError(
                "trials_to_threshold.censored must be boolean"
            )
        value = endpoint.get("value")
        if censored:
            if (
                value is not None
                or endpoint.get("lower_bound_exclusive") != attempted
            ):
                raise RecordValidationError(
                    "censored endpoint must use the exact attempted-trial lower bound"
                )
            censoring_reason = endpoint.get("censoring_reason")
            if attempted < budget and censoring_reason != "wall-time-budget-exhausted":
                raise RecordValidationError(
                    "early censored endpoint requires a wall-time-budget-exhausted reason"
                )
            trials[name] = None
        else:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= attempted <= budget
            ):
                raise RecordValidationError(
                    "uncensored trials_to_threshold value is invalid"
                )
            if endpoint.get("lower_bound_exclusive") is not None:
                raise RecordValidationError(
                    "uncensored endpoint cannot have a lower bound"
                )
            trials[name] = value
        reached[name] = not censored
        endpoint_seconds = arm.get("elapsed_to_threshold_seconds")
        if censored:
            if endpoint_seconds is not None:
                raise RecordValidationError(
                    "censored arm elapsed_to_threshold_seconds must be null"
                )
            elapsed_to_threshold[name] = None
        else:
            if (
                isinstance(endpoint_seconds, bool)
                or not isinstance(endpoint_seconds, (int, float))
                or not math.isfinite(endpoint_seconds)
                or endpoint_seconds <= 0
            ):
                raise RecordValidationError(
                    "reached threshold requires positive elapsed_to_threshold_seconds"
                )
            elapsed_to_threshold[name] = float(endpoint_seconds)
        total_elapsed = float(
            _required_number(arm, "total_elapsed_seconds", minimum=0)
        )
        if endpoint_seconds is not None and endpoint_seconds > total_elapsed:
            raise RecordValidationError(
                "elapsed_to_threshold_seconds cannot exceed total_elapsed_seconds"
            )
        best_metric = arm.get("best_metric")
        if best_metric is None:
            best[name] = None
        else:
            best[name] = float(
                _required_number(arm, "best_metric", minimum=-math.inf)
            )
        _nullable_number(arm, "compute_seconds", minimum=0)
        _nullable_number(arm, "interventions", minimum=0, integer=True)
        _nullable_number(arm, "cost_usd", minimum=0)
        _nullable_number(arm, "token_usage", minimum=0, integer=True)
        availability = _required_mapping(arm, "measurement_availability")
        if set(availability) != {
            "workflow_overhead",
            "compute_seconds",
            "human_interventions",
            "cost_usd",
            "token_usage",
        } or any(
            status not in {"MEASURED", "UNAVAILABLE"}
            for status in availability.values()
        ):
            raise RecordValidationError(
                f"{name} measurement_availability is incomplete or invalid"
            )
        availability_fields = {
            "compute_seconds": "compute_seconds",
            "human_interventions": "interventions",
            "cost_usd": "cost_usd",
            "token_usage": "token_usage",
        }
        for availability_key, value_key in availability_fields.items():
            expected = "UNAVAILABLE" if arm[value_key] is None else "MEASURED"
            if availability[availability_key] != expected:
                raise RecordValidationError(
                    f"{name} {availability_key} availability contradicts its value"
                )
    if budgets["baseline"] != budgets["proposed"]:
        raise RecordValidationError("matched acceleration arms require the same trial budget")
    _required_str(record, "trial_count_rule")
    _required_str(record, "formula")
    outcome = _required_str(record, "outcome")
    trial_speedup = record.get("observed_trial_speedup")
    time_speedup = record.get("observed_time_speedup")
    lower_bound = record.get("trial_speedup_lower_bound")
    if all(reached.values()):
        baseline = trials["baseline"]
        proposed = trials["proposed"]
        assert baseline is not None and proposed is not None
        expected_trial = baseline / proposed
        baseline_time = elapsed_to_threshold["baseline"]
        proposed_time = elapsed_to_threshold["proposed"]
        assert baseline_time is not None and proposed_time is not None
        expected_time = baseline_time / proposed_time
        if (
            isinstance(trial_speedup, bool)
            or not isinstance(trial_speedup, (int, float))
            or not math.isclose(trial_speedup, expected_trial)
        ):
            raise RecordValidationError(
                "observed_trial_speedup does not match the predeclared formula"
            )
        if (
            isinstance(time_speedup, bool)
            or not isinstance(time_speedup, (int, float))
            or not math.isclose(time_speedup, expected_time)
        ):
            raise RecordValidationError(
                "observed_time_speedup does not match inclusive elapsed time"
            )
        if lower_bound is not None:
            raise RecordValidationError("uncensored arms cannot report a speedup lower bound")
    elif trial_speedup is not None or time_speedup is not None:
        raise RecordValidationError(
            "censored arms cannot report finite observed speedups"
        )
    elif reached["proposed"]:
        proposed = trials["proposed"]
        assert proposed is not None
        baseline_bound = arms["baseline"]["trials_to_threshold"][
            "lower_bound_exclusive"
        ]
        assert isinstance(baseline_bound, int)
        expected_lower_bound = baseline_bound / proposed
        if (
            isinstance(lower_bound, bool)
            or not isinstance(lower_bound, (int, float))
            or not math.isclose(lower_bound, expected_lower_bound)
        ):
            raise RecordValidationError("trial_speedup_lower_bound is not the exact censored bound")
    elif lower_bound is not None:
        raise RecordValidationError("no lower-bound speedup exists when proposed is censored")

    quality = _required_mapping(record, "quality_non_inferiority")
    margin = float(_required_number(quality, "margin", minimum=0))
    higher_is_better = quality.get("higher_is_better")
    if not isinstance(higher_is_better, bool):
        raise RecordValidationError("quality_non_inferiority.higher_is_better must be boolean")
    quality_estimable = best["baseline"] is not None and best["proposed"] is not None
    declared_estimable = quality.get("estimable")
    if declared_estimable is not None and declared_estimable is not quality_estimable:
        raise RecordValidationError(
            "quality_non_inferiority.estimable contradicts arm metrics"
        )
    if not quality_estimable and declared_estimable is not False:
        raise RecordValidationError(
            "quality_non_inferiority must explicitly mark missing metrics not estimable"
        )
    expected_quality = bool(
        quality_estimable
        and best["baseline"] is not None
        and best["proposed"] is not None
        and (
            best["proposed"] + margin >= best["baseline"]
            if higher_is_better
            else best["proposed"] - margin <= best["baseline"]
        )
    )
    if quality.get("passed") is not expected_quality:
        raise RecordValidationError("quality_non_inferiority.passed does not match arm metrics")

    expected_blockers: list[str] = []
    if not reached["baseline"]:
        expected_blockers.append("baseline_censored")
    if not reached["proposed"]:
        expected_blockers.append("proposed_censored")
    if not all(reached.values()):
        expected_blockers.append("time_speedup_not_estimable")
    else:
        assert isinstance(trial_speedup, (int, float))
        assert isinstance(time_speedup, (int, float))
        if trial_speedup <= 1:
            expected_blockers.append("trial_speedup_not_above_one")
        if time_speedup <= 1:
            expected_blockers.append("time_speedup_not_above_one")
    if not quality_estimable:
        expected_blockers.append("quality_non_inferiority_not_estimable")
    elif not expected_quality:
        expected_blockers.append("quality_non_inferiority_failed")
    if not overhead_included:
        expected_blockers.append("overhead_missing")
    compute_available = not any(
        arms[name]["measurement_availability"]["compute_seconds"]
        != "MEASURED"
        for name in ("baseline", "proposed")
    )
    if not compute_available:
        expected_blockers.append("compute_unavailable")
    blockers = _string_list(record, "claim_blockers")
    if blockers != sorted(set(expected_blockers)):
        raise RecordValidationError("claim_blockers do not exactly describe blocked claims")

    if outcome not in {
        "POSITIVE",
        "TRIAL_EFFICIENCY_ONLY",
        "NO_IMPROVEMENT",
        "NOT_ESTIMABLE",
        "LOWER_BOUND_ONLY",
    }:
        raise RecordValidationError("acceleration outcome is invalid")
    expected_outcome = (
        "NOT_ESTIMABLE"
        if not reached["proposed"]
        else "LOWER_BOUND_ONLY"
        if not reached["baseline"]
        else "NO_IMPROVEMENT"
        if not expected_quality or trial_speedup is None or trial_speedup <= 1
        else "POSITIVE"
        if (
            time_speedup is not None
            and time_speedup > 1
            and overhead_included
            and compute_available
        )
        else "TRIAL_EFFICIENCY_ONLY"
    )
    if outcome != expected_outcome:
        raise RecordValidationError(
            f"acceleration outcome must be {expected_outcome} for these endpoints"
        )
    if discovery_claim is not (outcome == "POSITIVE"):
        raise RecordValidationError(
            "overall_discovery_speed_claim contradicts the validated outcome"
        )
    _string_list(record, "threats_to_validity", allow_empty=False)
    scaling = _required_mapping(record, "scaling_analysis")
    for field in (
        "remaining_bottlenecks",
        "parallelizable_or_automatable",
        "evidence_still_needed",
        "conditions_for_approaching_10x",
        "boundaries",
    ):
        _string_list(scaling, field, allow_empty=False)
    scenarios = _required_mapping(scaling, "scenarios")
    if set(scenarios) != {"conservative", "expected", "optimistic"}:
        raise RecordValidationError(
            "scaling scenarios must be conservative, expected, and optimistic"
        )
    for name, scenario in scenarios.items():
        if not isinstance(scenario, Mapping):
            raise RecordValidationError(
                f"{name} scaling scenario must be an object"
            )
        _string_list(scenario, "assumptions", allow_empty=False)
        _required_number(scenario, "projected_speedup", minimum=0)
        _string_list(scenario, "boundaries", allow_empty=False)


def _validate_legacy_v1(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact pre-authority record profile for persisted reads only."""

    if not isinstance(record, Mapping):
        raise RecordValidationError("legacy stored record must be a JSON object")
    normalized = json.loads(canonical_json(record).decode("utf-8"))
    schema = _required_str(normalized, "schema")
    if schema not in LEGACY_V1_ID_FIELDS:
        raise RecordValidationError("record is not a supported legacy /v1 payload")
    if _looks_partially_upgraded(normalized):
        raise RecordValidationError(
            "partially upgraded /v1 record is neither current nor readable legacy"
        )
    _required_str(normalized, LEGACY_V1_ID_FIELDS[schema])

    if schema == "research-question/v1":
        for field in ("question", "measurable_outcome", "primary_metric"):
            _required_str(normalized, field)
        _string_list(normalized, "constraints")
        _string_list(normalized, "assumptions")
    elif schema == "evidence-package/v1":
        _required_str(normalized, "question_id")
        claims = normalized.get("claims")
        if not isinstance(claims, list):
            raise RecordValidationError("legacy claims must be a list")
        for claim in claims:
            if not isinstance(claim, Mapping):
                raise RecordValidationError("legacy evidence claim must be an object")
            for field in ("evidence_id", "claim", "source_type", "support"):
                _required_str(claim, field)
            citation = _required_mapping(claim, "citation")
            for field in ("title", "url", "authors_or_organization", "retrieved_at"):
                _required_str(citation, field)
        _string_list(normalized, "conflicts")
        _string_list(normalized, "coverage_gaps")
    elif schema == "hypothesis-portfolio/v1":
        hypotheses = normalized.get("hypotheses")
        if not isinstance(hypotheses, list) or not hypotheses:
            raise RecordValidationError("legacy hypotheses must be a non-empty list")
        for hypothesis in hypotheses:
            if not isinstance(hypothesis, Mapping):
                raise RecordValidationError("legacy hypothesis must be an object")
            for field in (
                "hypothesis_id", "statement", "prediction", "falsification_condition"
            ):
                _required_str(hypothesis, field)
            _string_list(hypothesis, "supporting_evidence_ids")
    elif schema == "experiment-candidates/v1":
        _required_str(normalized, "hypothesis_id")
        candidates = normalized.get("candidates")
        if not isinstance(candidates, list) or len(candidates) < 2:
            raise RecordValidationError("legacy record requires at least two candidates")
        identifiers: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                raise RecordValidationError("legacy candidate must be an object")
            identifier = _required_str(candidate, "experiment_id")
            if identifier in identifiers:
                raise RecordValidationError("legacy experiment IDs must be unique")
            identifiers.add(identifier)
            for field in ("method", "baseline", "success_threshold", "expected_learning"):
                _required_str(candidate, field)
            _required_mapping(candidate, "parameters")
            metrics = candidate.get("metrics")
            if not isinstance(metrics, list) or not metrics:
                raise RecordValidationError("legacy candidate metrics must be non-empty")
        selected = _required_str(normalized, "selected_experiment_id")
        if selected not in identifiers:
            raise RecordValidationError("legacy selected experiment is not a candidate")
        _required_str(normalized, "selection_rationale")
    elif schema == "safety-review/v1":
        verdict = _required_str(normalized, "verdict")
        if verdict not in {"APPROVAL_REQUIRED", "REVISE", "REJECT"}:
            raise RecordValidationError("legacy safety verdict is invalid")
        for field in ("risks", "required_controls", "prohibited_actions", "review_limitations"):
            _string_list(normalized, field)
        if verdict == "APPROVAL_REQUIRED":
            _required_str(normalized, "approval_question")
    elif schema == "human-approval/v1":
        for field in ("experiment_id", "experiment_digest", "approved_by", "approved_at"):
            _required_str(normalized, field)
        if normalized.get("approved") is not True:
            raise RecordValidationError("legacy approval must contain approved=true")
        if normalized.get("scope") != "execute-exact-experiment":
            raise RecordValidationError("legacy approval scope is invalid")
        _string_list(normalized, "constraints")
    elif schema == "experiment-result/v1":
        for field in (
            "experiment_id", "execution_source", "code_identity", "dataset_identity",
            "environment_identity", "started_at", "completed_at", "status"
        ):
            _required_str(normalized, field)
        _required_mapping(normalized, "metrics")
        _required_mapping(normalized, "parameters")
        if normalized["status"] not in {"PASS", "FAIL", "ERROR", "CANCELLED"}:
            raise RecordValidationError("legacy result status is invalid")
        _string_list(normalized, "artifact_refs")
        _string_list(normalized, "limitations")
    elif schema == "updated-decision/v1":
        for field in ("question_id", "hypothesis_id", "experiment_id", "rationale"):
            _required_str(normalized, field)
        if normalized.get("decision") not in {
            "support", "revise", "reject", "inconclusive"
        }:
            raise RecordValidationError("legacy decision is invalid")
        _string_list(normalized, "supporting_evidence_ids")
        _string_list(normalized, "remaining_uncertainty")
        _required_mapping(normalized, "next_experiment")

    claimed = normalized.get("record_digest")
    actual = record_digest(normalized)
    if claimed is not None and claimed != actual:
        raise RecordValidationError("legacy record_digest does not match its payload")
    normalized["record_digest"] = actual
    return normalized


def _looks_partially_upgraded(record: Mapping[str, Any]) -> bool:
    schema = record.get("schema")
    if "objective_confirmation_digest" in record:
        return True
    claims = record.get("claims")
    if schema == "evidence-package/v1" and isinstance(claims, list):
        if any(isinstance(claim, Mapping) and "claim_type" in claim for claim in claims):
            return True
    sentinels = {
        "evidence-package/v1": set(),
        "hypothesis-portfolio/v1": {"hypothesis_portfolio_id"},
        "experiment-candidates/v1": {
            "experiment_candidates_id", "primary_metric", "dataset_identity", "resource_bounds"
        },
        "safety-review/v1": {"experiment_digest"},
        "human-approval/v1": set(),
        "experiment-result/v1": {
            "experiment_digest", "approval_digest", "measurement_support"
        },
        "updated-decision/v1": {"result_digest", "interpreted_metrics"},
    }
    return any(field in record for field in sentinels.get(str(schema), set()))
