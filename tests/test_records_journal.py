from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from ai_researcher.journal import (
    JournalConflictError,
    ResearchJournal,
    _verify_omnigent_session_export,
)
from ai_researcher.records import (
    RecordValidationError,
    experiment_digest,
    record_digest,
    selected_experiment,
    validate_record,
    validate_stored_record,
)


def _question() -> dict:
    return {
        "schema": "research-question/v1",
        "question_id": "q-1",
        "question": "Can guided search reach the target in fewer trials?",
        "domain": "machine learning",
        "intended_scientific_use": "Evaluate a bounded discovery policy.",
        "measurable_outcome": "Trials to the fixed target.",
        "primary_metric": "trials_to_threshold",
        "constraints": ["four trials per arm"],
        "assumptions": ["fixed split"],
    }


def _objective(question: dict) -> dict:
    return {
        "schema": "objective-confirmation/v1",
        "objective_confirmation_id": "objective-1",
        "question_id": question["question_id"],
        "question_digest": question["record_digest"],
        "primary_metric": question["primary_metric"],
        "dataset": {
            "identifier": "openml-task-59",
            "version": "active",
            "digest": "a" * 64,
            "source": "https://www.openml.org/t/59",
        },
        "risk_tolerance": {
            "level": "low",
            "allowed_risks": ["bounded compute overrun"],
            "prohibited_actions": ["data mutation"],
            "privacy_constraints": ["public data only"],
            "acceptable_failure_modes": ["inconclusive result"],
        },
        "execution_scope": {
            "max_trials": 8,
            "max_runtime_minutes": 30,
            "max_cost_usd": 1.0,
            "compute": "local CPU",
            "network_access": "dataset-download-only",
            "mutation_permissions": ["artifact directory only"],
        },
        "confirmed_by": "human:test",
        "confirmed_at": "2026-10-03T12:00:00Z",
    }


def _evidence(objective_digest: str, package_id: str = "evidence-a") -> dict:
    return {
        "schema": "evidence-package/v1",
        "evidence_package_id": package_id,
        "question_id": "q-1",
        "objective_confirmation_digest": objective_digest,
        "claims": [
            {
                "evidence_id": f"claim-{package_id}",
                "claim_type": "external-fact",
                "claim": "The task has a stable OpenML identifier.",
                "source_type": "dataset-registry",
                "citation": {
                    "title": "OpenML task 59 / dataset 61",
                    "url": "https://www.openml.org/t/59",
                    "authors_or_organization": "OpenML",
                    "publisher_or_source": "OpenML",
                    "retrieved_at": "2026-10-03T12:01:00Z",
                    "license_or_access_note": "Public task metadata.",
                    "verification_state": "verified",
                },
                "support": "Structured task identifier field.",
                "uncertainty": "Availability can change.",
            }
        ],
        "conflicts": [],
        "coverage_gaps": [],
    }


def _branch(objective_digest: str, evidence_digest: str, branch_id: str, start: str, end: str) -> dict:
    return {
        "schema": "parallel-branch/v1",
        "branch_id": branch_id,
        "question_id": "q-1",
        "objective_confirmation_digest": objective_digest,
        "bounded_question": f"Independent question {branch_id}",
        "producer_agent_id": f"agent:{branch_id}",
        "producer_session_id": f"session:{branch_id}",
        "started_at": start,
        "completed_at": end,
        "status": "COMPLETED",
        "independent_context": True,
        "invocation_id": f"invocation:{branch_id}",
        "invocation_status": "COMPLETED",
        "provider_session_id": f"conv-{branch_id}",
        "provider_receipt_digest": "0" * 64,
        "evidence_package_digest": evidence_digest,
    }


def _provider_invocation(
    branch_id: str,
    *,
    session_id: str | None = None,
    request_created_at: int | None = None,
    response_created_at: int | None = None,
    marker_started_at: int | None = None,
    marker_completed_at: int | None = None,
    session_created_at: int | None = None,
    session_updated_at: int | None = None,
    include_markers: bool = True,
    include_substantive_call: bool = True,
    include_source_inspections: bool = True,
    include_validation: bool = True,
    substantive_after_end: bool = False,
    search_tool_name: str = "web_search",
):
    session_id = session_id or f"conv-{branch_id}"
    suffix = 1 if branch_id.endswith("a") else 2
    response_id = f"response-{branch_id}"
    request_time = request_created_at or 1791028800 + suffix * 60
    marker_start = marker_started_at or request_time + 10
    marker_end = marker_completed_at or marker_start + 120
    assistant_time = response_created_at or marker_end + 10
    start_marker_id = f"marker-start-{branch_id}"
    end_marker_id = f"marker-end-{branch_id}"
    start_call_id = f"call-start-{branch_id}"
    end_call_id = f"call-end-{branch_id}"
    search_call_id = f"call-search-{branch_id}"
    source_urls = [
        f"https://example.org/{branch_id}/source-a",
        f"https://example.org/{branch_id}/source-b",
    ]
    package = {
        "schema": "evidence-package/v1",
        "evidence_package_id": f"package-{branch_id}",
        "question_id": "q-1",
        "objective_confirmation_digest": "a" * 64,
        "claims": [
            {
                "evidence_id": f"claim-{branch_id}-{index}",
                "claim_type": "external-fact",
                "claim": f"Narrow externally supported fact {index}.",
                "source_type": "official-documentation",
                "citation": {
                    "title": f"Source {index}",
                    "url": url,
                    "authors_or_organization": "Example",
                    "publisher_or_source": "Example",
                    "retrieved_at": "2026-10-03T12:01:00Z",
                    "license_or_access_note": "Public access.",
                    "verification_state": "verified",
                },
                "support": f"Directly inspected field {index}.",
                "uncertainty": "Limited to the documented field.",
            }
            for index, url in enumerate(source_urls, start=1)
        ],
        "conflicts": [],
        "coverage_gaps": [],
    }
    package_digest = validate_record(package)["record_digest"]
    rows = [
        json.dumps({
            "record_type": "session_meta",
            "id": session_id,
            "agent_id": "ag-evidence-researcher",
            "agent_name": f"agent:{branch_id}",
            "sub_agent_name": "evidence-researcher",
            "parent_session_id": "conv-research-director",
            "root_conversation_id": "conv-research-director",
            "status": "idle",
            # Session metadata is intentionally independent of the execution
            # interval. Omnigent may update it for operations such as rename.
            "created_at": session_created_at or 1791028700,
            "updated_at": session_updated_at or 1791029300,
            "llm_model": "hermetic-provider-model",
            "harness": "claude-sdk",
            "last_total_tokens": 42,
        }),
        json.dumps({
            "record_type": "item",
            "id": f"request-{branch_id}",
            "type": "message",
            "status": "completed",
            # Real Omnigent exports use a turn ID for the user request and a
            # provider response ID for the calls/results.
            "response_id": f"turn-{branch_id}",
            "created_by": "operator",
            "created_at": request_time,
            "role": "user",
            "content": [{"type": "text", "text": f"Investigate {branch_id}."}],
        }),
    ]
    if include_markers:
        rows.extend([
            json.dumps({
                "record_type": "item", "id": f"start-call-{branch_id}",
                "type": "function_call", "status": "completed",
                "response_id": response_id, "created_at": marker_start - 1,
                "model": f"agent:{branch_id}",
                "name": "mark_provider_execution_start",
                "arguments": json.dumps({"branch_id": branch_id}),
                "call_id": start_call_id,
            }),
            json.dumps({
                "record_type": "item", "id": f"start-result-{branch_id}",
                "type": "function_call_output", "status": "completed",
                "response_id": response_id, "created_at": marker_start,
                "call_id": start_call_id,
                "output": json.dumps({
                    "schema": "provider-execution-marker/v1", "phase": "START",
                    "branch_id": branch_id, "marker_id": start_marker_id,
                }),
            }),
        ])
        substantive_rows = [
            json.dumps({
                "record_type": "item", "id": f"search-call-{branch_id}",
                "type": "function_call", "status": "completed",
                "response_id": response_id, "created_at": marker_start + 1,
                "model": f"agent:{branch_id}", "name": search_tool_name,
                "arguments": json.dumps({"query": f"evidence for {branch_id}"}),
                "call_id": search_call_id,
            }),
            json.dumps({
                "record_type": "item", "id": f"search-result-{branch_id}",
                "type": "function_call_output", "status": "completed",
                "response_id": response_id, "created_at": marker_start + 2,
                "call_id": search_call_id,
                "output": json.dumps({"results": [{"title": "Evidence"}]}),
            }),
        ]
        if include_source_inspections:
            for index, url in enumerate(source_urls, start=1):
                substantive_rows.extend(
                    [
                        json.dumps({
                            "record_type": "item",
                            "id": f"inspect-call-{branch_id}-{index}",
                            "type": "function_call",
                            "status": "completed",
                            "response_id": response_id,
                            "created_at": marker_start + 2 + index * 2,
                            "model": f"agent:{branch_id}",
                            "name": "inspect_public_source",
                            "arguments": json.dumps({"url": url}),
                            "call_id": f"call-inspect-{branch_id}-{index}",
                        }),
                        json.dumps({
                            "record_type": "item",
                            "id": f"inspect-result-{branch_id}-{index}",
                            "type": "function_call_output",
                            "status": "completed",
                            "response_id": response_id,
                            "created_at": marker_start + 3 + index * 2,
                            "call_id": f"call-inspect-{branch_id}-{index}",
                            "output": json.dumps({
                                "schema": "public-source-inspection/v1",
                                "requested_url": url,
                                "final_url": url,
                                "http_status": 200,
                                "content_type": "text/html",
                                "retrieved_at": "2026-10-03T12:01:00Z",
                                "body_sha256": str(index) * 64,
                                "title": f"Source {index}",
                                "text_excerpt": f"Directly inspected field {index}.",
                                "truncated": False,
                            }),
                        }),
                    ]
                )
        if include_validation:
            substantive_rows.extend(
                [
                    json.dumps({
                        "record_type": "item",
                        "id": f"validation-call-{branch_id}",
                        "type": "function_call",
                        "status": "completed",
                        "response_id": response_id,
                        "created_at": marker_start + 20,
                        "model": f"agent:{branch_id}",
                        "name": "validate_evidence_package",
                        "arguments": json.dumps({"package_json": json.dumps(package)}),
                        "call_id": f"call-validation-{branch_id}",
                    }),
                    json.dumps({
                        "record_type": "item",
                        "id": f"validation-result-{branch_id}",
                        "type": "function_call_output",
                        "status": "completed",
                        "response_id": response_id,
                        "created_at": marker_start + 21,
                        "call_id": f"call-validation-{branch_id}",
                        "output": json.dumps({
                            "schema": "evidence-package-validation/v1",
                            "valid": True,
                            "evidence_package_id": package["evidence_package_id"],
                            "claim_count": len(package["claims"]),
                            "record_digest": package_digest,
                        }),
                    }),
                ]
            )
        if include_substantive_call and not substantive_after_end:
            rows.extend(substantive_rows)
        rows.extend([
            json.dumps({
                "record_type": "item", "id": f"end-call-{branch_id}",
                "type": "function_call", "status": "completed",
                "response_id": response_id, "created_at": marker_end - 1,
                "model": f"agent:{branch_id}",
                "name": "mark_provider_execution_end",
                "arguments": json.dumps({
                    "branch_id": branch_id, "start_marker_id": start_marker_id,
                }),
                "call_id": end_call_id,
            }),
            json.dumps({
                "record_type": "item", "id": f"end-result-{branch_id}",
                "type": "function_call_output", "status": "completed",
                "response_id": response_id, "created_at": marker_end,
                "call_id": end_call_id,
                "output": json.dumps({
                    "schema": "provider-execution-marker/v1", "phase": "END",
                    "branch_id": branch_id, "marker_id": end_marker_id,
                    "start_marker_id": start_marker_id,
                }),
            }),
        ])
        if include_substantive_call and substantive_after_end:
            rows.extend(substantive_rows)
    rows.append(
        json.dumps({
            "record_type": "item",
            "id": f"item-{branch_id}",
            "type": "message",
            "status": "completed",
            "response_id": response_id,
            "created_by": "assistant",
            "created_at": assistant_time,
            "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(package)}],
        })
    )
    export = "\n".join(rows).encode()
    return _verify_omnigent_session_export(
        export,
        expected_branch_id=branch_id,
        expected_session_id=session_id,
        expected_agent_id=f"agent:{branch_id}",
    )


