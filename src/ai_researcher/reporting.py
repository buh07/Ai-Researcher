"""Deterministic terminal and rubric views of a supplied research chain.

This module renders evidence; it does not create it.  In particular, missing
records remain visibly unavailable and are never inferred from configuration,
fixtures, or the presence of an expected artifact path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


_UNAVAILABLE = "[UNAVAILABLE] no supplied evidence"

_SECTIONS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "OBJECTIVE",
        ("objective", "objective_confirmation", "research_question"),
        ("question_id", "question_digest", "objective_confirmation_digest"),
    ),
    (
        "PARALLEL EVIDENCE",
        ("parallel_evidence", "evidence_packages", "evidence"),
        ("evidence_package_digests", "reconciliation_digest"),
    ),
    (
        "HYPOTHESIS",
        ("hypothesis", "hypothesis_portfolio"),
        ("hypothesis_portfolio_digest",),
    ),
    (
        "CANDIDATES",
        ("candidates", "experiment_candidates"),
        ("experiment_candidates_digest", "selected_experiment_id", "experiment_digest"),
    ),
    (
        "SAFETY",
        ("safety", "safety_review"),
        ("safety_review_digest",),
    ),
    (
        "APPROVAL",
        ("approval", "human_approval"),
        ("human_approval_digest",),
    ),
    (
        "RESULT",
        ("result", "experiment_result"),
        ("experiment_result_digest", "task_card_digest", "execution_snapshot"),
    ),
    (
        "DECISION",
        ("decision", "updated_decision"),
        ("updated_decision_digest",),
    ),
    (
        "ACCELERATION / 10X PATH",
        ("acceleration_10x_path", "acceleration", "acceleration_summary"),
        ("acceleration_summary_digest",),
    ),
)

_RUBRIC: tuple[tuple[str, str, int, tuple[str, ...]], ...] = (
    (
        "omnigent_orchestration",
        "Omnigent orchestration",
        30,
        (
            "agents/research-director/config.yaml",
            "agents/research-director/agents/",
            "artifacts/research-chain.json",
            "artifacts/learning-receipt.json",
        ),
    ),
    (
        "breakthrough_potential",
        "Breakthrough potential",
        25,
        ("README.md", "DEMO.md", "docs/LIMITATIONS.md"),
    ),
    (
        "discovery_acceleration_and_learning",
        "Discovery acceleration and learning",
        20,
        (
            "artifacts/acceleration-summary.json",
            "artifacts/learning-receipt.json",
            "DEMO.md",
        ),
    ),
    (
        "scientific_rigor",
        "Scientific rigor",
        15,
        (
            "docs/HANDOFF_CONTRACTS.md",
            "tests/",
            "artifacts/experiment-result.json",
        ),
    ),
    (
        "creativity_and_responsibility",
        "Creativity and responsibility",
        10,
        (
            "agents/research-director/",
            "artifacts/learning-receipt.json",
            "DEMO.md",
        ),
    ),
)

_RUBRIC_STATUSES = frozenset({"MET", "PARTIAL", "UNMET", "UNAVAILABLE"})
_SAFE_DIGEST = re.compile(r"^[A-Za-z0-9._:-]+$")

_SUPPORTED_RECORD_SCHEMAS = frozenset(
    {
        "research-question/v1",
        "objective-confirmation/v1",
        "feasibility-check/v1",
        "evidence-package/v1",
        "parallel-branch/v1",
        "branch-reconciliation/v1",
        "hypothesis-portfolio/v1",
        "experiment-candidates/v1",
        "safety-review/v1",
        "human-approval/v1",
        "experiment-result/v1",
        "updated-decision/v1",
        "acceleration-summary/v1",
    }
)

_SINGULAR_SECTION_SCHEMAS = {
    "HYPOTHESIS": "hypothesis-portfolio/v1",
    "CANDIDATES": "experiment-candidates/v1",
    "SAFETY": "safety-review/v1",
    "APPROVAL": "human-approval/v1",
    "RESULT": "experiment-result/v1",
    "DECISION": "updated-decision/v1",
    "ACCELERATION / 10X PATH": "acceleration-summary/v1",
}


def render_research_report(research_chain: Mapping[str, Any]) -> str:
    """Render a supplied chain or learning receipt in a fixed terminal order.

    Semantic records take precedence over receipt digests.  A caller may pass a
    learning receipt directly or under ``learning_receipt``.  Missing sections
    are marked unavailable rather than filled with demo claims.
    """

    supplied = _require_mapping(research_chain, "research_chain")
    _assert_json_value(supplied)
    chain_value = supplied.get("research_chain", supplied)
    chain = _require_mapping(chain_value, "research_chain.research_chain")
    receipt_value = supplied.get(
        "learning_receipt", chain.get("learning_receipt", chain)
    )
    receipt = receipt_value if isinstance(receipt_value, Mapping) else {}
    record_sections = _sections_from_records(chain)

    lines = ["AI RESEARCHER — DISCOVERY RECEIPT", "=" * 33]
    if "receipt_digest" in receipt:
        receipt_digest = receipt["receipt_digest"]
        if not isinstance(receipt_digest, str) or not _SAFE_DIGEST.fullmatch(
            receipt_digest
        ):
            raise ValueError("receipt_digest must be a non-empty safe identifier")
        lines.append(f"RECEIPT DIGEST: {receipt_digest}")
    for heading, aliases, receipt_fields in _SECTIONS:
        value = _first_present(supplied, aliases)
        if value is _MISSING and chain is not supplied:
            value = _first_present(chain, aliases)
        if value is _MISSING:
            value = record_sections.get(heading, _MISSING)
        if value is _MISSING:
            digest_view = {
                field: receipt[field]
                for field in receipt_fields
                if field in receipt and receipt[field] is not None
            }
            value = digest_view if digest_view else _MISSING
        lines.extend(("", heading, "-" * len(heading)))
        if value is _MISSING:
            lines.append(_UNAVAILABLE)
        else:
            lines.extend(_pretty_json_lines(value))
    return "\n".join(lines) + "\n"


def build_rubric_artifact_map(research_chain: Mapping[str, Any]) -> dict[str, Any]:
    """Build the challenge rubric map without inferring that evidence exists.

    The optional ``rubric_evidence`` object must explicitly give each claimed
    status.  ``expected_artifacts`` are an inventory, not proof; only the
    caller-supplied ``artifacts`` list appears as evidence.
    """

    chain = _require_mapping(research_chain, "research_chain")
    _assert_json_value(chain)
    evidence_value = chain.get("rubric_evidence", {})
    evidence = _require_mapping(evidence_value, "rubric_evidence")

    criteria: list[dict[str, Any]] = []
    for criterion_id, name, weight, expected in _RUBRIC:
        supplied_value = evidence.get(criterion_id, {})
        supplied = _require_mapping(
            supplied_value, f"rubric_evidence.{criterion_id}"
        )
        status = supplied.get("status", "UNAVAILABLE")
        if status not in _RUBRIC_STATUSES:
            raise ValueError(
                f"rubric status for {criterion_id!r} must be one of "
                f"{sorted(_RUBRIC_STATUSES)}"
            )
        artifacts = supplied.get("artifacts", [])
        if (
            not isinstance(artifacts, Sequence)
            or isinstance(artifacts, (str, bytes, bytearray))
            or any(not isinstance(item, str) or not item.strip() for item in artifacts)
        ):
            raise TypeError(f"rubric artifacts for {criterion_id!r} must be strings")
        criterion: dict[str, Any] = {
            "criterion_id": criterion_id,
            "name": name,
            "weight_percent": weight,
            "status": status,
            "evidence_artifacts": sorted(set(artifacts)),
            "expected_artifacts": list(expected),
        }
        if "notes" in supplied:
            notes = supplied["notes"]
            if not isinstance(notes, str):
                raise TypeError(f"rubric notes for {criterion_id!r} must be a string")
            criterion["notes"] = notes
        criteria.append(criterion)

    return {
        "schema": "rubric-artifact-map/v1",
        "claim_policy": (
            "Statuses and evidence_artifacts are caller-supplied; expected_artifacts "
            "are inventory targets and do not prove completion."
        ),
        "criteria": criteria,
    }


def rubric_artifact_json(research_chain: Mapping[str, Any]) -> str:
    """Return the rubric map as stable, finite, newline-terminated JSON."""

    return (
        json.dumps(
            build_rubric_artifact_map(research_chain),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


class _Missing:
    pass


_MISSING = _Missing()


def _first_present(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return _MISSING


def _sections_from_records(chain: Mapping[str, Any]) -> dict[str, Any]:
    if "records" not in chain:
        return {}
    records_value = chain["records"]
    if (
        not isinstance(records_value, Sequence)
        or isinstance(records_value, (str, bytes, bytearray))
    ):
        raise TypeError("research_chain.records must be a list of record mappings")

    by_schema: dict[str, list[Mapping[str, Any]]] = {}
    for index, record_value in enumerate(records_value):
        record = _require_mapping(record_value, f"research_chain.records[{index}]")
        schema = record.get("schema")
        if not isinstance(schema, str) or not schema.strip():
            raise ValueError(f"research_chain.records[{index}].schema is required")
        if schema not in _SUPPORTED_RECORD_SCHEMAS:
            raise ValueError(f"unsupported research-chain record schema: {schema!r}")
        by_schema.setdefault(schema, []).append(record)
    for records in by_schema.values():
        records.sort(key=_record_sort_key)

    question = _single_record(by_schema, "research-question/v1")
    objective = _single_record(by_schema, "objective-confirmation/v1")
    feasibility = by_schema.get("feasibility-check/v1", [])
    objective_view: dict[str, Any] = {}
    if question is not None:
        objective_view["research_question"] = question
    if objective is not None:
        objective_view["objective_confirmation"] = objective
    if feasibility:
        objective_view["feasibility_checks"] = feasibility

    evidence_view: dict[str, Any] = {}
    for key, schema in (
        ("evidence_packages", "evidence-package/v1"),
        ("parallel_branches", "parallel-branch/v1"),
        ("reconciliations", "branch-reconciliation/v1"),
    ):
        records = by_schema.get(schema, [])
        if records:
            evidence_view[key] = records

    sections: dict[str, Any] = {}
    if objective_view:
        sections["OBJECTIVE"] = objective_view
    if evidence_view:
        sections["PARALLEL EVIDENCE"] = evidence_view
    for heading, schema in _SINGULAR_SECTION_SCHEMAS.items():
        record = _single_record(by_schema, schema)
        if record is not None:
            sections[heading] = record
    return sections


def _single_record(
    by_schema: Mapping[str, list[Mapping[str, Any]]], schema: str
) -> Mapping[str, Any] | None:
    records = by_schema.get(schema, [])
    if len(records) > 1:
        raise ValueError(f"conflicting singular records for {schema}")
    return records[0] if records else None


def _record_sort_key(record: Mapping[str, Any]) -> tuple[str, str]:
    digest = record.get("record_digest")
    digest_key = digest if isinstance(digest, str) else ""
    canonical = json.dumps(
        record,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return digest_key, canonical


def _pretty_json_lines(value: Any) -> list[str]:
    rendered = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return rendered.splitlines()


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _assert_json_value(value: Any) -> None:
    try:
        json.dumps(value, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("research_chain must contain finite JSON values") from exc
