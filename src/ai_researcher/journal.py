"""Immutable SQLite journal and deterministic scientific-chain projections."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import sqlite3
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .records import (
    ID_FIELDS,
    RecordValidationError,
    canonical_json,
    decision_timing_digest,
    experiment_digest,
    selected_experiment,
    stored_record_uses_legacy_contract,
    validate_record,
    validate_stored_record,
)


class JournalConflictError(RuntimeError):
    """Journal provenance or an immutable identity is missing or inconsistent."""


_PROVIDER_ATTESTATION_KEY = secrets.token_bytes(32)
_PROVIDER_SEARCH_TOOL_NAMES = frozenset({"web_search", "search_public_web"})


@dataclass(frozen=True, slots=True)
class VerifiedProviderInvocation:
    """Process-authenticated projection of an independently exported Omnigent session.

    Callers cannot construct a usable instance from self-authored JSON: the journal
    verifies the private process tag before accepting it. The public research tool
    obtains export bytes itself from ``omnigent session export`` and never accepts a
    caller-selected receipt path.
    """

    payload: dict[str, Any]
    _authentication_tag: str


def _verify_omnigent_session_export(
    export_bytes: bytes,
    *,
    expected_branch_id: str,
    expected_session_id: str,
    expected_agent_id: str,
) -> VerifiedProviderInvocation:
    """Validate an Omnigent-owned export and issue a process-authenticated receipt.

    This function is also the hermetic verifier seam used by tests. Production code
    supplies bytes fetched by the controlled Omnigent export command, never bytes
    supplied through an agent-call argument.
    """

    if not isinstance(export_bytes, bytes) or not export_bytes:
        raise JournalConflictError("Omnigent session export must be nonempty bytes")
    records: list[dict[str, Any]] = []
    try:
        for line in export_bytes.decode("utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("record is not an object")
                records.append(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise JournalConflictError("Omnigent session export is malformed") from exc
    if not records or records[0].get("record_type") != "session_meta":
        raise JournalConflictError("Omnigent export lacks a leading session_meta record")
    if any(row.get("record_type") == "session_meta" for row in records[1:]):
        raise JournalConflictError("Omnigent export contains multiple session_meta records")
    meta = records[0]
    branch_id = _nonempty(expected_branch_id, "expected_branch_id")
    session_id = _nonempty(expected_session_id, "expected_session_id")
    agent_id = _nonempty(expected_agent_id, "expected_agent_id")
    if meta.get("id") != session_id or meta.get("agent_name") != agent_id:
        raise JournalConflictError(
            "Omnigent session identity does not match the dispatched branch"
        )
    if meta.get("status") != "idle":
        raise JournalConflictError(
            "Omnigent provider session must be idle after completed execution"
        )
    if not isinstance(meta.get("parent_session_id"), str) or not meta["parent_session_id"]:
        raise JournalConflictError("parallel evidence requires an Omnigent child session")
    if meta.get("sub_agent_name") != "evidence-researcher":
        raise JournalConflictError(
            "parallel evidence receipt must identify the evidence-researcher sub-agent"
        )
    if meta["parent_session_id"] == session_id:
        raise JournalConflictError("provider child session cannot be its own parent")
    if not isinstance(meta.get("harness"), str) or not meta["harness"]:
        raise JournalConflictError("Omnigent export lacks provider harness identity")
    if not isinstance(meta.get("llm_model"), str) or not meta["llm_model"]:
        raise JournalConflictError("Omnigent export lacks provider model identity")
    tokens = meta.get("last_total_tokens")
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
        raise JournalConflictError(
            "Omnigent export lacks positive provider token usage evidence"
        )
    items = [row for row in records[1:] if row.get("record_type") == "item"]
    indexed_items = list(enumerate(items))
    start_calls = [
        (index, row)
        for index, row in indexed_items
        if row.get("type") == "function_call"
        and row.get("status") == "completed"
        and row.get("name") == "mark_provider_execution_start"
    ]
    if len(start_calls) != 1:
        raise JournalConflictError(
            "Omnigent export requires exactly one completed provider execution start marker"
        )
    start_call_index, start_call = start_calls[0]
    if _json_string_object(start_call.get("arguments"), "start marker arguments") != {
        "branch_id": branch_id
    }:
        raise JournalConflictError("provider execution start marker does not bind the branch")
    response_id = _nonempty(str(start_call.get("response_id", "")), "response_id")
    start_call_id = _nonempty(str(start_call.get("call_id", "")), "start call_id")
    if not isinstance(start_call.get("model"), str) or not start_call["model"]:
        raise JournalConflictError("provider execution start marker lacks model identity")

    start_results = [
        (index, row)
        for index, row in indexed_items
        if row.get("type") == "function_call_output"
        and row.get("status") == "completed"
        and row.get("call_id") == start_call_id
        and row.get("response_id") == response_id
    ]
    if len(start_results) != 1:
        raise JournalConflictError(
            "Omnigent export requires the completed provider execution start result"
        )
    start_result_index, start_result = start_results[0]
    start_output = _json_string_object(start_result.get("output"), "start marker output")
    start_marker_id = _nonempty(str(start_output.get("marker_id", "")), "marker_id")
    if start_output != {
        "schema": "provider-execution-marker/v1",
        "phase": "START",
        "branch_id": branch_id,
        "marker_id": start_marker_id,
    }:
        raise JournalConflictError("provider execution start result is malformed")

    end_calls = [
        (index, row)
        for index, row in indexed_items
        if row.get("type") == "function_call"
        and row.get("status") == "completed"
        and row.get("name") == "mark_provider_execution_end"
    ]
    if len(end_calls) != 1:
        raise JournalConflictError(
            "Omnigent export requires exactly one completed provider execution end marker"
        )
    end_call_index, end_call = end_calls[0]
    if _json_string_object(end_call.get("arguments"), "end marker arguments") != {
        "branch_id": branch_id,
        "start_marker_id": start_marker_id,
    }:
        raise JournalConflictError("provider execution end marker does not bind the start marker")
    end_call_id = _nonempty(str(end_call.get("call_id", "")), "end call_id")
    if (
        end_call_id == start_call_id
        or end_call.get("response_id") != response_id
        or not isinstance(end_call.get("model"), str)
        or not end_call["model"]
    ):
        raise JournalConflictError("provider execution markers have mismatched identities")
    end_results = [
        (index, row)
        for index, row in indexed_items
        if row.get("type") == "function_call_output"
        and row.get("status") == "completed"
        and row.get("call_id") == end_call_id
        and row.get("response_id") == response_id
    ]
    if len(end_results) != 1:
        raise JournalConflictError(
            "Omnigent export requires the completed provider execution end result"
        )
    end_result_index, end_result = end_results[0]
    end_output = _json_string_object(end_result.get("output"), "end marker output")
    end_marker_id = _nonempty(str(end_output.get("marker_id", "")), "marker_id")
    if end_output != {
        "schema": "provider-execution-marker/v1",
        "phase": "END",
        "branch_id": branch_id,
        "marker_id": end_marker_id,
        "start_marker_id": start_marker_id,
    }:
        raise JournalConflictError("provider execution end result is malformed")

    if not (
        start_call_index < start_result_index < end_call_index < end_result_index
    ):
        raise JournalConflictError("provider execution marker items are out of order")
    started = _finite_item_timestamp(start_result, "start marker result")
    end_call_time = _finite_item_timestamp(end_call, "end marker call")
    completed = _finite_item_timestamp(end_result, "end marker result")
    if completed <= started:
        raise JournalConflictError(
            "provider execution marker interval must be positive and ordered"
        )

    marker_tool_names = {
        "mark_provider_execution_start",
        "mark_provider_execution_end",
    }
    substantive_calls = [
        (index, row)
        for index, row in indexed_items
        if row.get("type") == "function_call"
        and row.get("status") == "completed"
        and row.get("response_id") == response_id
        and row.get("name") not in marker_tool_names
    ]
    if not any(
        row.get("name") in _PROVIDER_SEARCH_TOOL_NAMES
        for _, row in substantive_calls
    ):
        raise JournalConflictError(
            "provider execution interval requires a completed substantive provider tool call"
        )
    for call_index, call in substantive_calls:
        if not start_result_index < call_index < end_call_index:
            raise JournalConflictError(
                "substantive provider tool call occurred outside execution markers"
            )
        call_id = _nonempty(str(call.get("call_id", "")), "substantive call_id")
        results = [
            (index, row)
            for index, row in indexed_items
            if row.get("type") == "function_call_output"
            and row.get("status") == "completed"
            and row.get("call_id") == call_id
            and row.get("response_id") == response_id
        ]
        if len(results) != 1:
            raise JournalConflictError(
                "substantive provider tool call lacks one completed result"
            )
        result_index, result = results[0]
        if not call_index < result_index < end_call_index:
            raise JournalConflictError(
                "substantive provider tool result occurred outside execution markers"
            )
        call_time = _finite_item_timestamp(call, "substantive tool call")
        result_time = _finite_item_timestamp(result, "substantive tool result")
        if not started <= call_time <= result_time <= end_call_time:
            raise JournalConflictError(
                "substantive provider tool timestamps fall outside execution markers"
            )

    branch_requests = [
        row
        for row in items
        if row.get("type") == "message"
        and row.get("role") == "user"
        and row.get("status") == "completed"
        and row.get("response_id") == response_id
        and _contains_exact_branch_marker(row, branch_id)
    ]
    matching_responses = [
        row
        for row in items
        if row.get("type") == "message"
        and row.get("role") == "assistant"
        and row.get("status") == "completed"
        and row.get("response_id") == response_id
    ]
    if len(branch_requests) != 1 or not matching_responses:
        raise JournalConflictError(
            "provider execution markers must belong to one completed branch response"
        )
    request_time = _finite_item_timestamp(branch_requests[0], "branch request")
    response_times = [
        _finite_item_timestamp(row, "assistant response") for row in matching_responses
    ]
    if request_time > started or max(response_times) < completed:
        raise JournalConflictError(
            "provider execution markers fall outside their completed response"
        )
    export_digest = hashlib.sha256(export_bytes).hexdigest()
    receipt: dict[str, Any] = {
        "schema": "omnigent-provider-invocation-receipt/v1",
        "issuer": "omnigent-session-export",
        "branch_id": branch_id,
        "provider_session_id": session_id,
        "agent_id": agent_id,
        "agent_durable_id": _nonempty(str(meta.get("agent_id", "")), "agent_id"),
        "sub_agent_name": _nonempty(
            str(meta.get("sub_agent_name", "")), "sub_agent_name"
        ),
        "parent_session_id": meta["parent_session_id"],
        "root_conversation_id": _nonempty(
            str(meta.get("root_conversation_id", "")), "root_conversation_id"
        ),
        "harness": meta["harness"],
        "model": meta["llm_model"],
        "status": "COMPLETED",
        "interval_source": "provider-execution-marker-results/v1",
        "started_at": datetime.fromtimestamp(
            started, timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.fromtimestamp(
            completed, timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "last_total_tokens": tokens,
        "provider_response_id": response_id,
        "execution_start_call_id": start_call_id,
        "execution_end_call_id": end_call_id,
        "execution_start_marker_id": start_marker_id,
        "execution_end_marker_id": end_marker_id,
        "substantive_tool_calls": [
            {"call_id": str(row["call_id"]), "name": str(row["name"])}
            for _, row in substantive_calls
        ],
        "completed_response_ids": [response_id],
        "export_item_count": len(items),
        "export_digest": export_digest,
    }
    receipt["receipt_digest"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    tag = hmac.new(
        _PROVIDER_ATTESTATION_KEY, canonical_json(receipt), hashlib.sha256
    ).hexdigest()
    return VerifiedProviderInvocation(receipt, tag)


def _json_string_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise JournalConflictError(f"Omnigent {label} must be a JSON object string")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise JournalConflictError(f"Omnigent {label} is malformed") from exc
    if not isinstance(decoded, dict):
        raise JournalConflictError(f"Omnigent {label} must decode to an object")
    return decoded


def _finite_item_timestamp(item: Mapping[str, Any], label: str) -> float:
    value = item.get("created_at")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise JournalConflictError(f"Omnigent {label} lacks a finite provider timestamp")
    return float(value)


def _contains_exact_branch_marker(item: Mapping[str, Any], branch_id: str) -> bool:
    """Match a branch marker without accepting substring-collision identities."""

    text = canonical_json(item).decode("utf-8")
    start = 0
    while True:
        index = text.find(branch_id, start)
        if index < 0:
            return False
        before = text[index - 1] if index else ""
        after_index = index + len(branch_id)
        after = text[after_index] if after_index < len(text) else ""
        identifier_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        if before not in identifier_characters and after not in identifier_characters:
            return True
        start = index + 1


def _authenticated_provider_invocation(
    value: VerifiedProviderInvocation | None,
) -> dict[str, Any]:
    if not isinstance(value, VerifiedProviderInvocation):
        raise JournalConflictError(
            "parallel branch requires a verified Omnigent provider invocation receipt"
        )
    expected = hmac.new(
        _PROVIDER_ATTESTATION_KEY, canonical_json(value.payload), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(value._authentication_tag, expected):
        raise JournalConflictError("provider invocation receipt authentication failed")
    receipt = json.loads(canonical_json(value.payload).decode("utf-8"))
    claimed = receipt.pop("receipt_digest", None)
    actual = hashlib.sha256(canonical_json(receipt)).hexdigest()
    if claimed != actual:
        raise JournalConflictError("provider invocation receipt digest is invalid")
    receipt["receipt_digest"] = actual
    return receipt


def _validate_stored_provider_receipt(
    branch: Mapping[str, Any], row: Mapping[str, Any]
) -> tuple[str, str]:
    """Revalidate one persisted provider receipt after process restart."""

    row = dict(row)
    started_at = row.get("invocation_started_at")
    completed_at = row.get("invocation_completed_at")
    if not isinstance(started_at, str) or not isinstance(completed_at, str):
        raise JournalConflictError("parallel branch lacks trusted runtime timing")
    try:
        provider_receipt = json.loads(str(row.get("provider_receipt_json")))
    except (TypeError, json.JSONDecodeError) as exc:
        raise JournalConflictError(
            "parallel branch lacks its immutable provider receipt"
        ) from exc
    if not isinstance(provider_receipt, dict):
        raise JournalConflictError(
            "parallel branch lacks its immutable provider receipt"
        )
    receipt_without_digest = {
        key: value for key, value in provider_receipt.items() if key != "receipt_digest"
    }
    receipt_digest = hashlib.sha256(canonical_json(receipt_without_digest)).hexdigest()
    response_id = provider_receipt.get("provider_response_id")
    start_call_id = provider_receipt.get("execution_start_call_id")
    end_call_id = provider_receipt.get("execution_end_call_id")
    substantive_calls = provider_receipt.get("substantive_tool_calls")
    if (
        provider_receipt.get("schema")
        != "omnigent-provider-invocation-receipt/v1"
        or provider_receipt.get("issuer") != "omnigent-session-export"
        or provider_receipt.get("status") != "COMPLETED"
        or provider_receipt.get("interval_source")
        != "provider-execution-marker-results/v1"
        or not isinstance(response_id, str)
        or not response_id
        or provider_receipt.get("completed_response_ids") != [response_id]
        or not isinstance(start_call_id, str)
        or not start_call_id
        or not isinstance(end_call_id, str)
        or not end_call_id
        or start_call_id == end_call_id
        or not isinstance(provider_receipt.get("execution_start_marker_id"), str)
        or not provider_receipt["execution_start_marker_id"]
        or not isinstance(provider_receipt.get("execution_end_marker_id"), str)
        or not provider_receipt["execution_end_marker_id"]
        or not isinstance(substantive_calls, list)
        or not substantive_calls
        or not any(
            isinstance(item, dict)
            and item.get("name") in _PROVIDER_SEARCH_TOOL_NAMES
            and isinstance(item.get("call_id"), str)
            and item["call_id"]
            for item in substantive_calls
        )
        or provider_receipt.get("branch_id") != branch.get("branch_id")
        or provider_receipt.get("provider_session_id")
        != branch.get("provider_session_id")
        or provider_receipt.get("agent_id") != branch.get("producer_agent_id")
        or provider_receipt.get("started_at") != started_at
        or provider_receipt.get("completed_at") != completed_at
        or receipt_digest != provider_receipt.get("receipt_digest")
        or receipt_digest != branch.get("provider_receipt_digest")
        or receipt_digest != row.get("provider_receipt_digest")
        or row.get("provider_session_id") != branch.get("provider_session_id")
        or row.get("producer_session_id") != branch.get("producer_session_id")
        or row.get("producer_agent_id") != branch.get("producer_agent_id")
    ):
        raise JournalConflictError(
            "parallel branch provider receipt is missing, damaged, or mismatched"
        )
    return started_at, completed_at


class ResearchJournal:
    """Append-only records plus one explicitly mutable execution projection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def initialize(self) -> None:
        """Create or additively migrate the journal without rewriting old rows."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    record_digest TEXT PRIMARY KEY,
                    schema_name TEXT NOT NULL,
                    primary_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    producer_session_id TEXT,
                    producer_agent_id TEXT,
                    invocation_id TEXT,
                    invocation_status TEXT,
                    provider_session_id TEXT,
                    provider_receipt_digest TEXT,
                    provider_receipt_json TEXT,
                    invocation_started_at TEXT,
                    invocation_completed_at TEXT,
                    UNIQUE(schema_name, primary_id)
                );
                CREATE TABLE IF NOT EXISTS record_links (
                    parent_digest TEXT NOT NULL REFERENCES records(record_digest),
                    child_digest TEXT NOT NULL REFERENCES records(record_digest),
                    relation TEXT NOT NULL,
                    PRIMARY KEY(parent_digest, child_digest, relation)
                );
                CREATE TABLE IF NOT EXISTS experiment_bindings (
                    experiment_id TEXT PRIMARY KEY,
                    experiment_digest TEXT NOT NULL,
                    approval_digest TEXT NOT NULL REFERENCES records(record_digest),
                    objective_confirmation_digest TEXT,
                    task_card_digest TEXT,
                    task_card_path TEXT NOT NULL,
                    lane_id TEXT,
                    run_id TEXT,
                    acceptance_decided_at TEXT,
                    acceptance_digest TEXT,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(connection, "records", "producer_session_id", "TEXT")
            self._ensure_column(connection, "records", "producer_agent_id", "TEXT")
            self._ensure_column(connection, "records", "invocation_id", "TEXT")
            self._ensure_column(connection, "records", "invocation_status", "TEXT")
            self._ensure_column(connection, "records", "provider_session_id", "TEXT")
            self._ensure_column(
                connection, "records", "provider_receipt_digest", "TEXT"
            )
            self._ensure_column(connection, "records", "provider_receipt_json", "TEXT")
            self._ensure_column(connection, "records", "invocation_started_at", "TEXT")
            self._ensure_column(connection, "records", "invocation_completed_at", "TEXT")
            self._ensure_column(
                connection, "experiment_bindings", "objective_confirmation_digest", "TEXT"
            )
            self._ensure_column(
                connection, "experiment_bindings", "task_card_digest", "TEXT"
            )
            self._ensure_column(
                connection, "experiment_bindings", "acceptance_decided_at", "TEXT"
            )
            self._ensure_column(
                connection, "experiment_bindings", "acceptance_digest", "TEXT"
            )

    def append(
        self,
        record: Mapping[str, Any],
        *,
        source: str,
        links: Iterable[tuple[str, str]] = (),
        producer_session_id: str | None = None,
        producer_agent_id: str | None = None,
        invocation_id: str | None = None,
        invocation_status: str | None = None,
        provider_invocation: VerifiedProviderInvocation | None = None,
        invocation_started_at: str | None = None,
        invocation_completed_at: str | None = None,
    ) -> dict[str, Any]:
        """Atomically validate and append a record and all incoming semantic links."""

        if record.get("schema") == "updated-decision/v1":
            record = self._attach_decision_timing(record)
        normalized = validate_record(record)
        digest = normalized["record_digest"]
        schema = normalized["schema"]
        identifier = str(normalized[ID_FIELDS[schema]])
        payload = canonical_json(normalized).decode("utf-8")
        source = _nonempty(source, "source")
        session_id = _nonempty(
            producer_session_id or f"unspecified:{source}", "producer_session_id"
        )
        agent_id = _nonempty(
            producer_agent_id or _agent_from_source(source), "producer_agent_id"
        )
        trusted_start, trusted_end = _trusted_interval(
            invocation_started_at, invocation_completed_at,
            required=schema == "parallel-branch/v1",
        )
        trusted_invocation_id: str | None = None
        trusted_invocation_status: str | None = None
        provider_session_id: str | None = None
        provider_receipt_digest: str | None = None
        provider_receipt_json: str | None = None
        if schema == "parallel-branch/v1":
            receipt = _authenticated_provider_invocation(provider_invocation)
            trusted_invocation_id = _nonempty(invocation_id, "invocation_id")
            trusted_invocation_status = _nonempty(
                invocation_status, "invocation_status"
            )
            if trusted_invocation_status != "COMPLETED":
                raise JournalConflictError(
                    "trusted invocation lifecycle must be COMPLETED"
                )
            if (
                normalized["producer_session_id"] != session_id
                or normalized["producer_agent_id"] != agent_id
                or normalized["invocation_id"] != trusted_invocation_id
                or normalized["invocation_status"] != trusted_invocation_status
                or normalized["branch_id"] != receipt["branch_id"]
                or normalized["provider_session_id"]
                != receipt["provider_session_id"]
                or normalized["provider_receipt_digest"]
                != receipt["receipt_digest"]
                or session_id != receipt["provider_session_id"]
                or agent_id != receipt["agent_id"]
                or trusted_invocation_id != receipt["provider_session_id"]
                or trusted_start != receipt["started_at"]
                or trusted_end != receipt["completed_at"]
            ):
                raise JournalConflictError(
                    "parallel branch identity, interval, and lifecycle must match "
                    "the verified Omnigent provider receipt"
                )
            provider_session_id = receipt["provider_session_id"]
            provider_receipt_digest = receipt["receipt_digest"]
            provider_receipt_json = canonical_json(receipt).decode("utf-8")
        elif (
            invocation_id is not None
            or invocation_status is not None
            or provider_invocation is not None
        ):
            raise JournalConflictError(
                "trusted invocation lifecycle is valid only for parallel branches"
            )
        link_values = tuple((_digest(parent), _nonempty(relation, "relation")) for parent, relation in links)
        if len(link_values) != len(set(link_values)):
            raise JournalConflictError("duplicate provenance link in one append")

        self.initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT record_digest FROM records WHERE schema_name=? AND primary_id=?",
                (schema, identifier),
            ).fetchone()
            if existing is not None and existing[0] != digest:
                raise JournalConflictError(
                    f"{schema} identity {identifier!r} already has different content"
                )
            for parent_digest, _ in link_values:
                if self._payload(connection, parent_digest) is None:
                    raise JournalConflictError(
                        f"provenance parent {parent_digest!r} does not exist"
                    )
            if existing is not None:
                for parent_digest, relation in link_values:
                    linked = connection.execute(
                        """SELECT 1 FROM record_links
                           WHERE parent_digest=? AND child_digest=? AND relation=?""",
                        (parent_digest, digest, relation),
                    ).fetchone()
                    if linked is None:
                        raise JournalConflictError(
                            "an immutable record replay cannot add new provenance"
                        )
            else:
                self._validate_cross_record(connection, normalized, link_values)
                connection.execute(
                    """
                    INSERT INTO records
                        (record_digest, schema_name, primary_id, payload_json, source,
                         recorded_at, producer_session_id, producer_agent_id,
                         invocation_id, invocation_status,
                         provider_session_id, provider_receipt_digest,
                         provider_receipt_json,
                         invocation_started_at, invocation_completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        digest,
                        schema,
                        identifier,
                        payload,
                        source,
                        _utc_now(),
                        session_id,
                        agent_id,
                        trusted_invocation_id,
                        trusted_invocation_status,
                        provider_session_id,
                        provider_receipt_digest,
                        provider_receipt_json,
                        trusted_start,
                        trusted_end,
                    ),
                )
                for parent_digest, relation in link_values:
                    connection.execute(
                        "INSERT INTO record_links VALUES (?, ?, ?)",
                        (parent_digest, digest, relation),
                    )
        return normalized

    def _attach_decision_timing(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Add trusted post-acceptance timing to an analyst's decision payload.

        The analyst owns interpretation, not timestamps.  Harness acceptance is
        persisted when its exact reviewed result is ingested; this journal
        boundary supplies the completion time.  Callers therefore cannot label
        a self-authored digest as measured timing.
        """

        if "decision_timing" in record or "decision_timing_source_digest" in record:
            raise JournalConflictError(
                "decision timing is journal-authored and must not be caller supplied"
            )
        experiment_id = _nonempty(
            str(record.get("experiment_id", "")), "experiment_id"
        )
        run_id = _nonempty(str(record.get("run_id", "")), "run_id")
        result_digest = _digest(str(record.get("result_digest", "")))
        self.initialize()
        with self._connect() as connection:
            binding = connection.execute(
                """
                SELECT run_id, status, acceptance_decided_at, acceptance_digest
                FROM experiment_bindings WHERE experiment_id=?
                """,
                (experiment_id,),
            ).fetchone()
        if (
            binding is None
            or binding[0] != run_id
            or binding[1] not in {"COMPLETED", "FAILED", "ERROR", "CANCELLED"}
            or not binding[2]
            or not binding[3]
        ):
            raise JournalConflictError(
                "updated decision requires an accepted, ingested Harness result"
            )
        accepted_at = str(binding[2])
        acceptance_digest = _digest(str(binding[3]))
        try:
            accepted = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise JournalConflictError(
                "stored Harness acceptance timestamp is invalid"
            ) from exc
        if accepted.tzinfo is None:
            raise JournalConflictError(
                "stored Harness acceptance timestamp lacks a timezone"
            )
        completed_at = _utc_now()
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if completed < accepted:
            raise JournalConflictError(
                "decision completion cannot precede Harness result acceptance"
            )
        timing = {
            "schema": "decision-timing-measurement/v1",
            "result_digest": result_digest,
            "run_id": run_id,
            "harness_acceptance_digest": acceptance_digest,
            "result_accepted_at": accepted_at,
            "decision_completed_at": completed_at,
            "latency_seconds": (completed - accepted).total_seconds(),
        }
        enriched = dict(record)
        enriched["decision_timing"] = timing
        enriched["decision_timing_source_digest"] = decision_timing_digest(timing)
        return enriched

    def get(self, digest: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as connection:
            payload = self._payload(connection, digest)
        return validate_stored_record(payload) if payload is not None else None

    def find(self, schema: str, primary_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM records WHERE schema_name=? AND primary_id=?",
                (schema, primary_id),
            ).fetchone()
        return validate_stored_record(json.loads(row[0])) if row is not None else None

    def record_metadata(self, digest: str) -> dict[str, Any] | None:
        """Return journal provenance separately from the immutable record payload."""

        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT record_digest, schema_name, primary_id, source, recorded_at,
                       producer_session_id, producer_agent_id,
                       invocation_id, invocation_status,
                       provider_session_id, provider_receipt_digest,
                       invocation_started_at, invocation_completed_at
                FROM records WHERE record_digest=?
                """,
                (digest,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_questions(self) -> list[dict[str, Any]]:
        """List questions in stable journal insertion order, never by 'latest'."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM records
                WHERE schema_name='research-question/v1'
                ORDER BY rowid ASC
                """
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def reconstruct_chain(self, question_id: str) -> dict[str, Any]:
        """Return every descendant record, semantic edge, and producer attribution."""

        self.initialize()
        with self._connect() as connection:
            root_row = connection.execute(
                """
                SELECT record_digest FROM records
                WHERE schema_name='research-question/v1' AND primary_id=?
                """,
                (question_id,),
            ).fetchone()
            if root_row is None:
                raise JournalConflictError(f"unknown research question {question_id!r}")
            digests, edges = self._descendants(connection, root_row[0])
            placeholders = ",".join("?" for _ in digests)
            rows = connection.execute(
                f"""
                SELECT record_digest, payload_json, source, recorded_at,
                       producer_session_id, producer_agent_id,
                       invocation_id, invocation_status,
                       provider_session_id, provider_receipt_digest,
                       provider_receipt_json,
                       invocation_started_at, invocation_completed_at
                FROM records WHERE record_digest IN ({placeholders})
                """,
                tuple(digests),
            ).fetchall()
        payloads = {
            row["record_digest"]: validate_stored_record(json.loads(row["payload_json"]))
            for row in rows
        }
        for row in rows:
            payload = payloads[row["record_digest"]]
            if (
                payload.get("schema") == "parallel-branch/v1"
                and not stored_record_uses_legacy_contract(payload)
            ):
                _validate_stored_provider_receipt(payload, row)
        legacy_digests = sorted(
            digest
            for digest, payload in payloads.items()
            if stored_record_uses_legacy_contract(payload)
        )
        records = [payloads[digest] for digest in sorted(payloads)]
        provenance = [
            {
                "record_digest": row["record_digest"],
                "source": row["source"],
                "recorded_at": row["recorded_at"],
                "producer_session_id": row["producer_session_id"],
                "producer_agent_id": row["producer_agent_id"],
                "invocation_id": row["invocation_id"],
                "invocation_status": row["invocation_status"],
                "provider_session_id": row["provider_session_id"],
                "provider_receipt_digest": row["provider_receipt_digest"],
                "invocation_started_at": row["invocation_started_at"],
                "invocation_completed_at": row["invocation_completed_at"],
            }
            for row in sorted(rows, key=lambda item: item["record_digest"])
        ]
        return {
            "question_id": question_id,
            "records": records,
            "links": edges,
            "provenance": provenance,
            "legacy_record_digests": legacy_digests,
        }

    def bind_experiment(
        self,
        *,
        experiment_id: str,
        experiment_digest: str,
        approval_digest: str,
        task_card_path: str | Path,
        objective_confirmation_digest: str | None = None,
        task_card_digest: str | None = None,
        status: str = "STAGED",
        lane_id: str | None = None,
        run_id: str | None = None,
        acceptance_decided_at: str | None = None,
        acceptance_digest: str | None = None,
    ) -> None:
        """Advance lifecycle state without permitting authority fields to change.

        Legacy rows with absent authority remain readable but cannot be advanced
        through this normal path. Migration must be an explicit, separately
        audited operation; missing authority is never inferred.
        """

        if objective_confirmation_digest is None:
            raise JournalConflictError(
                "explicit objective_confirmation_digest is required for every binding"
            )
        if task_card_digest is None:
            raise JournalConflictError(
                "explicit task_card_digest is required for every binding"
            )
        experiment_id = _nonempty(experiment_id, "experiment_id")
        experiment_digest = _digest(experiment_digest)
        approval_digest = _digest(approval_digest)
        status = _nonempty(status, "status")
        if status not in {
            "STAGED", "LAUNCHING", "LAUNCHED", "RUNNING", "COMPLETED", "FAILED", "ERROR", "CANCELLED"
        }:
            raise JournalConflictError("unknown experiment lifecycle status")
        if (acceptance_decided_at is None) != (acceptance_digest is None):
            raise JournalConflictError(
                "Harness acceptance timestamp and digest must be supplied together"
            )
        if acceptance_decided_at is not None and status not in {
            "COMPLETED",
            "FAILED",
            "ERROR",
            "CANCELLED",
        }:
            raise JournalConflictError(
                "Harness acceptance evidence is valid only for a terminal binding"
            )
        if acceptance_decided_at is not None:
            try:
                accepted = datetime.fromisoformat(
                    acceptance_decided_at.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise JournalConflictError(
                    "acceptance_decided_at must be an ISO-8601 timestamp"
                ) from exc
            if accepted.tzinfo is None:
                raise JournalConflictError(
                    "acceptance_decided_at must include a timezone"
                )
            acceptance_digest = _digest(acceptance_digest)
        resolved_path = Path(task_card_path).expanduser().resolve()
        if not resolved_path.is_file():
            raise JournalConflictError("task card does not exist")
        actual_task_digest = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
        task_card_digest = _digest(task_card_digest)
        if task_card_digest != actual_task_digest:
            raise JournalConflictError("task_card_digest does not match the staged bytes")
        objective_confirmation_digest = _digest(objective_confirmation_digest)
        expected_card_authority = {
            "objective_confirmation_digest": objective_confirmation_digest,
            "experiment_digest": experiment_digest,
            "approval_digest": approval_digest,
        }
        if _task_card_authority(resolved_path) != expected_card_authority:
            raise JournalConflictError(
                "task card structured authority does not match the binding"
            )

        self.initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            approval = self._payload(connection, approval_digest)
            if approval is None:
                raise JournalConflictError("approval_digest is not a journal record")
            if approval.get("schema") != "human-approval/v1":
                raise JournalConflictError("approval_digest does not identify human approval")
            if approval.get("experiment_id") != experiment_id or approval.get("experiment_digest") != experiment_digest:
                raise JournalConflictError("binding conflicts with its immutable approval")
            approval_objective = approval.get("objective_confirmation_digest")
            if objective_confirmation_digest is None:
                objective_confirmation_digest = approval_objective
            if approval_objective != objective_confirmation_digest:
                raise JournalConflictError("binding objective conflicts with its immutable approval")
            existing = connection.execute(
                """
                SELECT experiment_digest, approval_digest,
                       objective_confirmation_digest, task_card_digest, task_card_path,
                       lane_id, run_id, status,
                       acceptance_decided_at, acceptance_digest
                FROM experiment_bindings WHERE experiment_id=?
                """,
                (experiment_id,),
            ).fetchone()
            authority = (
                experiment_digest,
                approval_digest,
                objective_confirmation_digest,
                task_card_digest,
                str(resolved_path),
            )
            if existing is not None:
                old = tuple(existing[:5])
                if old[2] is None or old[3] is None:
                    raise JournalConflictError(
                        "legacy binding lacks immutable authority; explicit audited migration required"
                    )
                if old != authority:
                    raise JournalConflictError(
                        "experiment binding conflicts with immutable authority fields"
                    )
                old_lane, old_run, old_status = existing[5], existing[6], existing[7]
                old_accepted_at, old_acceptance_digest = existing[8], existing[9]
                if old_lane is not None and lane_id is not None and old_lane != lane_id:
                    raise JournalConflictError("lane_id is immutable once assigned")
                if old_run is not None and run_id is not None and old_run != run_id:
                    raise JournalConflictError("run_id is immutable once assigned")
                if not _lifecycle_transition(str(old_status), status):
                    raise JournalConflictError(
                        f"invalid lifecycle transition from {old_status} to {status}"
                    )
                lane_id = old_lane if lane_id is None else lane_id
                run_id = old_run if run_id is None else run_id
                if old_accepted_at is not None and (
                    acceptance_decided_at is not None
                    and acceptance_decided_at != old_accepted_at
                ):
                    raise JournalConflictError(
                        "Harness acceptance timestamp is immutable once recorded"
                    )
                if old_acceptance_digest is not None and (
                    acceptance_digest is not None
                    and acceptance_digest != old_acceptance_digest
                ):
                    raise JournalConflictError(
                        "Harness acceptance digest is immutable once recorded"
                    )
                acceptance_decided_at = (
                    old_accepted_at
                    if acceptance_decided_at is None
                    else acceptance_decided_at
                )
                acceptance_digest = (
                    old_acceptance_digest
                    if acceptance_digest is None
                    else acceptance_digest
                )
            elif status != "STAGED":
                raise JournalConflictError("new experiment binding must begin in STAGED lifecycle")
            if status == "STAGED" and run_id is not None:
                raise JournalConflictError("STAGED binding cannot already have a run_id")
            if status in {"LAUNCHING", "LAUNCHED", "RUNNING"} and run_id is None:
                raise JournalConflictError(
                    f"{status} binding requires the bootstrapped run_id"
                )
            if status in {"COMPLETED", "FAILED", "ERROR"} and run_id is None:
                raise JournalConflictError("terminal executed binding requires a run_id")
            if status in {"COMPLETED", "FAILED", "ERROR"} and (
                acceptance_decided_at is None or acceptance_digest is None
            ):
                raise JournalConflictError(
                    "accepted terminal binding requires Harness acceptance evidence"
                )
            connection.execute(
                """
                INSERT INTO experiment_bindings
                    (experiment_id, experiment_digest, approval_digest,
                     objective_confirmation_digest, task_card_digest, task_card_path,
                     lane_id, run_id, acceptance_decided_at, acceptance_digest,
                     status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    lane_id=excluded.lane_id,
                    run_id=excluded.run_id,
                    acceptance_decided_at=excluded.acceptance_decided_at,
                    acceptance_digest=excluded.acceptance_digest,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    experiment_id,
                    experiment_digest,
                    approval_digest,
                    objective_confirmation_digest,
                    task_card_digest,
                    str(resolved_path),
                    lane_id,
                    run_id,
                    acceptance_decided_at,
                    acceptance_digest,
                    status,
                    _utc_now(),
                ),
            )

    def experiment_status(self, experiment_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT experiment_id, experiment_digest, approval_digest,
                       objective_confirmation_digest, task_card_digest,
                       task_card_path, lane_id, run_id, acceptance_decided_at,
                       acceptance_digest, status, updated_at
                FROM experiment_bindings WHERE experiment_id=?
                """,
                (experiment_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def learning_receipt(
        self,
        question_id: str,
        *,
        final: bool = False,
        objective_confirmation_digest: str | None = None,
    ) -> dict[str, Any]:
        """Project a deterministic ``learning-receipt/v1`` from one exact chain."""

        chain = self.reconstruct_chain(question_id)
        if chain["legacy_record_digests"]:
            raise JournalConflictError(
                "legacy /v1 records are readable but cannot produce an authority receipt; "
                "start a fresh objective-confirmed chain"
            )
        all_records = {
            record["record_digest"]: validate_record(record)
            for record in chain["records"]
        }
        question_records = [
            record for record in all_records.values()
            if record["schema"] == "research-question/v1"
        ]
        if len(question_records) != 1:
            raise JournalConflictError("chain requires exactly one research question")
        question = question_records[0]
        objectives = [
            record for record in all_records.values()
            if record["schema"] == "objective-confirmation/v1"
        ]
        superseded = {
            record["supersedes_objective_confirmation_digest"]
            for record in objectives
            if "supersedes_objective_confirmation_digest" in record
        }
        active = [record for record in objectives if record["record_digest"] not in superseded]
        if objective_confirmation_digest is not None:
            objective_confirmation_digest = _digest(objective_confirmation_digest)
            selected = [
                record for record in active
                if record["record_digest"] == objective_confirmation_digest
            ]
            if len(selected) != 1:
                raise JournalConflictError(
                    "requested objective is not a single unsuperseded confirmation"
                )
            objective = selected[0]
        elif len(active) == 1:
            objective = active[0]
        else:
            raise JournalConflictError(
                "objective confirmation is ambiguous; request one explicit unsuperseded digest"
            )

        adjacency: dict[str, set[str]] = {}
        for edge in chain["links"]:
            adjacency.setdefault(edge["parent_digest"], set()).add(edge["child_digest"])
        selected_digests = {objective["record_digest"]}
        queue = deque(selected_digests)
        while queue:
            parent = queue.popleft()
            for child in adjacency.get(parent, set()):
                if child not in selected_digests:
                    selected_digests.add(child)
                    queue.append(child)
        selected_digests.add(question["record_digest"])
        chain = {
            **chain,
            "records": [all_records[digest] for digest in sorted(selected_digests)],
            "links": [
                edge for edge in chain["links"]
                if edge["parent_digest"] in selected_digests
                and edge["child_digest"] in selected_digests
            ],
        }
        by_schema: dict[str, list[dict[str, Any]]] = {}
        for record in chain["records"]:
            by_schema.setdefault(record["schema"], []).append(record)
        if objective["question_digest"] != question["record_digest"]:
            raise JournalConflictError("objective does not bind the reconstructed question")

        mapping = {
            "reconciliation_digest": "branch-reconciliation/v1",
            "hypothesis_portfolio_digest": "hypothesis-portfolio/v1",
            "experiment_candidates_digest": "experiment-candidates/v1",
            "safety_review_digest": "safety-review/v1",
            "human_approval_digest": "human-approval/v1",
            "experiment_result_digest": "experiment-result/v1",
            "updated_decision_digest": "updated-decision/v1",
            "acceleration_summary_digest": "acceleration-summary/v1",
        }
        singular: dict[str, dict[str, Any] | None] = {
            key: _only(by_schema, schema, required=final)
            for key, schema in mapping.items()
        }
        candidates = singular["experiment_candidates_digest"]
        selected_id = candidates["selected_experiment_id"] if candidates else None
        selected_digest = experiment_digest(candidates) if candidates else None
        objective_digest = objective["record_digest"]
        for records in by_schema.values():
            for record in records:
                if record["schema"] not in {"research-question/v1", "objective-confirmation/v1"}:
                    if record.get("objective_confirmation_digest") != objective_digest:
                        raise JournalConflictError("chain contains a mismatched objective authority")

        approval = singular["human_approval_digest"]
        if approval and (
            approval["experiment_id"] != selected_id
            or approval["experiment_digest"] != selected_digest
        ):
            raise JournalConflictError("approval does not bind the selected experiment")
        result = singular["experiment_result_digest"]
        if result and approval and (
            result["experiment_id"] != selected_id
            or result["experiment_digest"] != selected_digest
            or result["approval_digest"] != approval["record_digest"]
        ):
            raise JournalConflictError("result does not bind the selected approval")
        if result and candidates and result["dataset_identity"] != candidates["dataset_identity"]:
            raise JournalConflictError("result dataset identity does not match the selected experiment")
        acceleration = singular["acceleration_summary_digest"]
        decision = singular["updated_decision_digest"]
        if acceleration:
            if result is None or candidates is None or decision is None or (
                acceleration["experiment_id"] != result["experiment_id"]
                or acceleration["result_digest"] != result["record_digest"]
                or acceleration["updated_decision_digest"]
                != decision["record_digest"]
                or acceleration["primary_metric"] != candidates["primary_metric"]
            ):
                raise JournalConflictError(
                    "acceleration summary does not bind the exact experiment result"
                )

        binding = self.experiment_status(selected_id) if selected_id else None
        task_digest: str | None = None
        snapshot: dict[str, Any] | None = None
        if binding is not None:
            task_path = Path(binding["task_card_path"])
            if not task_path.is_file():
                raise JournalConflictError("bound task card is missing")
            task_digest = hashlib.sha256(task_path.read_bytes()).hexdigest()
            expected_authority = (
                objective_digest,
                selected_digest,
                approval["record_digest"] if approval else None,
                task_digest,
            )
            actual_authority = (
                binding["objective_confirmation_digest"],
                binding["experiment_digest"],
                binding["approval_digest"],
                binding["task_card_digest"],
            )
            if actual_authority != expected_authority:
                raise JournalConflictError("execution snapshot authority does not match the chain")
            expected_card_authority = {
                "objective_confirmation_digest": objective_digest,
                "experiment_digest": selected_digest,
                "approval_digest": approval["record_digest"] if approval else None,
            }
            if _task_card_authority(task_path) != expected_card_authority:
                raise JournalConflictError("task card structured authority does not match the chain")
            if final:
                if binding["status"] not in {"COMPLETED", "FAILED", "ERROR", "CANCELLED"}:
                    raise JournalConflictError("final receipt requires a terminal execution binding")
                expected_binding_status = {
                    "PASS": "COMPLETED",
                    "FAIL": "COMPLETED",
                    "ERROR": "ERROR",
                    "CANCELLED": "CANCELLED",
                }.get(result["status"] if result else "")
                if (
                    result is None
                    or binding["run_id"] is None
                    or binding["run_id"] != result["run_id"]
                    or binding["experiment_id"] != result["experiment_id"]
                    or binding["status"] != expected_binding_status
                ):
                    raise JournalConflictError(
                        "final receipt result identity does not match the execution binding"
                    )
            snapshot = {
                key: binding[key]
                for key in (
                    "experiment_id",
                    "lane_id",
                    "run_id",
                    "status",
                    "objective_confirmation_digest",
                    "experiment_digest",
                    "approval_digest",
                    "task_card_digest",
                    "acceptance_decided_at",
                    "acceptance_digest",
                )
            }
        elif final or approval is not None:
            raise JournalConflictError("approved chain has no execution binding")

        receipt: dict[str, Any] = {
            "schema": "learning-receipt/v1",
            "question_id": question_id,
            "question_digest": question["record_digest"],
            "objective_confirmation_digest": objective_digest,
            "evidence_package_digests": sorted(
                record["record_digest"]
                for record in by_schema.get("evidence-package/v1", [])
            ),
            **{
                key: value["record_digest"] if value is not None else None
                for key, value in singular.items()
            },
            "selected_experiment_id": selected_id,
            "experiment_digest": selected_digest,
            "task_card_digest": task_digest,
            "provenance_edges": chain["links"],
            "execution_snapshot": snapshot,
        }
        receipt["receipt_digest"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
        return receipt

    def _validate_cross_record(
        self,
        connection: sqlite3.Connection,
        record: dict[str, Any],
        links: tuple[tuple[str, str], ...],
    ) -> None:
        schema = record["schema"]
        parents = {digest for digest, _ in links}
        ancestors = self._ancestors(connection, parents)
        ancestor_records = {
            digest: self._payload(connection, digest) for digest in ancestors
        }

        if schema == "research-question/v1":
            if links:
                raise JournalConflictError("research question cannot have an upstream scientific record")
            return
        if not links:
            raise JournalConflictError(f"{schema} requires explicit provenance links")

        if schema == "objective-confirmation/v1":
            question = ancestor_records.get(record["question_digest"])
            if question is None or question.get("schema") != "research-question/v1":
                raise JournalConflictError("objective question_digest is not a linked research question")
            if question["question_id"] != record["question_id"]:
                raise JournalConflictError("objective and question identities do not match")
            if question["primary_metric"] != record["primary_metric"]:
                raise JournalConflictError("objective changes the question primary metric")
            supersedes = record.get("supersedes_objective_confirmation_digest")
            if supersedes is not None:
                prior = ancestor_records.get(supersedes)
                if prior is None or prior.get("schema") != "objective-confirmation/v1":
                    raise JournalConflictError("superseded objective is not linked")
                if prior["question_id"] != record["question_id"]:
                    raise JournalConflictError("cannot supersede another question's objective")
            return

        authority_digest = record["objective_confirmation_digest"]
        objective = ancestor_records.get(authority_digest)
        if objective is None or objective.get("schema") != "objective-confirmation/v1":
            raise JournalConflictError("objective authority is absent from the linked provenance chain")
        if record.get("question_id", objective["question_id"]) != objective["question_id"]:
            raise JournalConflictError("record question does not match objective authority")
        if self._is_superseded(connection, authority_digest):
            raise JournalConflictError("objective authority has been superseded")

        if schema == "feasibility-check/v1":
            return
        if schema == "evidence-package/v1":
            existing_ids = self._question_evidence_ids(
                connection, record["question_id"]
            )
            new_ids = {claim["evidence_id"] for claim in record["claims"]}
            duplicated = sorted(existing_ids & new_ids)
            if duplicated:
                raise JournalConflictError(
                    "evidence_id values must be globally unique within a question: "
                    + ", ".join(duplicated)
                )
            return
        if schema == "parallel-branch/v1":
            evidence = ancestor_records.get(record.get("evidence_package_digest"))
            if record["status"] == "COMPLETED" and (
                evidence is None or evidence.get("schema") != "evidence-package/v1"
            ):
                raise JournalConflictError("parallel branch evidence package is not linked")
            return
        if schema == "branch-reconciliation/v1":
            self._validate_reconciliation_links(connection, record, ancestor_records)
            return
        if schema == "hypothesis-portfolio/v1":
            evidence_ids = {
                claim["evidence_id"]
                for parent in ancestor_records.values()
                if parent is not None and parent.get("schema") == "evidence-package/v1"
                for claim in parent["claims"]
            }
            referenced = {
                evidence_id
                for hypothesis in record["hypotheses"]
                for evidence_id in hypothesis["supporting_evidence_ids"]
            }
            if not referenced <= evidence_ids:
                raise JournalConflictError("hypothesis references unknown cited evidence IDs")
            return
        if schema == "experiment-candidates/v1":
            matching_hypotheses = [
                hypothesis
                for parent in ancestor_records.values()
                if parent is not None
                and parent.get("schema") == "hypothesis-portfolio/v1"
                for hypothesis in parent["hypotheses"]
                if hypothesis["hypothesis_id"] == record["hypothesis_id"]
            ]
            if len(matching_hypotheses) != 1:
                raise JournalConflictError(
                    "candidate hypothesis_id must resolve exactly once in linked ancestors"
                )
            feasibility_rows = connection.execute(
                "SELECT payload_json FROM records WHERE schema_name='feasibility-check/v1'"
            ).fetchall()
            objective_checks = [
                json.loads(row[0])
                for row in feasibility_rows
                if json.loads(row[0]).get("objective_confirmation_digest")
                == authority_digest
            ]
            if any(check.get("overall_status") == "FAIL" for check in objective_checks):
                raise JournalConflictError(
                    "a failed feasibility check blocks experiment candidates"
                )
            feasible = [
                parent for parent in ancestor_records.values()
                if parent is not None
                and parent.get("schema") == "feasibility-check/v1"
                and parent.get("overall_status") == "PASS"
            ]
            if len(objective_checks) != 1 or len(feasible) != 1:
                raise JournalConflictError(
                    "experiment candidates require exactly one linked passing feasibility check"
                )
            if record["primary_metric"] != objective["primary_metric"]:
                raise JournalConflictError("candidate primary metric exceeds objective authority")
            objective_dataset = {
                key: objective["dataset"][key]
                for key in ("identifier", "version", "digest")
            }
            if record["dataset_identity"] != objective_dataset:
                raise JournalConflictError("candidate dataset exceeds objective authority")
            scope = objective["execution_scope"]
            bounds = record["resource_bounds"]
            for key in ("max_trials", "max_runtime_minutes", "max_cost_usd"):
                if bounds[key] > scope[key]:
                    raise JournalConflictError(f"candidate {key} exceeds objective authority")
            for key in ("compute", "network_access", "mutation_permissions"):
                if bounds[key] != scope[key]:
                    raise JournalConflictError(
                        f"candidate {key} differs from objective authority"
                    )
            if record["risk_tolerance"] != objective["risk_tolerance"]:
                raise JournalConflictError(
                    "candidate risk tolerance differs from objective authority"
                )
            return
        if schema == "safety-review/v1":
            portfolio = _ancestor_schema(ancestor_records, "experiment-candidates/v1")
            if record["experiment_digest"] != experiment_digest(portfolio):
                raise JournalConflictError("safety review does not bind the selected experiment")
            if record["experiment_id"] != portfolio["selected_experiment_id"]:
                raise JournalConflictError("safety review targets another experiment")
            return
        if schema == "human-approval/v1":
            review = _ancestor_schema(ancestor_records, "safety-review/v1")
            if review["verdict"] != "APPROVAL_REQUIRED":
                raise JournalConflictError("safety review does not permit approval")
            if (
                record["experiment_id"] != review["experiment_id"]
                or record["experiment_digest"] != review["experiment_digest"]
            ):
                raise JournalConflictError("approval does not bind the reviewed experiment")
            return
        if schema == "experiment-result/v1":
            approval = ancestor_records.get(record["approval_digest"])
            if approval is None or approval.get("schema") != "human-approval/v1":
                raise JournalConflictError("result approval_digest is not linked human approval")
            if (
                record["experiment_id"] != approval["experiment_id"]
                or record["experiment_digest"] != approval["experiment_digest"]
            ):
                raise JournalConflictError("result does not bind the approved experiment")
            portfolio = _ancestor_schema(ancestor_records, "experiment-candidates/v1")
            if record["dataset_identity"] != portfolio["dataset_identity"]:
                raise JournalConflictError("result dataset identity does not match the approved experiment")
            selected = selected_experiment(portfolio)
            parameters = record["parameters"]
            if parameters["approved_candidate_parameters"] != selected["parameters"]:
                raise JournalConflictError(
                    "result approved parameters do not match the immutable selected experiment"
                )
            preregistration = parameters["observed_preregistration"]
            preregistration_fields = {
                "primary_metric": portfolio["primary_metric"],
                "dataset_identity": portfolio["dataset_identity"],
                "split_seed": selected["random_seeds"][0],
                "threshold": selected["parameters"]["threshold"],
                "max_trials_per_arm": selected["parameters"]["max_trials_per_arm"],
                "max_seconds_per_arm": selected["parameters"]["max_seconds_per_arm"],
            }
            if any(
                preregistration.get(field) != expected
                for field, expected in preregistration_fields.items()
            ):
                raise JournalConflictError(
                    "observed preregistration differs from the approved experiment"
                )
            for field in (
                "baseline_order",
                "evidence_guided_order",
                "quality_noninferiority_margin",
            ):
                if field in selected["parameters"] and (
                    preregistration.get(field) != selected["parameters"][field]
                ):
                    raise JournalConflictError(
                        "observed preregistration differs from approved executable parameters"
                    )
            if (
                record["primary_metric"] != portfolio["primary_metric"]
                or record["random_seeds"] != selected["random_seeds"]
            ):
                raise JournalConflictError(
                    "result metric or random seeds differ from the approved experiment"
                )
            return
        if schema == "updated-decision/v1":
            result = ancestor_records.get(record["result_digest"])
            if result is None or result.get("schema") != "experiment-result/v1":
                raise JournalConflictError("decision result_digest is not linked")
            if (
                record["run_id"] != result["run_id"]
                or record["experiment_id"] != result["experiment_id"]
                or not set(record["interpreted_metrics"]) <= set(result["metrics"])
            ):
                raise JournalConflictError("decision does not faithfully reference the result")
            binding = connection.execute(
                """
                SELECT run_id, status, acceptance_decided_at, acceptance_digest
                FROM experiment_bindings WHERE experiment_id=?
                """,
                (record["experiment_id"],),
            ).fetchone()
            timing = record["decision_timing"]
            if (
                binding is None
                or binding[0] != record["run_id"]
                or binding[1] not in {"COMPLETED", "FAILED", "ERROR", "CANCELLED"}
                or binding[2] != timing["result_accepted_at"]
                or binding[3] != timing["harness_acceptance_digest"]
            ):
                raise JournalConflictError(
                    "decision timing does not match the accepted Harness boundary"
                )
            result_completed = datetime.fromisoformat(
                result["completed_at"].replace("Z", "+00:00")
            )
            result_accepted = datetime.fromisoformat(
                timing["result_accepted_at"].replace("Z", "+00:00")
            )
            if result_accepted < result_completed:
                raise JournalConflictError(
                    "Harness acceptance cannot precede experiment completion"
                )
            matching_hypotheses = [
                hypothesis
                for parent in ancestor_records.values()
                if parent is not None
                and parent.get("schema") == "hypothesis-portfolio/v1"
                for hypothesis in parent["hypotheses"]
                if hypothesis["hypothesis_id"] == record["hypothesis_id"]
            ]
            if len(matching_hypotheses) != 1:
                raise JournalConflictError(
                    "decision hypothesis_id must resolve exactly once in linked ancestors"
                )
            evidence_ids = {
                claim["evidence_id"]
                for parent in ancestor_records.values()
                if parent is not None and parent.get("schema") == "evidence-package/v1"
                for claim in parent["claims"]
            }
            if not set(record["supporting_evidence_ids"]) <= evidence_ids:
                raise JournalConflictError(
                    "decision references evidence outside its exact linked ancestors"
                )
            return
        if schema == "acceleration-summary/v1":
            result = ancestor_records.get(record["result_digest"])
            if result is None or result.get("schema") != "experiment-result/v1":
                raise JournalConflictError("acceleration summary result_digest is not linked")
            decision = ancestor_records.get(record["updated_decision_digest"])
            if (
                decision is None
                or decision.get("schema") != "updated-decision/v1"
                or decision.get("result_digest") != result["record_digest"]
            ):
                raise JournalConflictError(
                    "acceleration summary updated_decision_digest is not linked to its result"
                )
            portfolio = _ancestor_schema(ancestor_records, "experiment-candidates/v1")
            if (
                record["experiment_id"] != result["experiment_id"]
                or record["experiment_id"] != portfolio["selected_experiment_id"]
                or record["primary_metric"] != portfolio["primary_metric"]
                or record["primary_metric"] not in result["metrics"]
            ):
                raise JournalConflictError(
                    "acceleration summary does not bind the exact experiment/result/primary metric"
                )
            if record["dataset_identity"] != result["dataset_identity"]:
                raise JournalConflictError(
                    "acceleration dataset identity differs from the immutable result"
                )
            metrics = result["metrics"]
            preregistration = result["parameters"]["observed_preregistration"]
            expected_arm_metric_names = {
                "baseline": "baseline",
                "proposed": "evidence_guided",
            }
            execution_availability = result["parameters"]["execution_metadata"][
                "measurement_availability"
            ]
            arm_overhead: dict[str, bool] = {}
            for arm_name, nested_name in expected_arm_metric_names.items():
                arm = record["arms"][arm_name]
                nested_metrics = metrics[nested_name]
                nested_availability = nested_metrics.get("measurement_availability")
                expected_availability = execution_availability.get(arm_name)
                if (
                    not isinstance(nested_availability, Mapping)
                    or nested_availability != expected_availability
                    or arm.get("measurement_availability") != nested_availability
                ):
                    raise JournalConflictError(
                        f"acceleration {arm_name} measurement availability differs "
                        "from the immutable result"
                    )
                overhead = nested_metrics.get("overhead_included")
                if not isinstance(overhead, bool) or (
                    nested_availability.get("workflow_overhead")
                    != ("MEASURED" if overhead else "UNAVAILABLE")
                ):
                    raise JournalConflictError(
                        f"acceleration {arm_name} workflow overhead provenance is invalid"
                    )
                arm_overhead[arm_name] = overhead
                exact_values = {
                    "trials_to_threshold": metrics["trials_to_threshold"][arm_name],
                    "elapsed_to_threshold_seconds": metrics[
                        "elapsed_to_threshold_seconds"
                    ][arm_name],
                    "total_elapsed_seconds": metrics["total_elapsed_seconds"][arm_name],
                    "compute_seconds": metrics["compute_seconds"][arm_name],
                    "best_metric": metrics["accuracy"][arm_name],
                    "interventions": metrics["interventions"][arm_name],
                    "cost_usd": metrics["cost_usd"][arm_name],
                    "token_usage": metrics["token_usage"][arm_name],
                    "trial_budget": preregistration["max_trials_per_arm"],
                    "trials_attempted": metrics[nested_name]["attempted_trials"],
                }
                if any(arm.get(key) != value for key, value in exact_values.items()):
                    raise JournalConflictError(
                        f"acceleration {arm_name} measurements differ from the immutable result"
                    )
            expected_overhead = all(arm_overhead.values())
            expected_timing_scope = (
                "end-to-end-arm-workflow"
                if expected_overhead
                else "model-evaluation-only"
            )
            result_acceleration = metrics.get("acceleration")
            if not isinstance(result_acceleration, Mapping):
                raise JournalConflictError(
                    "immutable result omits its observed acceleration calculation"
                )
            immutable_acceleration = {
                "matched_conditions": result_acceleration.get("matched_controls"),
                "overhead_included": result_acceleration.get("overhead_included"),
                "timing_scope": result_acceleration.get("timing_scope"),
                "overall_discovery_speed_claim": result_acceleration.get(
                    "overall_discovery_speed_claim"
                ),
                "observed_trial_speedup": result_acceleration.get("trial_speedup"),
                "observed_time_speedup": result_acceleration.get("time_speedup"),
                "trial_speedup_lower_bound": result_acceleration.get(
                    "trial_speedup_lower_bound"
                ),
                "quality_non_inferiority": result_acceleration.get(
                    "quality_non_inferiority"
                ),
                "claim_blockers": result_acceleration.get("claim_blockers"),
            }
            if any(
                record.get(field) != expected
                for field, expected in immutable_acceleration.items()
            ):
                raise JournalConflictError(
                    "acceleration claims differ from the immutable result calculation"
                )
            if (
                record["overhead_included"] is not expected_overhead
                or record["timing_scope"] != expected_timing_scope
            ):
                raise JournalConflictError(
                    "acceleration timing scope contradicts immutable workflow measurements"
                )
            margin = preregistration.get("quality_noninferiority_margin")
            if (
                margin is None
                or record["quality_non_inferiority"].get("margin") != margin
            ):
                raise JournalConflictError(
                    "acceleration quality margin differs from preregistration"
                )
            decision_timing = decision["decision_timing"]
            if (
                record["decision_latency_seconds"]
                != decision_timing["latency_seconds"]
                or record["decision_timing_source_digest"]
                != decision["decision_timing_source_digest"]
                or record["matched_controls_digest"]
                != preregistration["control_digest"]
                or record["endpoint_rules"] != preregistration["endpoint_rules"]
            ):
                raise JournalConflictError(
                    "acceleration latency, decision source, or preregistered controls differ"
                )

    def _validate_reconciliation_links(
        self,
        connection: sqlite3.Connection,
        record: dict[str, Any],
        ancestors: Mapping[str, dict[str, Any] | None],
    ) -> None:
        branches: dict[str, dict[str, Any]] = {}
        trusted_intervals: dict[str, tuple[str, str]] = {}
        producer_sessions: set[str] = set()
        invocation_ids: set[str] = set()
        provider_session_ids: set[str] = set()
        evidence_digests: set[str] = set()
        branch_evidence_ids: dict[str, set[str]] = {}
        for digest in record["branch_digests"]:
            branch = ancestors.get(digest)
            if branch is None or branch.get("schema") != "parallel-branch/v1":
                raise JournalConflictError("reconciliation branch digest is not linked")
            branch_id = branch["branch_id"]
            if branch_id in branches:
                raise JournalConflictError("parallel branch IDs must be distinct")
            branches[branch_id] = branch
            row = connection.execute(
                """SELECT producer_session_id, producer_agent_id,
                          invocation_id, invocation_status,
                          provider_session_id, provider_receipt_digest,
                          provider_receipt_json,
                          invocation_started_at, invocation_completed_at
                   FROM records WHERE record_digest=?""",
                (digest,),
            ).fetchone()
            if row is None:
                raise JournalConflictError("parallel branch lacks trusted runtime timing")
            metadata = _validate_stored_provider_receipt(branch, row)
            if (
                row["invocation_status"] != "COMPLETED"
                or branch.get("invocation_status") != "COMPLETED"
                or row["invocation_id"] != branch.get("invocation_id")
            ):
                raise JournalConflictError(
                    "parallel branch lacks a trusted completed invocation lifecycle"
                )
            producer_sessions.add(str(row["producer_session_id"]))
            invocation_ids.add(str(row["invocation_id"]))
            provider_session_ids.add(str(row["provider_session_id"]))
            evidence_digest = branch.get("evidence_package_digest")
            evidence = ancestors.get(str(evidence_digest))
            if (
                branch.get("status") != "COMPLETED"
                or evidence is None
                or evidence.get("schema") != "evidence-package/v1"
                or not evidence.get("claims")
            ):
                raise JournalConflictError(
                    "parallel MET requires completed branches with nonempty cited evidence"
                )
            evidence_digests.add(str(evidence_digest))
            branch_evidence_ids[branch_id] = {
                claim["evidence_id"] for claim in evidence["claims"]
            }
            trusted_intervals[branch_id] = metadata
        if record["parallel_status"] == "MET":
            branch_count = len(branches)
            if len(producer_sessions) != branch_count:
                raise JournalConflictError(
                    "parallel MET requires distinct producer sessions"
                )
            if len(invocation_ids) != branch_count:
                raise JournalConflictError(
                    "parallel MET requires distinct trusted invocations"
                )
            if len(provider_session_ids) != branch_count:
                raise JournalConflictError(
                    "parallel MET requires distinct provider-owned sessions"
                )
            if len(evidence_digests) != branch_count:
                raise JournalConflictError(
                    "parallel MET requires distinct evidence packages"
                )
            reconciled = set(record["reconciled_evidence_ids"])
            if any(not (ids & reconciled) for ids in branch_evidence_ids.values()):
                raise JournalConflictError(
                    "parallel MET must reconcile cited evidence from every branch"
                )
        real_pairs: set[tuple[str, str]] = set()
        ids = sorted(branches)
        for index, left_id in enumerate(ids):
            for right_id in ids[index + 1 :]:
                left_start, left_end = trusted_intervals[left_id]
                right_start, right_end = trusted_intervals[right_id]
                if left_start < right_end and right_start < left_end:
                    real_pairs.add((left_id, right_id))
        claimed = {tuple(sorted(pair)) for pair in record["overlapping_branch_pairs"]}
        if claimed != real_pairs:
            raise JournalConflictError("claimed branch overlap does not match trusted runtime overlap")
        expected = "MET" if real_pairs else "UNMET"
        if record["parallel_status"] != expected:
            raise JournalConflictError("parallel_status does not match authoritative intervals")

    def _is_superseded(self, connection: sqlite3.Connection, digest: str) -> bool:
        rows = connection.execute(
            "SELECT payload_json FROM records WHERE schema_name='objective-confirmation/v1'"
        ).fetchall()
        return any(
            json.loads(row[0]).get("supersedes_objective_confirmation_digest") == digest
            for row in rows
        )

    @staticmethod
    def _question_evidence_ids(
        connection: sqlite3.Connection, question_id: str
    ) -> set[str]:
        rows = connection.execute(
            "SELECT payload_json FROM records WHERE schema_name='evidence-package/v1'"
        ).fetchall()
        return {
            claim["evidence_id"]
            for row in rows
            for record in (json.loads(row[0]),)
            if record.get("question_id") == question_id
            for claim in record.get("claims", [])
        }

    def _ancestors(
        self, connection: sqlite3.Connection, starts: set[str]
    ) -> set[str]:
        found = set(starts)
        queue = deque(starts)
        while queue:
            child = queue.popleft()
            rows = connection.execute(
                "SELECT parent_digest FROM record_links WHERE child_digest=?", (child,)
            ).fetchall()
            for row in rows:
                parent = row[0]
                if parent not in found:
                    found.add(parent)
                    queue.append(parent)
        return found

    def _descendants(
        self, connection: sqlite3.Connection, root: str
    ) -> tuple[set[str], list[dict[str, str]]]:
        found = {root}
        queue = deque([root])
        edge_set: set[tuple[str, str, str]] = set()
        while queue:
            parent = queue.popleft()
            rows = connection.execute(
                """
                SELECT parent_digest, relation, child_digest FROM record_links
                WHERE parent_digest=?
                """,
                (parent,),
            ).fetchall()
            for row in rows:
                edge = (row["parent_digest"], row["relation"], row["child_digest"])
                edge_set.add(edge)
                child = row["child_digest"]
                if child not in found:
                    found.add(child)
                    queue.append(child)
        edges = [
            {"parent_digest": parent, "relation": relation, "child_digest": child}
            for parent, relation, child in sorted(edge_set)
        ]
        return found, edges

    @staticmethod
    def _payload(
        connection: sqlite3.Connection, digest: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT payload_json FROM records WHERE record_digest=?", (digest,)
        ).fetchone()
        return json.loads(row[0]) if row is not None else None

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, declaration: str
    ) -> None:
        columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection


def _only(
    by_schema: Mapping[str, list[dict[str, Any]]], schema: str, *, required: bool
) -> dict[str, Any] | None:
    records = by_schema.get(schema, [])
    if len(records) > 1:
        raise JournalConflictError(f"chain has conflicting {schema} records")
    if required and not records:
        raise JournalConflictError(f"chain is missing required {schema}")
    return records[0] if records else None


def _ancestor_schema(
    ancestors: Mapping[str, dict[str, Any] | None], schema: str
) -> dict[str, Any]:
    records = [record for record in ancestors.values() if record and record.get("schema") == schema]
    if len(records) != 1:
        raise JournalConflictError(f"provenance requires exactly one linked {schema}")
    return records[0]


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value


def _digest(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("digest must be a lowercase SHA-256 digest")
    return value


def _agent_from_source(source: str) -> str:
    return source.split(":", 1)[-1]


def _trusted_interval(
    started_at: str | None,
    completed_at: str | None,
    *,
    required: bool,
) -> tuple[str | None, str | None]:
    if started_at is None and completed_at is None and not required:
        return None, None
    if started_at is None or completed_at is None:
        raise JournalConflictError("trusted invocation timing requires both endpoints")
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise JournalConflictError("trusted invocation timing must be ISO-8601") from exc
    if started.tzinfo is None or completed.tzinfo is None or completed <= started:
        raise JournalConflictError("trusted invocation timing must be ordered and timezone-aware")
    return (
        started.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        completed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _task_card_authority(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JournalConflictError("task card must be valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise JournalConflictError("task card must be a JSON object")
    authority = payload.get("research_authority")
    required = {
        "objective_confirmation_digest",
        "experiment_digest",
        "approval_digest",
    }
    if not isinstance(authority, Mapping) or set(authority) != required:
        raise JournalConflictError("task card requires an exact structured authority mapping")
    try:
        return {key: _digest(authority[key]) for key in sorted(required)}
    except (TypeError, ValueError) as exc:
        raise JournalConflictError("task card structured authority contains invalid digests") from exc


def _lifecycle_transition(old: str, new: str) -> bool:
    allowed = {
        "STAGED": {"STAGED", "LAUNCHING", "CANCELLED"},
        "LAUNCHING": {"LAUNCHING", "LAUNCHED", "CANCELLED"},
        "LAUNCHED": {"LAUNCHED", "RUNNING", "COMPLETED", "FAILED", "ERROR", "CANCELLED"},
        "RUNNING": {"RUNNING", "COMPLETED", "FAILED", "ERROR", "CANCELLED"},
        "COMPLETED": {"COMPLETED"},
        "FAILED": {"FAILED"},
        "ERROR": {"ERROR"},
        "CANCELLED": {"CANCELLED"},
    }
    return new in allowed.get(old, set())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