def test_provider_export_without_execution_markers_fails_closed() -> None:
    with pytest.raises(JournalConflictError, match="execution start marker"):
        _provider_invocation("branch-a", include_markers=False)


def test_provider_export_rejects_substantive_work_after_end_marker() -> None:
    with pytest.raises(JournalConflictError, match="outside execution markers"):
        _provider_invocation("branch-a", substantive_after_end=True)


def test_provider_export_requires_substantive_work_between_markers() -> None:
    with pytest.raises(JournalConflictError, match="direct public-source inspections"):
        _provider_invocation("branch-a", include_substantive_call=False)


def test_provider_export_accepts_named_public_web_search_workaround() -> None:
    verified = _provider_invocation(
        "branch-a", search_tool_name="search_public_web"
    )
    assert [
        item["name"] for item in verified.payload["substantive_tool_calls"]
    ] == [
        "search_public_web",
        "inspect_public_source",
        "inspect_public_source",
        "validate_evidence_package",
    ]
    assert verified.payload["evidence_package_digest"]


def test_provider_export_rejects_search_snippets_without_direct_source_inspection() -> None:
    with pytest.raises(JournalConflictError, match="direct public-source inspections"):
        _provider_invocation(
            "branch-a",
            include_source_inspections=False,
            include_validation=False,
        )


def _bind_provider_receipt(record: dict, provider_invocation) -> dict:
    return record | {
        "provider_session_id": provider_invocation.payload["provider_session_id"],
        "provider_receipt_digest": provider_invocation.payload["receipt_digest"],
        "invocation_id": provider_invocation.payload["provider_session_id"],
        "invocation_status": "COMPLETED",
        "producer_agent_id": provider_invocation.payload["agent_id"],
        "producer_session_id": provider_invocation.payload["provider_session_id"],
        "started_at": provider_invocation.payload["started_at"],
        "completed_at": provider_invocation.payload["completed_at"],
    }


def _provider_append_kwargs(provider_invocation) -> dict:
    payload = provider_invocation.payload
    return {
        "producer_agent_id": payload["agent_id"],
        "producer_session_id": payload["provider_session_id"],
        "invocation_id": payload["provider_session_id"],
        "invocation_status": "COMPLETED",
        "provider_invocation": provider_invocation,
        "invocation_started_at": payload["started_at"],
        "invocation_completed_at": payload["completed_at"],
    }


def _feasibility(objective_digest: str) -> dict:
    return {
        "schema": "feasibility-check/v1",
        "feasibility_check_id": "feasible-1",
        "question_id": "q-1",
        "objective_confirmation_digest": objective_digest,
        "checked_by": "human:test",
        "checked_at": "2026-10-03T12:01:00Z",
        "checks": {
            key: {"status": "PASS", "evidence": f"Verified {key}."}
            for key in ("access", "identity", "license", "privacy", "api", "compute")
        },
        "overall_status": "PASS",
        "fallback": "Use the licensed local fixture after separate confirmation.",
    }


def _candidates(objective: dict) -> dict:
    def candidate(identifier: str) -> dict:
        return {
            "experiment_id": identifier, "method": f"Method {identifier}",
            "baseline": "Matched baseline", "controls": ["fixed split"],
            "inputs": ["openml-task-59/dataset-61"],
            "parameters": {
                "max_trials_per_arm": 4,
                "max_seconds_per_arm": 300,
                "threshold": 0.9,
                "quality_noninferiority_margin": 0,
            },
            "random_seeds": [7], "metrics": ["trials_to_threshold", "accuracy"],
            "success_threshold": "trials needed to reach accuracy >= 0.9",
            "expected_learning": "Whether trial selection helps",
            "estimated_runtime_minutes": 10, "estimated_cost_usd": 0,
            "risk_level": "low",
        }
    return {
        "schema": "experiment-candidates/v1",
        "experiment_candidates_id": f"candidates-{objective['objective_confirmation_id']}",
        "question_id": "q-1",
        "objective_confirmation_digest": objective["record_digest"],
        "hypothesis_id": "hypothesis-1", "primary_metric": "trials_to_threshold",
        "dataset_identity": {
            key: objective["dataset"][key] for key in ("identifier", "version", "digest")
        },
        "resource_bounds": {
            "max_trials": 8, "max_runtime_minutes": 30, "max_cost_usd": 1,
            "compute": objective["execution_scope"]["compute"],
            "network_access": objective["execution_scope"]["network_access"],
            "mutation_permissions": objective["execution_scope"]["mutation_permissions"],
        },
        "risk_tolerance": objective["risk_tolerance"],
        "candidates": [candidate("experiment-1"), candidate("experiment-2")],
        "selected_experiment_id": "experiment-1",
        "selection_rationale": "Best expected learning under matched bounds.",
        "rejected_candidate_rationales": {"experiment-2": "Lower expected learning."},
    }


