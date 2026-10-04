"""Validate an evidence package before closing its provider interval."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from omnigent_client.tools import tool

from ai_researcher.records import RecordValidationError, validate_record

_PACKAGE_FIELDS = {
    "schema",
    "evidence_package_id",
    "question_id",
    "objective_confirmation_digest",
    "claims",
    "conflicts",
    "coverage_gaps",
}
_CLAIM_FIELDS = {
    "evidence_id",
    "claim_type",
    "claim",
    "source_type",
    "citation",
    "support",
    "uncertainty",
}
_CITATION_FIELDS = {
    "title",
    "url",
    "authors_or_organization",
    "publisher_or_source",
    "retrieved_at",
    "license_or_access_note",
    "verification_state",
}
_SOURCE_TYPES = {
    "primary-paper",
    "official-dataset-registry",
    "official-documentation",
}


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ValueError(f"{label} fields are not canonical; missing={missing}, extra={extra}")


def _validate(package_json: str) -> dict[str, Any]:
    if not isinstance(package_json, str) or not package_json.strip():
        raise ValueError("package_json must be a non-empty JSON object string")
    try:
        package = json.loads(package_json)
    except json.JSONDecodeError as exc:
        raise ValueError("package_json is malformed JSON") from exc
    if not isinstance(package, dict):
        raise ValueError("package_json must decode to an object")
    _exact_fields(package, _PACKAGE_FIELDS, "package")
    claims = package.get("claims")
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValueError(f"claims[{index}] must be an object")
        _exact_fields(claim, _CLAIM_FIELDS, f"claims[{index}]")
        citation = claim.get("citation")
        if not isinstance(citation, dict):
            raise ValueError(f"claims[{index}].citation must be an object")
        _exact_fields(citation, _CITATION_FIELDS, f"claims[{index}].citation")
        if claim.get("source_type") not in _SOURCE_TYPES:
            raise ValueError(
                f"claims[{index}].source_type must be one of {sorted(_SOURCE_TYPES)}"
            )
    try:
        normalized = validate_record(package, "evidence-package/v1")
    except RecordValidationError as exc:
        raise ValueError(f"evidence package is invalid: {exc}") from exc
    return {
        "schema": "evidence-package-validation/v1",
        "valid": True,
        "evidence_package_id": normalized["evidence_package_id"],
        "claim_count": len(normalized["claims"]),
        "record_digest": normalized["record_digest"],
    }


@tool
def validate_evidence_package(package_json: str) -> dict[str, Any]:
    """Validate the exact canonical package JSON before the end marker.

    Args:
        package_json: Exact evidence-package/v1 object that will be returned.
    """

    return _validate(package_json)