def _measurement_fields(
    *,
    interventions: int | None = 0,
    cost_usd: float | None = 0,
    workflow_overhead: str = "MEASURED",
) -> dict:
    return {
        "compute_seconds": 1.0,
        "interventions": interventions,
        "cost_usd": cost_usd,
        "token_usage": None,
        "measurement_availability": {
            "workflow_overhead": workflow_overhead,
            "compute_seconds": "MEASURED",
            "human_interventions": (
                "MEASURED" if interventions is not None else "UNAVAILABLE"
            ),
            "cost_usd": "MEASURED" if cost_usd is not None else "UNAVAILABLE",
            "token_usage": "UNAVAILABLE",
        },
    }


def _acceleration_metadata(*, positive: bool) -> dict:
    return {
        "dataset_identity": {
            "identifier": "openml-task-59",
            "version": "active",
            "digest": "a" * 64,
        },
        "timing_scope": "end-to-end-arm-workflow",
        "overall_discovery_speed_claim": positive,
        "decision_latency_seconds": 5.0,
        "decision_timing_source_digest": "d" * 64,
        "updated_decision_digest": "c" * 64,
        "matched_controls_digest": "e" * 64,
        "endpoint_rules": {"attempt": "Every attempted fit counts."},
    }


def test_objective_confirmation_digest_is_stable_and_binds_question() -> None:
    question = validate_record(_question())
    objective = validate_record(_objective(question))
    assert objective["objective_confirmation_digest"] == objective["record_digest"]
    assert len(objective["record_digest"]) == 64

    invalid = _objective(question)
    invalid["question_digest"] = "not-a-digest"
    with pytest.raises(RecordValidationError, match="question_digest"):
        validate_record(invalid)


def test_question_requires_intended_scientific_use() -> None:
    question = _question()
    del question["intended_scientific_use"]
    with pytest.raises(RecordValidationError, match="intended_scientific_use"):
        validate_record(question)


def test_candidate_contract_carries_complete_confirmed_scope() -> None:
    question = validate_record(_question())
    objective = validate_record(_objective(question))
    portfolio = _candidates(objective)
    del portfolio["resource_bounds"]["network_access"]
    with pytest.raises(RecordValidationError, match="network_access"):
        validate_record(portfolio)
    portfolio = _candidates(objective)
    portfolio["risk_tolerance"]["level"] = "high"
    with pytest.raises(RecordValidationError, match="risk_level"):
        validate_record(portfolio)


def test_external_evidence_cannot_masquerade_as_a_measurement() -> None:
    claim = _evidence("b" * 64)["claims"][0]
    claim["claim_type"] = "observed-measurement"
    with pytest.raises(RecordValidationError, match="experiment-result"):
        validate_record(_evidence("b" * 64) | {"claims": [claim]})


def test_feasibility_status_must_match_every_mandatory_gate() -> None:
    record = _feasibility("b" * 64)
    record["checks"]["license"]["status"] = "FAIL"
    with pytest.raises(RecordValidationError, match="overall_status"):
        validate_record(record)


def test_any_failed_feasibility_gate_blocks_candidates(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    passed = journal.append(
        _feasibility(objective["record_digest"]), source="operator",
        links=((objective["record_digest"], "checks-feasibility"),),
    )
    failed_raw = _feasibility(objective["record_digest"]) | {
        "feasibility_check_id": "feasible-failed",
        "checked_at": "2026-10-03T12:02:00Z",
    }
    failed_raw["checks"]["api"] = {
        "status": "FAIL", "evidence": "API unavailable."
    }
    failed_raw["overall_status"] = "FAIL"
    failed = journal.append(
        failed_raw, source="operator",
        links=((objective["record_digest"], "checks-feasibility"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    hypotheses = journal.append({
        "schema": "hypothesis-portfolio/v1",
        "hypothesis_portfolio_id": "hypotheses-fail-gate",
        "question_id": "q-1",
        "objective_confirmation_digest": objective["record_digest"],
        "hypotheses": [{
            "hypothesis_id": "hypothesis-1", "statement": "Falsifiable statement.",
            "prediction": "Observable prediction.",
            "falsification_condition": "Observable counter-result.",
            "supporting_evidence_ids": [evidence["claims"][0]["evidence_id"]],
            "competing_explanations": ["Noise"], "uncertainty": "One task",
        }],
    }, source="scientist", links=((evidence["record_digest"], "supports-hypothesis"),))
    with pytest.raises(JournalConflictError, match="failed feasibility"):
        journal.append(
            _candidates(objective), source="designer",
            links=((hypotheses["record_digest"], "tests-hypothesis"),
                   (passed["record_digest"], "enables-candidates"),
                   (failed["record_digest"], "blocks-candidates")),
        )


def test_parallel_reconciliation_requires_real_half_open_overlap() -> None:
    reconciliation = {
        "schema": "branch-reconciliation/v1",
        "reconciliation_id": "reconcile-1",
        "question_id": "q-1",
        "objective_confirmation_digest": "b" * 64,
        "branch_digests": ["c" * 64, "d" * 64],
        "agreements": ["Both branches identify the task."],
        "conflicts": [],
        "unresolved_questions": [],
        "reconciled_evidence_ids": ["claim-a", "claim-b"],
        "parallel_status": "MET",
        "overlapping_branch_pairs": [["branch-a", "branch-b"]],
    }
    assert validate_record(reconciliation)["parallel_status"] == "MET"
    reconciliation["overlapping_branch_pairs"] = []
    with pytest.raises(RecordValidationError, match="overlapping"):
        validate_record(reconciliation)


def test_parallel_met_requires_completed_independent_invocations_and_evidence(
    tmp_path: Path,
) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    packages = [
        journal.append(
            _evidence(objective["record_digest"], f"evidence-{name}"),
            source=f"agent:{name}",
            links=((objective["record_digest"], "authorizes-evidence"),),
        )
        for name in ("a", "b")
    ]
    branches = []
    for index, name in enumerate(("a", "b")):
        provider = _provider_invocation(
            f"branch-{name}", session_id="conv-shared"
        )
        branch = journal.append(
            _bind_provider_receipt(
                _branch(
                    objective["record_digest"], packages[index]["record_digest"],
                    f"branch-{name}", f"2026-10-03T12:0{index + 1}:00Z",
                    f"2026-10-03T12:0{index + 3}:00Z",
                ),
                provider,
            ),
            source=f"agent:{name}",
            links=((packages[index]["record_digest"], "records-branch"),),
            **_provider_append_kwargs(provider),
        )
        branches.append(branch)
    with pytest.raises(JournalConflictError, match="distinct producer sessions"):
        journal.append({
            "schema": "branch-reconciliation/v1", "reconciliation_id": "reconcile-shared",
            "question_id": "q-1", "objective_confirmation_digest": objective["record_digest"],
            "branch_digests": [item["record_digest"] for item in branches],
            "agreements": [], "conflicts": [], "unresolved_questions": [],
            "reconciled_evidence_ids": [
                packages[0]["claims"][0]["evidence_id"],
                packages[1]["claims"][0]["evidence_id"],
            ],
            "parallel_status": "MET",
            "overlapping_branch_pairs": [["branch-a", "branch-b"]],
        }, source="director", links=tuple(
            (branch["record_digest"], "reconciled-by") for branch in branches
        ))


def test_local_wrapper_timing_cannot_replace_provider_attestation(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    record = _branch(
        objective["record_digest"], evidence["record_digest"], "branch-a",
        "2026-10-03T12:01:00Z", "2026-10-03T12:03:00Z",
    )
    with pytest.raises(JournalConflictError, match="verified Omnigent provider"):
        journal.append(
            record, source="agent", links=((evidence["record_digest"], "records-branch"),),
            producer_session_id="session:a", producer_agent_id="agent:branch-a",
            invocation_id="invocation:branch-a", invocation_status="COMPLETED",
            invocation_started_at="2026-10-03T12:01:00Z",
            invocation_completed_at="2026-10-03T12:03:00Z",
        )
    assert journal.find("parallel-branch/v1", "branch-a") is None
    with pytest.raises(JournalConflictError, match="verified Omnigent provider"):
        journal.append(
            record, source="agent", links=((evidence["record_digest"], "records-branch"),),
            producer_session_id="session:a", producer_agent_id="agent:branch-a",
            invocation_id="invocation:branch-a", invocation_status="COMPLETED",
            provider_invocation={"forged": True},  # type: ignore[arg-type]
            invocation_started_at="2026-10-03T12:01:00Z",
            invocation_completed_at="2026-10-03T12:03:00Z",
        )


def test_hermetic_provider_marker_export_earns_verified_provider_provenance(
    tmp_path: Path,
) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    provider = _provider_invocation("branch-a")
    stored = journal.append(
        _bind_provider_receipt(
            _branch(
                objective["record_digest"], evidence["record_digest"], "branch-a",
                provider.payload["started_at"], provider.payload["completed_at"],
            ),
            provider,
        ),
        source="omnigent:evidence-researcher",
        links=((evidence["record_digest"], "records-branch"),),
        **_provider_append_kwargs(provider),
    )
    metadata = journal.record_metadata(stored["record_digest"])
    assert metadata["provider_session_id"] == "conv-branch-a"
    assert metadata["provider_receipt_digest"] == provider.payload["receipt_digest"]
    assert provider.payload["interval_source"] == "provider-execution-marker-results/v1"
    assert provider.payload["execution_start_call_id"] == "call-start-branch-a"
    assert provider.payload["execution_end_call_id"] == "call-end-branch-a"


def test_reopen_revalidates_persisted_provider_receipt(tmp_path: Path) -> None:
    database = tmp_path / "journal.sqlite3"
    journal = ResearchJournal(database)
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    provider = _provider_invocation("branch-a")
    stored = journal.append(
        _bind_provider_receipt(
            _branch(
                objective["record_digest"], evidence["record_digest"], "branch-a",
                provider.payload["started_at"], provider.payload["completed_at"],
            ),
            provider,
        ),
        source="omnigent:evidence-researcher",
        links=((evidence["record_digest"], "records-branch"),),
        **_provider_append_kwargs(provider),
    )

    # A fresh journal object can verify the persisted receipt without the
    # process-authentication object used during append.
    reopened = ResearchJournal(database)
    assert reopened.reconstruct_chain("q-1")["question_id"] == "q-1"

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE records SET provider_receipt_json=? WHERE record_digest=?",
            (json.dumps({"tampered": True}), stored["record_digest"]),
        )
    with pytest.raises(JournalConflictError, match="provider receipt.*damaged"):
        ResearchJournal(database).reconstruct_chain("q-1")


def test_acceleration_summary_preserves_censoring_and_separates_forecasts() -> None:
    endpoint = {
        "schema": "acceleration-summary/v1",
        "acceleration_summary_id": "acceleration-1",
        "question_id": "q-1",
        "objective_confirmation_digest": "b" * 64,
        "experiment_id": "experiment-1",
        "result_digest": "c" * 64,
        "primary_metric": "trials_to_threshold",
        **_acceleration_metadata(positive=False),
        "threshold_predeclared": True,
        "matched_conditions": True,
        "arms": {
            "baseline": {
                "trial_budget": 4, "trials_attempted": 4,
                "trials_to_threshold": {
                    "value": None, "censored": True, "lower_bound_exclusive": 4
                },
                "elapsed_to_threshold_seconds": None, "total_elapsed_seconds": 40,
                "best_metric": 0.89,
                **_measurement_fields(),
            },
            "proposed": {
                "trial_budget": 4, "trials_attempted": 3,
                "trials_to_threshold": {
                    "value": 3, "censored": False, "lower_bound_exclusive": None
                },
                "elapsed_to_threshold_seconds": 35, "total_elapsed_seconds": 35,
                "best_metric": 0.91,
                **_measurement_fields(),
            },
        },
        "trial_count_rule": "Every attempted fit counts.",
        "formula": "baseline / proposed only when both reach threshold",
        "outcome": "LOWER_BOUND_ONLY",
        "observed_trial_speedup": None,
        "trial_speedup_lower_bound": 4 / 3,
        "observed_time_speedup": None,
        "overhead_included": True,
        "quality_non_inferiority": {
            "margin": 0.01, "higher_is_better": True, "passed": True
        },
        "claim_blockers": ["baseline_censored", "time_speedup_not_estimable"],
        "threats_to_validity": ["single task"],
        "scaling_analysis": {
            "remaining_bottlenecks": ["approval latency"],
            "parallelizable_or_automatable": ["retrieval"],
            "evidence_still_needed": ["more tasks"],
            "conditions_for_approaching_10x": ["safe parallel work"],
            "boundaries": ["forecast is not observed"],
            "scenarios": {
                name: {
                    "assumptions": ["declared assumption"],
                    "projected_speedup": speedup,
                    "boundaries": ["requires prospective validation"],
                }
                for name, speedup in (
                    ("conservative", 1.1), ("expected", 2.0), ("optimistic", 10.0)
                )
            },
        },
    }
    assert validate_record(endpoint)["outcome"] == "LOWER_BOUND_ONLY"
    endpoint["observed_trial_speedup"] = 4 / 3
    with pytest.raises(RecordValidationError, match="censored"):
        validate_record(endpoint)


def test_acceleration_recomputes_time_quality_and_false_positive_claims() -> None:
    record = {
        "schema": "acceleration-summary/v1", "acceleration_summary_id": "a-2",
        "question_id": "q-1", "objective_confirmation_digest": "b" * 64,
        "experiment_id": "e-1", "result_digest": "c" * 64,
        "primary_metric": "trials_to_threshold", "threshold_predeclared": True,
        **_acceleration_metadata(positive=True),
        "matched_conditions": True, "overhead_included": True,
        "arms": {
            "baseline": {
                "trial_budget": 4, "trials_attempted": 4,
                "trials_to_threshold": {"value": 4, "censored": False,
                                        "lower_bound_exclusive": None},
                "elapsed_to_threshold_seconds": 20, "total_elapsed_seconds": 20,
                "best_metric": 0.90,
                **_measurement_fields(),
            },
            "proposed": {
                "trial_budget": 4, "trials_attempted": 2,
                "trials_to_threshold": {"value": 2, "censored": False,
                                        "lower_bound_exclusive": None},
                "elapsed_to_threshold_seconds": 25, "total_elapsed_seconds": 25,
                "best_metric": 0.88,
                **_measurement_fields(),
            },
        },
        "trial_count_rule": "Every fit counts.", "formula": "baseline / proposed",
        "observed_trial_speedup": 2.0, "trial_speedup_lower_bound": None,
        "observed_time_speedup": 1.25,
        "quality_non_inferiority": {
            "margin": 0.01, "higher_is_better": True, "passed": True
        },
        "claim_blockers": [], "outcome": "POSITIVE",
        "threats_to_validity": ["single task"],
        "scaling_analysis": {
            "remaining_bottlenecks": ["review"],
            "parallelizable_or_automatable": ["retrieval"],
            "evidence_still_needed": ["more tasks"],
            "conditions_for_approaching_10x": ["safe concurrency"],
            "boundaries": ["forecast only"],
            "scenarios": {
                name: {"assumptions": ["assumption"], "projected_speedup": value,
                       "boundaries": ["not observed"]}
                for name, value in (("conservative", 1.0), ("expected", 2.0),
                                    ("optimistic", 10.0))
            },
        },
    }
    with pytest.raises(RecordValidationError, match="observed_time_speedup|passed"):
        validate_record(record)


def test_journal_migrates_old_database_and_preserves_producer_provenance(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE records (
              record_digest TEXT PRIMARY KEY, schema_name TEXT NOT NULL,
              primary_id TEXT NOT NULL, payload_json TEXT NOT NULL,
              source TEXT NOT NULL, recorded_at TEXT NOT NULL,
              UNIQUE(schema_name, primary_id));
            CREATE TABLE record_links (
              parent_digest TEXT NOT NULL, child_digest TEXT NOT NULL,
              relation TEXT NOT NULL,
              PRIMARY KEY(parent_digest, child_digest, relation));
            CREATE TABLE experiment_bindings (
              experiment_id TEXT PRIMARY KEY, experiment_digest TEXT NOT NULL,
              approval_digest TEXT NOT NULL, task_card_path TEXT NOT NULL,
              lane_id TEXT, run_id TEXT, status TEXT NOT NULL, updated_at TEXT NOT NULL);
            """
        )

    journal = ResearchJournal(path)
    stored = journal.append(
        _question(),
        source="omnigent:research-director",
        producer_session_id="session-1",
        producer_agent_id="research-director",
    )
    metadata = journal.record_metadata(stored["record_digest"])
    assert metadata["producer_session_id"] == "session-1"
    assert metadata["producer_agent_id"] == "research-director"


def test_pre_authority_v1_rows_are_readable_but_cannot_gain_authority(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="legacy-import")
    legacy_hypotheses = {
        "schema": "hypothesis-portfolio/v1", "question_id": "q-1",
        "hypotheses": [{
            "hypothesis_id": "legacy-hypothesis", "statement": "Legacy statement",
            "prediction": "Legacy prediction", "falsification_condition": "Legacy falsifier",
            "supporting_evidence_ids": [],
        }],
    }
    legacy_candidates = {
        "schema": "experiment-candidates/v1", "question_id": "q-1",
        "hypothesis_id": "legacy-hypothesis",
        "candidates": [
            {
                "experiment_id": identifier, "method": "Legacy method",
                "baseline": "Legacy baseline", "parameters": {},
                "metrics": ["accuracy"], "success_threshold": "Fixed threshold",
                "expected_learning": "Legacy learning",
            }
            for identifier in ("legacy-a", "legacy-b")
        ],
        "selected_experiment_id": "legacy-a",
        "selection_rationale": "Legacy rationale",
    }
    rows = []
    for schema_name, primary_id, payload in (
        ("hypothesis-portfolio/v1", "q-1", legacy_hypotheses),
        ("experiment-candidates/v1", "q-1", legacy_candidates),
    ):
        normalized = payload | {"record_digest": record_digest(payload)}
        rows.append(normalized)
        with sqlite3.connect(journal.path) as connection:
            connection.execute(
                """INSERT INTO records
                   (record_digest, schema_name, primary_id, payload_json, source, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (normalized["record_digest"], schema_name, primary_id,
                 json.dumps(normalized), "legacy", "2025-01-01T00:00:00Z"),
            )
    with sqlite3.connect(journal.path) as connection:
        connection.execute(
            "INSERT INTO record_links VALUES (?, ?, ?)",
            (question["record_digest"], rows[0]["record_digest"], "legacy-hypothesis"),
        )
        connection.execute(
            "INSERT INTO record_links VALUES (?, ?, ?)",
            (rows[0]["record_digest"], rows[1]["record_digest"], "legacy-candidates"),
        )

    assert validate_stored_record(rows[0])["question_id"] == "q-1"
    assert journal.find("experiment-candidates/v1", "q-1")["selected_experiment_id"] == "legacy-a"
    chain = journal.reconstruct_chain("q-1")
    assert chain["legacy_record_digests"] == sorted(
        row["record_digest"] for row in rows
    )
    with pytest.raises(RecordValidationError, match="hypothesis_portfolio_id"):
        validate_record(rows[0])
    with pytest.raises(RecordValidationError, match="experiment_candidates_id"):
        journal.append(legacy_candidates, source="new-write")
    with pytest.raises(JournalConflictError, match="legacy.*readable"):
        journal.learning_receipt("q-1")


def test_journal_lists_questions_in_recorded_order_and_reconstructs_full_chain(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    q1 = journal.append(_question(), source="human")
    q2 = journal.append(_question() | {"question_id": "q-2", "question": "Second?"}, source="human")
    objective = journal.append(
        _objective(q1),
        source="human",
        links=((q1["record_digest"], "confirms-objective"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]),
        source="omnigent:evidence-researcher",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )

    assert [row["question_id"] for row in journal.list_questions()] == ["q-1", "q-2"]
    chain = journal.reconstruct_chain("q-1")
    assert {row["record_digest"] for row in chain["records"]} == {
        q1["record_digest"], objective["record_digest"], evidence["record_digest"]
    }
    assert chain["links"] == sorted(
        chain["links"], key=lambda edge: (edge["parent_digest"], edge["relation"], edge["child_digest"])
    )


def test_journal_rejects_cross_question_objective_authority(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human", links=((question["record_digest"], "confirms-objective"),)
    )
    wrong = _evidence(objective["record_digest"])
    wrong["question_id"] = "q-other"
    with pytest.raises(JournalConflictError, match="question"):
        journal.append(wrong, source="agent", links=((objective["record_digest"], "authorizes-evidence"),))


def test_evidence_ids_are_globally_unique_within_question(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    first = journal.append(
        _evidence(objective["record_digest"], "package-a"), source="agent:a",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    duplicate = _evidence(objective["record_digest"], "package-b")
    duplicate["claims"][0]["evidence_id"] = first["claims"][0]["evidence_id"]
    with pytest.raises(JournalConflictError, match="evidence_id.*question"):
        journal.append(
            duplicate, source="agent:b",
            links=((objective["record_digest"], "authorizes-evidence"),),
        )


def test_reconfirmation_can_regenerate_portfolio_and_candidates(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    previous_objective: dict | None = None
    candidate_records = []
    for index in (1, 2):
        raw_objective = _objective(question) | {
            "objective_confirmation_id": f"objective-{index}",
            "confirmed_at": f"2026-10-03T12:{index:02d}:00Z",
        }
        links = [(question["record_digest"], "confirms-objective")]
        if previous_objective is not None:
            raw_objective["supersedes_objective_confirmation_digest"] = previous_objective["record_digest"]
            links.append((previous_objective["record_digest"], "supersedes-objective"))
        objective = journal.append(raw_objective, source="human", links=links)
        evidence = journal.append(
            _evidence(objective["record_digest"], f"package-{index}"), source="agent",
            links=((objective["record_digest"], "authorizes-evidence"),),
        )
        hypothesis = journal.append({
            "schema": "hypothesis-portfolio/v1",
            "hypothesis_portfolio_id": f"hypotheses-{index}",
            "question_id": "q-1",
            "objective_confirmation_digest": objective["record_digest"],
            "hypotheses": [{
                "hypothesis_id": "hypothesis-1", "statement": "A falsifiable statement.",
                "prediction": "A measurable prediction.",
                "falsification_condition": "A measurable falsifier.",
                "supporting_evidence_ids": [evidence["claims"][0]["evidence_id"]],
                "competing_explanations": [], "uncertainty": "Known uncertainty.",
            }],
        }, source="scientist", links=((evidence["record_digest"], "supports-hypothesis"),))
        feasibility = journal.append(
            _feasibility(objective["record_digest"]) | {
                "feasibility_check_id": f"feasibility-{index}"
            }, source="operator", links=((objective["record_digest"], "checks-feasibility"),),
        )
        candidates = _candidates(objective)
        candidate_records.append(journal.append(
            candidates, source="designer",
            links=((hypothesis["record_digest"], "tests-hypothesis"),
                   (feasibility["record_digest"], "enables-candidates")),
        ))
        previous_objective = objective
    assert candidate_records[0]["record_digest"] != candidate_records[1]["record_digest"]


def test_candidate_dataset_version_and_digest_must_match_objective(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    feasibility = journal.append(
        _feasibility(objective["record_digest"]), source="operator",
        links=((objective["record_digest"], "checks-feasibility"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    hypothesis = journal.append({
        "schema": "hypothesis-portfolio/v1",
        "hypothesis_portfolio_id": "hypotheses-dataset-test",
        "question_id": "q-1", "objective_confirmation_digest": objective["record_digest"],
        "hypotheses": [{
            "hypothesis_id": "hypothesis-1", "statement": "A falsifiable statement.",
            "prediction": "A prediction.", "falsification_condition": "A falsifier.",
            "supporting_evidence_ids": [evidence["claims"][0]["evidence_id"]],
            "competing_explanations": [], "uncertainty": "Known uncertainty.",
        }],
    }, source="scientist", links=((evidence["record_digest"], "supports-hypothesis"),))
    portfolio = _candidates(objective)
    portfolio["dataset_identity"]["version"] = "different-version"
    with pytest.raises(JournalConflictError, match="dataset"):
        journal.append(
            portfolio, source="designer",
            links=((feasibility["record_digest"], "enables-candidates"),
                   (hypothesis["record_digest"], "tests-hypothesis")),
        )
    portfolio["dataset_identity"] = {
        key: objective["dataset"][key] for key in ("identifier", "version", "digest")
    }
    portfolio["hypothesis_id"] = "unknown-hypothesis"
    with pytest.raises(JournalConflictError, match="hypothesis_id.*exactly once"):
        journal.append(
            portfolio, source="designer",
            links=((feasibility["record_digest"], "enables-candidates"),
                   (hypothesis["record_digest"], "tests-hypothesis")),
        )


def test_binding_authority_and_task_card_digest_are_immutable(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    journal.initialize()
    approval = {
        "schema": "human-approval/v1", "approval_id": "approval-1",
        "experiment_id": "experiment-1", "experiment_digest": "c" * 64,
        "objective_confirmation_digest": "b" * 64,
        "approved": True, "approved_by": "human:test",
        "approved_at": "2026-10-03T12:05:00Z",
        "scope": "execute-exact-experiment", "constraints": [],
    }
    normalized_approval = validate_record(approval)
    # Seed a valid immutable approval row as though it came from the complete
    # upstream chain; this test isolates lifecycle-binding invariants.
    with sqlite3.connect(journal.path) as connection:
        connection.execute(
            """INSERT INTO records
               (record_digest, schema_name, primary_id, payload_json, source,
                recorded_at, producer_session_id, producer_agent_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                normalized_approval["record_digest"], "human-approval/v1", "approval-1",
                json.dumps(normalized_approval), "human", "2026-10-03T12:05:00Z",
                "session:test", "human:test",
            ),
        )
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"research_authority": {
        "objective_confirmation_digest": "b" * 64,
        "experiment_digest": "c" * 64,
        "approval_digest": normalized_approval["record_digest"],
    }}), encoding="utf-8")
    task_digest = hashlib.sha256(task.read_bytes()).hexdigest()
    kwargs = {
        "experiment_id": "experiment-1",
        "experiment_digest": "c" * 64,
        "approval_digest": normalized_approval["record_digest"],
        "objective_confirmation_digest": "b" * 64,
        "task_card_digest": task_digest,
        "task_card_path": task,
    }
    journal.bind_experiment(**kwargs)
    journal.bind_experiment(
        **kwargs, status="LAUNCHING", lane_id="lane-1", run_id="run-1"
    )
    journal.bind_experiment(
        **kwargs, status="LAUNCHED", lane_id="lane-1", run_id="run-1"
    )
    assert journal.experiment_status("experiment-1")["task_card_digest"] == task_digest
    with pytest.raises(JournalConflictError, match="task_card_digest|immutable authority"):
        journal.bind_experiment(**(kwargs | {"task_card_digest": "e" * 64}))
    with pytest.raises(JournalConflictError, match="lifecycle"):
        journal.bind_experiment(**kwargs, status="STAGED", lane_id="lane-1")
    with pytest.raises(JournalConflictError, match="lane_id"):
        journal.bind_experiment(**kwargs, status="RUNNING", lane_id="lane-2")
    journal.bind_experiment(**kwargs, status="RUNNING", lane_id="lane-1", run_id="run-1")
    with pytest.raises(JournalConflictError, match="run_id"):
        journal.bind_experiment(
            **kwargs, status="COMPLETED", lane_id="lane-1", run_id="run-2"
        )


def test_task_card_authority_must_be_structured_not_incidental_text(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    journal.initialize()
    approval = validate_record({
        "schema": "human-approval/v1", "approval_id": "approval-1",
        "experiment_id": "experiment-1", "experiment_digest": "c" * 64,
        "objective_confirmation_digest": "b" * 64, "approved": True,
        "approved_by": "human:test", "approved_at": "2026-10-03T12:05:00Z",
        "scope": "execute-exact-experiment", "constraints": [],
    })
    with sqlite3.connect(journal.path) as connection:
        connection.execute(
            """INSERT INTO records
               (record_digest, schema_name, primary_id, payload_json, source,
                recorded_at, producer_session_id, producer_agent_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (approval["record_digest"], "human-approval/v1", "approval-1",
             json.dumps(approval), "human", "2026-10-03T12:05:00Z",
             "session:test", "human:test"),
        )
    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "research_authority": {
            "objective_confirmation_digest": "0" * 64,
            "experiment_digest": "0" * 64,
            "approval_digest": "0" * 64,
        },
        "task": f"incidental {'b' * 64} {'c' * 64} {approval['record_digest']}",
    }), encoding="utf-8")
    with pytest.raises(JournalConflictError, match="structured authority"):
        journal.bind_experiment(
            experiment_id="experiment-1", experiment_digest="c" * 64,
            approval_digest=approval["record_digest"],
            objective_confirmation_digest="b" * 64,
            task_card_digest=hashlib.sha256(task.read_bytes()).hexdigest(),
            task_card_path=task,
        )


def test_binding_never_infers_or_backfills_missing_authority(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    journal.initialize()
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"research_authority": {
        "objective_confirmation_digest": "b" * 64,
        "experiment_digest": "c" * 64,
        "approval_digest": "d" * 64,
    }}), encoding="utf-8")
    with pytest.raises(JournalConflictError, match="explicit.*objective_confirmation_digest"):
        journal.bind_experiment(
            experiment_id="experiment-1", experiment_digest="c" * 64,
            approval_digest="d" * 64, objective_confirmation_digest=None,
            task_card_digest=hashlib.sha256(task.read_bytes()).hexdigest(),
            task_card_path=task,
        )
    with pytest.raises(JournalConflictError, match="explicit.*task_card_digest"):
        journal.bind_experiment(
            experiment_id="experiment-1", experiment_digest="c" * 64,
            approval_digest="d" * 64,
            objective_confirmation_digest="b" * 64,
            task_card_digest=None, task_card_path=task,
        )


def test_learning_receipt_is_a_deterministic_projection(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    evidence_b = journal.append(
        _evidence(objective["record_digest"], "evidence-b"), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    provider_a = _provider_invocation("branch-a")
    branch_a = journal.append(
        _bind_provider_receipt(
            _branch(objective["record_digest"], evidence["record_digest"], "branch-a",
                    provider_a.payload["started_at"], provider_a.payload["completed_at"]),
            provider_a,
        ),
        source="agent", links=((evidence["record_digest"], "records-branch"),),
        **_provider_append_kwargs(provider_a),
    )
    provider_b = _provider_invocation("branch-b")
    branch_b_record = _bind_provider_receipt(
        _branch(
            objective["record_digest"], evidence_b["record_digest"], "branch-b",
            provider_b.payload["started_at"], provider_b.payload["completed_at"],
        ),
        provider_b,
    )
    branch_b = journal.append(
        branch_b_record, source="agent", links=((evidence_b["record_digest"], "records-branch"),),
        **_provider_append_kwargs(provider_b),
    )
    reconciliation = journal.append(
        {
            "schema": "branch-reconciliation/v1",
            "reconciliation_id": "reconcile-1",
            "question_id": "q-1",
            "objective_confirmation_digest": objective["record_digest"],
            "branch_digests": [branch_b["record_digest"], branch_a["record_digest"]],
            "agreements": ["Task identity agrees."], "conflicts": [],
            "unresolved_questions": [], "reconciled_evidence_ids": [
                "claim-evidence-a", "claim-evidence-b"
            ],
            "parallel_status": "MET", "overlapping_branch_pairs": [["branch-a", "branch-b"]],
        },
        source="omnigent:research-director",
        links=((branch_a["record_digest"], "reconciled-by"),
               (branch_b["record_digest"], "reconciled-by")),
    )

    receipt1 = journal.learning_receipt("q-1", final=False)
    receipt2 = journal.learning_receipt("q-1", final=False)
    assert receipt1 == receipt2
    assert receipt1["reconciliation_digest"] == reconciliation["record_digest"]
    assert receipt1["evidence_package_digests"] == sorted(
        [evidence["record_digest"], evidence_b["record_digest"]]
    )
    assert receipt1["receipt_digest"] == record_digest(receipt1)


def test_overlapping_request_and_session_windows_cannot_hide_serial_marker_intervals(
    tmp_path: Path,
) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    evidence_by_branch = {
        "branch-a": evidence,
        "branch-b": journal.append(
            _evidence(objective["record_digest"], "evidence-b"), source="agent",
            links=((objective["record_digest"], "authorizes-evidence"),),
        ),
    }
    branches = []
    for branch_id, marker_start, marker_end in (
        ("branch-a", 1791028860, 1791028920),
        ("branch-b", 1791028920, 1791028980),
    ):
        provider = _provider_invocation(
            branch_id,
            # Both request/response and mutable metadata windows overlap.
            # Only the serial execution-marker intervals are authoritative.
            request_created_at=1791028800,
            response_created_at=1791029040,
            marker_started_at=marker_start,
            marker_completed_at=marker_end,
            session_created_at=1791028700,
            session_updated_at=1791029300,
        )
        branches.append(journal.append(
            _bind_provider_receipt(
                _branch(
                    objective["record_digest"], evidence_by_branch[branch_id]["record_digest"],
                    branch_id, provider.payload["started_at"], provider.payload["completed_at"],
                ),
                provider,
            ),
            source="agent", links=((evidence_by_branch[branch_id]["record_digest"], "records-branch"),),
            **_provider_append_kwargs(provider),
        ))
    with pytest.raises(JournalConflictError, match="trusted.*overlap|authoritative intervals"):
        journal.append({
            "schema": "branch-reconciliation/v1", "reconciliation_id": "r-1",
            "question_id": "q-1",
            "objective_confirmation_digest": objective["record_digest"],
            "branch_digests": [item["record_digest"] for item in branches],
            "agreements": [], "conflicts": [], "unresolved_questions": [],
            "reconciled_evidence_ids": ["claim-evidence-a", "claim-evidence-b"],
            "parallel_status": "MET",
            "overlapping_branch_pairs": [["branch-a", "branch-b"]],
        }, source="director", links=tuple(
            (item["record_digest"], "reconciled-by") for item in branches
        ))


def test_receipt_selects_only_unsuperseded_objective(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    first = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    replacement_record = _objective(question) | {
        "objective_confirmation_id": "objective-2",
        "confirmed_at": "2026-10-03T12:10:00Z",
        "supersedes_objective_confirmation_digest": first["record_digest"],
    }
    replacement = journal.append(
        replacement_record, source="human",
        links=((question["record_digest"], "confirms-objective"),
               (first["record_digest"], "supersedes-objective")),
    )
    receipt = journal.learning_receipt("q-1")
    assert receipt["objective_confirmation_digest"] == replacement["record_digest"]


def test_final_receipt_requires_terminal_binding_with_matching_run(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(_question(), source="human")
    objective = journal.append(
        _objective(question), source="human",
        links=((question["record_digest"], "confirms-objective"),),
    )
    feasibility = journal.append(
        _feasibility(objective["record_digest"]), source="operator",
        links=((objective["record_digest"], "checks-feasibility"),),
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="agent",
        links=((objective["record_digest"], "authorizes-evidence"),),
    )
    evidence_by_branch = {
        "branch-a": evidence,
        "branch-b": journal.append(
            _evidence(objective["record_digest"], "evidence-b"), source="agent",
            links=((objective["record_digest"], "authorizes-evidence"),),
        ),
    }
    branches = []
    for branch_id, start, end in (
        ("branch-a", "2026-10-03T12:01:00Z", "2026-10-03T12:03:00Z"),
        ("branch-b", "2026-10-03T12:02:00Z", "2026-10-03T12:04:00Z"),
    ):
        provider = _provider_invocation(branch_id)
        branches.append(journal.append(
            _bind_provider_receipt(
                _branch(
                    objective["record_digest"], evidence_by_branch[branch_id]["record_digest"],
                    branch_id, provider.payload["started_at"], provider.payload["completed_at"],
                ),
                provider,
            ),
            source="agent", links=((evidence_by_branch[branch_id]["record_digest"], "records-branch"),),
            **_provider_append_kwargs(provider),
        ))
    reconciliation = journal.append({
        "schema": "branch-reconciliation/v1", "reconciliation_id": "reconcile-final",
        "question_id": "q-1", "objective_confirmation_digest": objective["record_digest"],
        "branch_digests": [item["record_digest"] for item in branches],
        "agreements": ["task identity"], "conflicts": [], "unresolved_questions": [],
        "reconciled_evidence_ids": ["claim-evidence-a", "claim-evidence-b"],
        "parallel_status": "MET",
        "overlapping_branch_pairs": [["branch-a", "branch-b"]],
    }, source="director", links=tuple(
        (item["record_digest"], "reconciled-by") for item in branches
    ))
    hypothesis = journal.append({
        "schema": "hypothesis-portfolio/v1",
        "hypothesis_portfolio_id": "hypotheses-final", "question_id": "q-1",
        "objective_confirmation_digest": objective["record_digest"],
        "hypotheses": [{
            "hypothesis_id": "hypothesis-1", "statement": "Guidance reduces trials.",
            "prediction": "Fewer trials to threshold.",
            "falsification_condition": "No trial reduction.",
            "supporting_evidence_ids": ["claim-evidence-a"],
            "competing_explanations": ["Random variation"], "uncertainty": "One task",
        }],
    }, source="scientist", links=((reconciliation["record_digest"], "supports-hypothesis"),))
    portfolio = journal.append(
        _candidates(objective), source="designer",
        links=((hypothesis["record_digest"], "tests-hypothesis"),
               (feasibility["record_digest"], "enables-candidates")),
    )
    selected_digest = experiment_digest(portfolio)
    review = journal.append({
        "schema": "safety-review/v1", "experiment_id": "experiment-1",
        "experiment_digest": selected_digest,
        "objective_confirmation_digest": objective["record_digest"],
        "verdict": "APPROVAL_REQUIRED", "risks": [], "required_controls": [],
        "prohibited_actions": [], "approval_question": "Approve exact run?",
        "review_limitations": [],
    }, source="reviewer", links=((portfolio["record_digest"], "reviews-selection"),))
    approval = journal.append({
        "schema": "human-approval/v1", "approval_id": "approval-final",
        "experiment_id": "experiment-1", "experiment_digest": selected_digest,
        "objective_confirmation_digest": objective["record_digest"], "approved": True,
        "approved_by": "human:test", "approved_at": "2026-10-03T12:05:00Z",
        "scope": "execute-exact-experiment", "constraints": [],
    }, source="human", links=((review["record_digest"], "approves-after-review"),))
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"research_authority": {
        "objective_confirmation_digest": objective["record_digest"],
        "experiment_digest": selected_digest,
        "approval_digest": approval["record_digest"],
    }}), encoding="utf-8")
    bind = {
        "experiment_id": "experiment-1", "experiment_digest": selected_digest,
        "approval_digest": approval["record_digest"],
        "objective_confirmation_digest": objective["record_digest"],
        "task_card_digest": hashlib.sha256(task.read_bytes()).hexdigest(),
        "task_card_path": task, "lane_id": "lane-1",
    }
    journal.bind_experiment(**bind, status="STAGED")
    journal.bind_experiment(**bind, status="LAUNCHING", run_id="run-1")
    journal.bind_experiment(**bind, status="LAUNCHED", run_id="run-1")
    result_metrics = {
        "trials_to_threshold": {
            "baseline": {"value": 4, "censored": False, "lower_bound_exclusive": None},
            "proposed": {"value": 2, "censored": False, "lower_bound_exclusive": None},
        },
        "accuracy": {"baseline": 0.90, "proposed": 0.91},
        "elapsed_to_threshold_seconds": {"baseline": 40, "proposed": 20},
        "total_elapsed_seconds": {"baseline": 40, "proposed": 20},
        "compute_seconds": {"baseline": 1.0, "proposed": 1.0},
        "interventions": {"baseline": 0, "proposed": 0},
        "cost_usd": {"baseline": 0, "proposed": 0},
        "token_usage": {"baseline": None, "proposed": None},
        "baseline": {
            "attempted_trials": 4,
            "overhead_included": False,
            "measurement_availability": _measurement_fields(
                workflow_overhead="UNAVAILABLE"
            )[
                "measurement_availability"
            ],
        },
        "evidence_guided": {
            "attempted_trials": 2,
            "overhead_included": False,
            "measurement_availability": _measurement_fields(
                workflow_overhead="UNAVAILABLE"
            )[
                "measurement_availability"
            ],
        },
        "acceleration": {
            "matched_controls": True,
            "overhead_included": False,
            "timing_scope": "model-evaluation-only",
            "overall_discovery_speed_claim": False,
            "trial_speedup": 2.0,
            "time_speedup": 2.0,
            "trial_speedup_lower_bound": None,
            "quality_non_inferiority": {
                "margin": 0,
                "higher_is_better": True,
                "passed": True,
            },
            "claim_blockers": ["overhead_missing"],
        },
    }
    result_parameters = {
        "approved_candidate_parameters": selected_experiment(portfolio)["parameters"],
        "observed_preregistration": {
            "primary_metric": "trials_to_threshold",
            "dataset_identity": portfolio["dataset_identity"],
            "split_seed": 7,
            "threshold": 0.9,
            "max_trials_per_arm": 4,
            "max_seconds_per_arm": 300,
            "quality_noninferiority_margin": 0,
            "control_digest": "e" * 64,
            "endpoint_rules": {"attempt": "Every attempted fit counts."},
        },
        "execution_metadata": {
            "measurement_availability": {
                "baseline": _measurement_fields(
                    workflow_overhead="UNAVAILABLE"
                )["measurement_availability"],
                "proposed": _measurement_fields(
                    workflow_overhead="UNAVAILABLE"
                )["measurement_availability"],
            }
        },
    }
    result_record = {
        "schema": "experiment-result/v1", "question_id": "q-1",
        "experiment_id": "experiment-1",
        "experiment_digest": selected_digest,
        "objective_confirmation_digest": objective["record_digest"],
        "approval_digest": approval["record_digest"], "run_id": "run-1",
        "execution_source": "integrated-harness", "code_identity": "commit-1",
        "dataset_identity": portfolio["dataset_identity"],
        "environment_identity": "lock-1", "parameters": result_parameters,
        "primary_metric": "trials_to_threshold", "task_card_digest": bind["task_card_digest"],
        "random_seeds": [7], "metrics": result_metrics,
        "artifact_refs": [{"uri": "artifact://metrics", "kind": "metrics", "digest": "f" * 64}],
        "measurement_support": {key: "f" * 64 for key in result_metrics},
        "started_at": "2026-10-03T12:06:00Z", "completed_at": "2026-10-03T12:08:00Z",
        "status": "PASS", "limitations": [],
    }
    bad_parameters = json.loads(json.dumps(result_parameters))
    bad_parameters["observed_preregistration"]["threshold"] = 0.8
    with pytest.raises(JournalConflictError, match="observed preregistration"):
        journal.append(
            result_record | {"parameters": bad_parameters}, source="harness",
            links=((approval["record_digest"], "authorizes-result"),),
        )
    result = journal.append(
        result_record, source="harness",
        links=((approval["record_digest"], "authorizes-result"),),
    )
    decision_record = {
        "schema": "updated-decision/v1", "question_id": "q-1",
        "objective_confirmation_digest": objective["record_digest"],
        "hypothesis_id": "hypothesis-1", "experiment_id": "experiment-1",
        "run_id": "run-1", "result_digest": result["record_digest"],
        "decision": "support", "rationale": "Observed metric supports the hypothesis.",
        "interpreted_metrics": ["trials_to_threshold", "accuracy"],
        "supporting_evidence_ids": [],
        "remaining_uncertainty": ["single task"],
        "next_experiment": {"question": "Does this replicate?", "rationale": "Reduce uncertainty."},
        "human_review_required": True,
    }
    with pytest.raises(JournalConflictError, match="accepted, ingested"):
        journal.append(
            decision_record,
            source="analyst",
            links=((result["record_digest"], "interprets-result"),),
        )
    journal.bind_experiment(
        **bind,
        status="COMPLETED",
        run_id="run-1",
        acceptance_decided_at="2026-10-03T12:09:00Z",
        acceptance_digest="b" * 64,
    )
    with pytest.raises(JournalConflictError, match="acceptance digest is immutable"):
        journal.bind_experiment(
            **bind,
            status="COMPLETED",
            run_id="run-1",
            acceptance_decided_at="2026-10-03T12:09:00Z",
            acceptance_digest="c" * 64,
        )
    with pytest.raises(RecordValidationError, match="decision_timing"):
        validate_record(decision_record)
    with pytest.raises(JournalConflictError, match="evidence outside"):
        journal.append(
            decision_record | {"supporting_evidence_ids": ["unknown-evidence"]},
            source="analyst", links=((result["record_digest"], "interprets-result"),),
        )
    decision = journal.append(
        decision_record, source="analyst",
        links=((result["record_digest"], "interprets-result"),),
    )
    assert decision["decision_timing"]["result_accepted_at"] == (
        "2026-10-03T12:09:00Z"
    )
    assert decision["decision_timing"]["harness_acceptance_digest"] == "b" * 64
    assert decision["decision_timing_source_digest"] == hashlib.sha256(
        json.dumps(
            decision["decision_timing"],
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(JournalConflictError, match="journal-authored"):
        journal.append(
            decision_record
            | {
                "decision_timing": decision["decision_timing"],
                "decision_timing_source_digest": decision[
                    "decision_timing_source_digest"
                ],
            },
            source="analyst",
            links=((result["record_digest"], "interprets-result"),),
        )
    acceleration_record = {
        "schema": "acceleration-summary/v1", "acceleration_summary_id": "acc-final",
        "question_id": "q-1", "objective_confirmation_digest": objective["record_digest"],
        "experiment_id": "experiment-1", "result_digest": result["record_digest"],
        "updated_decision_digest": decision["record_digest"],
        "primary_metric": "trials_to_threshold", "threshold_predeclared": True,
        **(
            _acceleration_metadata(positive=False)
            | {
                "updated_decision_digest": decision["record_digest"],
                "decision_latency_seconds": decision["decision_timing"][
                    "latency_seconds"
                ],
                "decision_timing_source_digest": decision[
                    "decision_timing_source_digest"
                ],
            }
        ),
        "matched_conditions": True,
        "overhead_included": False,
        "timing_scope": "model-evaluation-only",
        "arms": {
            "baseline": {"trial_budget": 4, "trials_attempted": 4,
                         "trials_to_threshold": {"value": 4, "censored": False,
                                                 "lower_bound_exclusive": None},
                         "elapsed_to_threshold_seconds": 40, "total_elapsed_seconds": 40,
                         "best_metric": 0.90,
                         **_measurement_fields(workflow_overhead="UNAVAILABLE")},
            "proposed": {"trial_budget": 4, "trials_attempted": 2,
                         "trials_to_threshold": {"value": 2, "censored": False,
                                                 "lower_bound_exclusive": None},
                         "elapsed_to_threshold_seconds": 20, "total_elapsed_seconds": 20,
                         "best_metric": 0.91,
                         **_measurement_fields(workflow_overhead="UNAVAILABLE")},
        },
        "trial_count_rule": "Every attempted fit counts.", "formula": "baseline / proposed",
        "observed_trial_speedup": 2.0, "trial_speedup_lower_bound": None,
        "observed_time_speedup": 2.0, "quality_non_inferiority": {
            "margin": 0, "higher_is_better": True, "passed": True,
        }, "claim_blockers": ["overhead_missing"],
        "outcome": "TRIAL_EFFICIENCY_ONLY",
        "threats_to_validity": ["single task"], "scaling_analysis": {
            "remaining_bottlenecks": ["review"], "parallelizable_or_automatable": ["retrieval"],
            "evidence_still_needed": ["more tasks"],
            "conditions_for_approaching_10x": ["safe concurrency"],
            "boundaries": ["forecast only"], "scenarios": {
                name: {"assumptions": ["assumption"], "projected_speedup": speedup,
                       "boundaries": ["not observed"]}
                for name, speedup in (("conservative", 1), ("expected", 2), ("optimistic", 10))
            },
        },
    }
    bad_acceleration = json.loads(json.dumps(acceleration_record))
    bad_acceleration["arms"]["proposed"]["cost_usd"] = 0.5
    with pytest.raises(JournalConflictError, match="measurements differ"):
        journal.append(
            bad_acceleration, source="analyst",
            links=((decision["record_digest"], "summarizes-acceleration"),),
        )
    forged_positive = json.loads(json.dumps(acceleration_record))
    forged_positive.update({
        "overhead_included": True,
        "timing_scope": "end-to-end-arm-workflow",
        "overall_discovery_speed_claim": True,
        "claim_blockers": [],
        "outcome": "POSITIVE",
    })
    for arm in forged_positive["arms"].values():
        arm["measurement_availability"]["workflow_overhead"] = "MEASURED"
    reopened = ResearchJournal(journal.path)
    with pytest.raises(JournalConflictError, match="immutable result"):
        reopened.append(
            forged_positive,
            source="analyst",
            links=((decision["record_digest"], "summarizes-acceleration"),),
        )
    journal.append(
        acceleration_record, source="analyst",
        links=((decision["record_digest"], "summarizes-acceleration"),),
    )

    assert journal.learning_receipt("q-1", final=True)["execution_snapshot"]["run_id"] == "run-1"
