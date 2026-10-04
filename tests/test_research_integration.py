from __future__ import annotations

import hashlib
import json
import runpy
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_researcher.harness_adapter as harness_adapter_module
from ai_researcher import experiment
from ai_researcher.experiment import (
    DataGovernanceAttestation,
    ExecutionAuthorization,
    HumanExecutionScope,
    HumanObjective,
    run_matched_experiment,
)
from ai_researcher.harness_adapter import (
    HarnessAdapter,
    HarnessIntegrationError,
    PreparedExperiment,
)
from ai_researcher.journal import (
    JournalConflictError,
    ResearchJournal,
    _verify_omnigent_session_export,
)
from ai_researcher.records import RecordValidationError, experiment_digest, validate_record
from orchestrator_harness.config import ResourceManifest, load_config
from orchestrator_harness.core import content_hash
from orchestrator_harness.epochs import lane_record_path, open_epoch, write_active_lanes
from orchestrator_harness.lanes import write_lane
from scripts.record_human_authority import record_human_authority


def _question() -> dict:
    return {
        "schema": "research-question/v1",
        "question_id": "question-1",
        "question": "Can guided search reach a fixed target in fewer trials?",
        "domain": "machine learning",
        "intended_scientific_use": "Test a bounded discovery policy.",
        "measurable_outcome": "Trials to a fixed accuracy target.",
        "primary_metric": "trials_to_threshold",
        "constraints": ["public data", "local CPU"],
        "assumptions": ["fixed split"],
    }


def _objective(question: dict, *, objective_id: str = "objective-1") -> dict:
    return {
        "schema": "objective-confirmation/v1",
        "objective_confirmation_id": objective_id,
        "question_id": question["question_id"],
        "question_digest": question["record_digest"],
        "primary_metric": question["primary_metric"],
        "dataset": {
            "identifier": "openml-task-59",
            "version": "1",
            "digest": "a" * 64,
            "source": "https://www.openml.org/t/59",
        },
        "risk_tolerance": {
            "level": "low",
            "allowed_risks": ["bounded compute overrun"],
            "prohibited_actions": ["external data mutation"],
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
        "confirmed_at": "2026-10-03T16:00:00Z",
    }


def _feasibility(objective_digest: str) -> dict:
    return {
        "schema": "feasibility-check/v1",
        "feasibility_check_id": "feasibility-1",
        "question_id": "question-1",
        "objective_confirmation_digest": objective_digest,
        "checked_by": "operator:test",
        "checked_at": "2026-10-03T16:01:00Z",
        "checks": {
            name: {"status": "PASS", "evidence": f"Verified {name}."}
            for name in ("access", "identity", "license", "privacy", "api", "compute")
        },
        "overall_status": "PASS",
        "fallback": "Stop and seek a newly confirmed objective.",
    }


def _evidence(objective_digest: str) -> dict:
    return {
        "schema": "evidence-package/v1",
        "evidence_package_id": "evidence-1",
        "question_id": "question-1",
        "objective_confirmation_digest": objective_digest,
        "claims": [
            {
                "evidence_id": "claim-1",
                "claim_type": "external-fact",
                "claim": "OpenML publishes the fixed task identifier.",
                "source_type": "dataset-registry",
                "citation": {
                    "title": "OpenML task 59",
                    "url": "https://www.openml.org/t/59",
                    "authors_or_organization": "OpenML",
                    "publisher_or_source": "OpenML",
                    "retrieved_at": "2026-10-03T16:01:00Z",
                    "license_or_access_note": "Public registry metadata.",
                    "verification_state": "verified",
                },
                "support": "The registry exposes task 59.",
                "uncertainty": "Availability can change.",
            }
        ],
        "conflicts": [],
        "coverage_gaps": [],
    }


def _hypotheses(objective_digest: str) -> dict:
    return {
        "schema": "hypothesis-portfolio/v1",
        "hypothesis_portfolio_id": "hypothesis-portfolio-1",
        "question_id": "question-1",
        "objective_confirmation_digest": objective_digest,
        "hypotheses": [
            {
                "hypothesis_id": "hypothesis-1",
                "statement": "Evidence-guided ordering reaches the target sooner.",
                "prediction": "The guided arm uses fewer trials.",
                "falsification_condition": "It does not use fewer trials.",
                "supporting_evidence_ids": ["claim-1"],
                "competing_explanations": ["Ordering advantage is task-specific."],
                "uncertainty": "Single-task evidence.",
            }
        ],
    }


def _experiment_candidates(objective_digest: str) -> dict:
    common = {
        "controls": ["same split", "same seeds"],
        "inputs": ["openml-task-59"],
        "parameters": {
            "max_trials_per_arm": 4,
            "max_seconds_per_arm": 60.0,
            "threshold": 0.9,
        },
        "random_seeds": [7, 11],
        "metrics": ["trials_to_threshold", "accuracy"],
        "estimated_runtime_minutes": 20,
        "estimated_cost_usd": 1,
        "risk_level": "low",
    }
    return {
        "schema": "experiment-candidates/v1",
        "experiment_candidates_id": "experiment-candidates-1",
        "question_id": "question-1",
        "objective_confirmation_digest": objective_digest,
        "hypothesis_id": "hypothesis-1",
        "primary_metric": "trials_to_threshold",
        "dataset_identity": {
            "identifier": "openml-task-59",
            "version": "1",
            "digest": "a" * 64,
        },
        "resource_bounds": {
            "max_trials": 8,
            "max_runtime_minutes": 30,
            "max_cost_usd": 1.0,
            "compute": "local CPU",
            "network_access": "dataset-download-only",
            "mutation_permissions": ["artifact directory only"],
        },
        "risk_tolerance": {
            "level": "low",
            "allowed_risks": ["bounded compute overrun"],
            "prohibited_actions": ["external data mutation"],
            "privacy_constraints": ["public data only"],
            "acceptable_failure_modes": ["inconclusive result"],
        },
        "candidates": [
            {
                **common,
                "experiment_id": "experiment-guided",
                "method": "Run evidence-guided selection on a fixed split.",
                "baseline": "Fixed grid search on the same split.",
                "success_threshold": "Reach target accuracy in fewer trials.",
                "expected_learning": "Whether evidence improves trial efficiency.",
            },
            {
                **common,
                "experiment_id": "experiment-ablation",
                "method": "Remove reviewed failure memory.",
                "baseline": "Use reviewed failure memory.",
                "success_threshold": "Detect a trial-count difference.",
                "expected_learning": "Whether reviewed failures affect selection.",
            },
        ],
        "selected_experiment_id": "experiment-guided",
        "selection_rationale": "Best expected learning under the time budget.",
        "rejected_candidate_rationales": {"experiment-ablation": "Run second."},
    }


def _safety_review(portfolio: dict) -> dict:
    return {
        "schema": "safety-review/v1",
        "experiment_id": "experiment-guided",
        "experiment_digest": experiment_digest(portfolio),
        "objective_confirmation_digest": portfolio["objective_confirmation_digest"],
        "verdict": "APPROVAL_REQUIRED",
        "risks": ["Compute overrun"],
        "required_controls": ["Hard four-trial cap"],
        "prohibited_actions": ["No external data mutation"],
        "approval_question": "Approve this exact four-trial experiment?",
        "review_limitations": [],
    }


def _approval(portfolio: dict) -> dict:
    return {
        "schema": "human-approval/v1",
        "approval_id": "approval-1",
        "experiment_id": "experiment-guided",
        "experiment_digest": experiment_digest(portfolio),
        "objective_confirmation_digest": portfolio["objective_confirmation_digest"],
        "approved": True,
        "approved_by": "human:test",
        "approved_at": "2026-10-03T16:05:00Z",
        "scope": "execute-exact-experiment",
        "constraints": ["Hard four-trial cap"],
    }


def _record_reviewed_chain(adapter: HarnessAdapter) -> tuple[dict, dict, dict]:
    journal = adapter.journal
    question = journal.append(
        _question(), source="human", producer_session_id="human-turn-1",
        producer_agent_id="human:test",
    )
    objective = record_human_authority(
        journal_path=journal.path, record=_objective(question),
        parent_digest=question["record_digest"], human_id="human:test",
        human_session_id="human-turn-2",
    )
    feasibility = journal.append(
        _feasibility(objective["record_digest"]), source="operator:preflight",
        links=((objective["record_digest"], "checks-feasibility"),),
        producer_session_id="preflight-1", producer_agent_id="research-director",
    )
    evidence = journal.append(
        _evidence(objective["record_digest"]), source="omnigent:evidence-researcher",
        links=((objective["record_digest"], "authorizes-evidence"),),
        producer_session_id="evidence-session-1", producer_agent_id="evidence-researcher",
    )
    hypotheses = journal.append(
        _hypotheses(objective["record_digest"]), source="omnigent:hypothesis-scientist",
        links=((evidence["record_digest"], "supports-hypotheses"),),
        producer_session_id="hypothesis-session-1", producer_agent_id="hypothesis-scientist",
    )
    portfolio = journal.append(
        _experiment_candidates(objective["record_digest"]),
        source="omnigent:experiment-designer",
        links=(
            (hypotheses["record_digest"], "tests-hypothesis"),
            (feasibility["record_digest"], "bounded-by-feasibility"),
        ),
        producer_session_id="designer-session-1", producer_agent_id="experiment-designer",
    )
    review = journal.append(
        _safety_review(portfolio), source="omnigent:safety-reviewer",
        links=((portfolio["record_digest"], "reviews-selected-experiment"),),
        producer_session_id="safety-session-1", producer_agent_id="safety-reviewer",
    )
    return objective, portfolio, review


def _record_approval(
    adapter: HarnessAdapter, portfolio: dict, review: dict
) -> dict:
    return record_human_authority(
        journal_path=adapter.journal.path,
        record=_approval(portfolio),
        parent_digest=review["record_digest"],
        human_id="human:test",
        human_session_id="human-turn-approval",
    )


def _adapter(tmp_path: Path) -> HarnessAdapter:
    return HarnessAdapter(
        ROOT,
        journal_path=tmp_path / "journal.sqlite3",
        artifact_root=tmp_path / "tasks",
    )


def _mark_launched(
    adapter: HarnessAdapter, prepared: PreparedExperiment, *, run_id: str
) -> None:
    """Reproduce the durable two-phase launch handshake in lifecycle tests."""

    arguments = {
        "experiment_id": prepared.experiment_id,
        "experiment_digest": prepared.experiment_digest,
        "approval_digest": prepared.approval_digest,
        "objective_confirmation_digest": prepared.objective_confirmation_digest,
        "task_card_digest": prepared.task_card_digest,
        "task_card_path": prepared.task_card_path,
        "lane_id": prepared.lane_id,
        "run_id": run_id,
    }
    adapter.journal.bind_experiment(**arguments, status="LAUNCHING")
    adapter.journal.bind_experiment(**arguments, status="LAUNCHED")


def _publish_active_lane(
    harness_root: Path, workspace: Path, lane: dict
) -> str:
    """Publish a real local Harness epoch/lane index without touching the checkout."""

    local_config = harness_root / "local-config"
    local_config.mkdir(parents=True, exist_ok=True)
    (local_config / "harness-config.json").write_text(
        json.dumps(
            {"root_workspace": str(workspace), "managed_coordination": "disabled"}
        ),
        encoding="utf-8",
    )
    config = load_config(harness_root)
    state = open_epoch(config.runtime_root, config, ResourceManifest())
    epoch_id = str(state["epoch_id"])
    write_lane(config.runtime_root, epoch_id, lane["lane_id"], lane)
    write_active_lanes(
        config.runtime_root,
        epoch_id,
        [
            {
                "lane_id": lane["lane_id"],
                "run_id": lane["run_id"],
                "lane_record_path": str(
                    lane_record_path(config.runtime_root, epoch_id, lane["lane_id"])
                ),
            }
        ],
    )
    return epoch_id


def test_experiment_portfolio_requires_competing_candidates() -> None:
    portfolio = _experiment_candidates("b" * 64)
    portfolio["candidates"] = portfolio["candidates"][:1]
    with pytest.raises(RecordValidationError, match="at least two"):
        validate_record(portfolio)


def test_journal_rejects_conflicting_identity(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    record = _question()
    journal.append(record, source="test")
    with pytest.raises(JournalConflictError):
        journal.append(dict(record, question="A different question"), source="test")


def test_approval_request_requires_journaled_objective_and_feasibility(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    portfolio = _experiment_candidates("b" * 64)
    with pytest.raises(HarnessIntegrationError, match="journaled|authority"):
        adapter.approval_request(
            portfolio,
            _safety_review(portfolio),
            objective_confirmation_digest="b" * 64,
        )


def test_late_failed_feasibility_blocks_approval_and_staging(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    failed = _feasibility(objective["record_digest"])
    failed.update(
        {
            "feasibility_check_id": "feasibility-late-failure",
            "checked_at": "2026-10-03T16:04:00Z",
        }
    )
    failed["checks"]["api"] = {
        "status": "FAIL",
        "evidence": "The previously available API became unavailable.",
    }
    failed["overall_status"] = "FAIL"
    adapter.journal.append(
        failed,
        source="operator:preflight",
        links=((objective["record_digest"], "invalidates-feasibility"),),
        producer_session_id="preflight-2",
        producer_agent_id="research-director",
    )

    with pytest.raises(HarnessIntegrationError, match="failed feasibility"):
        adapter.approval_request(
            portfolio,
            review,
            objective_confirmation_digest=objective["record_digest"],
        )


def test_approval_stages_exact_task_bytes_without_launch(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    request = adapter.approval_request(
        portfolio, review,
        objective_confirmation_digest=objective["record_digest"],
    )
    assert request["objective_confirmation_digest"] == objective["record_digest"]
    assert request["experiment_digest"] == experiment_digest(portfolio)

    prepared = adapter.prepare(
        portfolio, review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    assert prepared.task_card_path.is_file()
    assert prepared.task_card_digest == hashlib.sha256(
        prepared.task_card_path.read_bytes()
    ).hexdigest()
    task = json.loads(prepared.task_card_path.read_text(encoding="utf-8"))
    assert task["research_authority"] == {
        "objective_confirmation_digest": prepared.objective_confirmation_digest,
        "experiment_digest": prepared.experiment_digest,
        "approval_digest": prepared.approval_digest,
    }
    for digest in (
        prepared.objective_confirmation_digest,
        prepared.experiment_digest,
        prepared.approval_digest,
    ):
        assert digest in task["task"]
    status = adapter.status("experiment-guided")
    assert status["status"] == "STAGED"
    assert status["task_card_digest"] == prepared.task_card_digest


def test_mismatched_or_stale_authority_fails_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    with pytest.raises(HarnessIntegrationError, match="not journaled"):
        adapter.prepare(
            portfolio, review,
            objective_confirmation_digest=objective["record_digest"],
            approval_digest="0" * 64,
        )

    question = adapter.journal.find("research-question/v1", "question-1")
    assert question is not None
    superseding = _objective(question, objective_id="objective-2")
    superseding["confirmed_at"] = "2026-10-03T16:06:00Z"
    superseding["supersedes_objective_confirmation_digest"] = objective["record_digest"]
    adapter.journal.append(
        superseding, source="human",
        links=((objective["record_digest"], "supersedes-objective"),),
    )
    with pytest.raises(HarnessIntegrationError, match="superseded|stale"):
        adapter.approval_request(
            portfolio, review,
            objective_confirmation_digest=objective["record_digest"],
        )


def test_launch_revalidates_staged_bytes_and_requires_environment_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio, review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    prepared.task_card_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    with pytest.raises(HarnessIntegrationError, match="task card"):
        adapter.launch(
            prepared, confirmation=prepared.approval_digest,
            provider="codex", model="test-model",
            provider_options={"reasoning_effort": "high", "service_tier": "priority"},
        )

    adapter2 = _adapter(tmp_path / "second")
    objective2, portfolio2, review2 = _record_reviewed_chain(adapter2)
    prepared2 = adapter2.prepare(
        portfolio2, review2,
        objective_confirmation_digest=objective2["record_digest"],
        approval_digest=_record_approval(adapter2, portfolio2, review2)["record_digest"],
    )
    monkeypatch.delenv("AI_RESEARCHER_ENABLE_EXECUTION", raising=False)
    with pytest.raises(HarnessIntegrationError, match="execution is disabled"):
        adapter2.launch(
            prepared2, confirmation=prepared2.approval_digest,
            provider="codex", model="test-model",
            provider_options={"reasoning_effort": "high", "service_tier": "priority"},
        )


def test_launch_uses_authoritative_harness_lane_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    local_config = adapter.harness_root / "local-config" / "harness-config.json"
    config_before = local_config.read_bytes() if local_config.is_file() else None
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio,
        review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    operator_calls: list[tuple[str, ...]] = []

    def operator(*args: str) -> dict:
        operator_calls.append(args)
        if args[:2] == ("lane", "launch"):
            launching = adapter.status(prepared.experiment_id)
            assert launching["status"] == "LAUNCHING"
            assert launching["run_id"] == "native-run-1"
        return {"ok": True}

    monkeypatch.setattr(adapter, "_operator", operator)
    calls: list[str] = []

    def active(_root: Path, *, lane_id: str) -> tuple[str, dict]:
        calls.append(lane_id)
        return "epoch-1", {"lane_id": lane_id, "run_id": "native-run-1"}

    monkeypatch.setattr(harness_adapter_module, "active_harness_run", active)
    launched = adapter.launch(
        prepared,
        confirmation=prepared.approval_digest,
        provider="codex",
        model="test-model",
        provider_options={"reasoning_effort": "high", "service_tier": "priority"},
    )
    assert launched["run_id"] == "native-run-1"
    assert calls == [prepared.lane_id, prepared.lane_id]
    assert adapter.status(prepared.experiment_id)["run_id"] == "native-run-1"
    config_after = local_config.read_bytes() if local_config.is_file() else None
    assert config_after == config_before
    assert ("--provider-option", "reasoning_effort=high") == operator_calls[0][
        operator_calls[0].index("--provider-option") :
        operator_calls[0].index("--provider-option") + 2
    ]
    assert "service_tier=priority" in operator_calls[0]


def test_launch_persistence_failure_force_stops_exact_run_and_cancels_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio,
        review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    operator_calls: list[tuple[str, ...]] = []
    lane_evidence = tmp_path / "launch-cleanup-lane.json"
    lane_evidence.write_text(json.dumps({
        "schema": "lane/v1", "lane_id": prepared.lane_id,
        "run_id": "race-run-1", "lifecycle": "retired",
    }), encoding="utf-8")

    def operator(*args: str) -> dict:
        operator_calls.append(args)
        if args[:2] == ("lane", "force-stop"):
            return {
                "ok": True,
                "code": "FORCE_STOP_OK",
                "evidence_paths": [str(lane_evidence)],
            }
        return {"ok": True}

    monkeypatch.setattr(adapter, "_operator", operator)
    monkeypatch.setattr(
        harness_adapter_module,
        "active_harness_run",
        lambda _root, *, lane_id: (
            "epoch-1", {"lane_id": lane_id, "run_id": "race-run-1"}
        ),
    )
    original_bind = adapter.journal.bind_experiment

    def persist_with_final_failure(**kwargs) -> None:
        if kwargs.get("status") == "LAUNCHED":
            raise JournalConflictError("simulated final launch persistence failure")
        original_bind(**kwargs)

    monkeypatch.setattr(adapter.journal, "bind_experiment", persist_with_final_failure)
    with pytest.raises(HarnessIntegrationError, match="force-stopped|persistence"):
        adapter.launch(
            prepared,
            confirmation=prepared.approval_digest,
            provider="codex",
            model="test-model",
            provider_options={
                "reasoning_effort": "high",
                "service_tier": "priority",
            },
        )
    assert [call[:2] for call in operator_calls] == [
        ("lane", "bootstrap"),
        ("lane", "launch"),
        ("lane", "force-stop"),
    ]
    binding = adapter.status(prepared.experiment_id)
    assert binding["status"] == "CANCELLED"
    assert binding["run_id"] == "race-run-1"


def test_launch_never_starts_worker_when_launching_authority_cannot_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio,
        review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    operator_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        adapter,
        "_operator",
        lambda *args: operator_calls.append(args) or {"ok": True},
    )
    monkeypatch.setattr(
        harness_adapter_module,
        "active_harness_run",
        lambda _root, *, lane_id: (
            "epoch-1", {"lane_id": lane_id, "run_id": "never-started-run"}
        ),
    )
    original_bind = adapter.journal.bind_experiment

    def reject_launching_authority(**kwargs) -> None:
        if kwargs.get("status") == "LAUNCHING":
            raise JournalConflictError("simulated durable persistence failure")
        original_bind(**kwargs)

    monkeypatch.setattr(adapter.journal, "bind_experiment", reject_launching_authority)
    with pytest.raises(HarnessIntegrationError, match="worker was not launched"):
        adapter.launch(
            prepared,
            confirmation=prepared.approval_digest,
            provider="codex",
            model="test-model",
            provider_options={
                "reasoning_effort": "high",
                "service_tier": "priority",
            },
        )
    assert [call[:2] for call in operator_calls] == [("lane", "bootstrap")]
    assert adapter.status(prepared.experiment_id)["status"] == "STAGED"


def test_launch_failure_keeps_launching_authority_when_exact_cleanup_is_unproven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio,
        review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    wrong_lane_evidence = tmp_path / "wrong-run-retirement.json"
    wrong_lane_evidence.write_text(json.dumps({
        "schema": "lane/v1", "lane_id": prepared.lane_id,
        "run_id": "different-run", "lifecycle": "retired",
    }), encoding="utf-8")

    def operator(*args: str) -> dict:
        if args[:2] == ("lane", "force-stop"):
            return {
                "ok": True,
                "code": "FORCE_STOP_OK",
                "evidence_paths": [str(wrong_lane_evidence)],
            }
        return {"ok": True}

    monkeypatch.setattr(adapter, "_operator", operator)
    monkeypatch.setattr(
        harness_adapter_module,
        "active_harness_run",
        lambda _root, *, lane_id: (
            "epoch-1", {"lane_id": lane_id, "run_id": "uncertain-run"}
        ),
    )
    original_bind = adapter.journal.bind_experiment

    def persist_with_final_failure(**kwargs) -> None:
        if kwargs.get("status") == "LAUNCHED":
            raise JournalConflictError("simulated final persistence failure")
        original_bind(**kwargs)

    monkeypatch.setattr(adapter.journal, "bind_experiment", persist_with_final_failure)
    with pytest.raises(HarnessIntegrationError, match="remains LAUNCHING"):
        adapter.launch(
            prepared,
            confirmation=prepared.approval_digest,
            provider="codex",
            model="test-model",
            provider_options={
                "reasoning_effort": "high",
                "service_tier": "priority",
            },
        )
    assert adapter.status(prepared.experiment_id)["status"] == "LAUNCHING"
    assert not (
        adapter.artifact_root / f"{prepared.lane_id}.force-stop.json"
    ).exists()


@pytest.mark.parametrize(
    ("provider", "provider_options", "expected_options"),
    [
        (
            "codex",
            {"reasoning_effort": "high", "service_tier": "priority"},
            ["reasoning_effort=high", "service_tier=priority"],
        ),
        ("claude-code", {"effort": "high"}, ["effort=high"]),
        ("qwen-code", {}, []),
    ],
)
def test_advertised_provider_launches_validate_options_and_use_real_lane_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    provider_options: dict[str, str],
    expected_options: list[str],
) -> None:
    """Cover provider configuration plus the real local Harness index boundary."""

    adapter_root = tmp_path / "adapter"
    adapter_root.mkdir()
    adapter = _adapter(adapter_root)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio,
        review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    isolated_harness = tmp_path / "isolated-harness"
    binding_source = (
        ROOT
        / "harness"
        / "orchestrator_harness"
        / "provider_adapters"
        / provider
        / "launcher_binding.py"
    )
    binding_target = (
        isolated_harness
        / "orchestrator_harness"
        / "provider_adapters"
        / provider
        / "launcher_binding.py"
    )
    binding_target.parent.mkdir(parents=True)
    binding_target.write_bytes(binding_source.read_bytes())
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_id = f"run-{provider}"
    lane = {
        "lane_id": prepared.lane_id,
        "run_id": run_id,
        "lifecycle": "prepared",
        "worktree_path": str(tmp_path / "worker"),
    }
    epoch_id = _publish_active_lane(isolated_harness, workspace, lane)
    adapter.harness_root = isolated_harness
    operator_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        adapter,
        "_operator",
        lambda *args: operator_calls.append(args) or {"ok": True, "args": args},
    )
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")

    launched = adapter.launch(
        prepared,
        confirmation=prepared.approval_digest,
        provider=provider,
        model="test-model",
        provider_options=provider_options,
    )

    assert launched["run_id"] == run_id
    assert adapter.harness_status(prepared.experiment_id)["epoch_id"] == epoch_id
    assert [call[:2] for call in operator_calls] == [
        ("lane", "bootstrap"),
        ("lane", "launch"),
    ]
    bootstrap = operator_calls[0]
    assert bootstrap[bootstrap.index("--provider") + 1] == provider
    assert bootstrap[bootstrap.index("--model") + 1] == "test-model"
    observed_options = [
        bootstrap[index + 1]
        for index, value in enumerate(bootstrap)
        if value == "--provider-option"
    ]
    assert observed_options == expected_options
    assert bootstrap[-2:] == ("--task-card", str(prepared.task_card_path))


@pytest.mark.parametrize(
    ("provider", "options"),
    [
        ("codex", {}),
        ("codex", {"reasoning_effort": "high"}),
        ("claude-code", {}),
        ("qwen-code", {"effort": "high"}),
    ],
)
def test_launch_rejects_missing_or_unsupported_provider_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    options: dict[str, str],
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio,
        review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    with pytest.raises(HarnessIntegrationError, match="provider options"):
        adapter.launch(
            prepared,
            confirmation=prepared.approval_digest,
            provider=provider,
            model="test-model",
            provider_options=options,
        )


def _result(prepared: PreparedExperiment, *, run_id: str = "run-1") -> dict:
    metrics_artifact = hashlib.sha256(b"metrics").hexdigest()
    availability = {
        "workflow_overhead": "UNAVAILABLE",
        "compute_seconds": "MEASURED",
        "human_interventions": "MEASURED",
        "cost_usd": "MEASURED",
        "token_usage": "MEASURED",
    }
    result = {
        "schema": "experiment-result/v1",
        "question_id": "question-1",
        "experiment_id": prepared.experiment_id,
        "run_id": run_id,
        "objective_confirmation_digest": prepared.objective_confirmation_digest,
        "experiment_digest": prepared.experiment_digest,
        "approval_digest": prepared.approval_digest,
        "task_card_digest": prepared.task_card_digest,
        "primary_metric": "trials_to_threshold",
        "execution_source": "integrated-harness",
        "code_identity": "commit-1",
        "dataset_identity": {
            "identifier": "openml-task-59",
            "version": "1",
            "digest": "a" * 64,
        },
        "environment_identity": "lock-1",
        "parameters": {
            "approved_candidate_parameters": {
                "max_trials_per_arm": 4,
                "max_seconds_per_arm": 60.0,
                "threshold": 0.9,
            },
            "observed_preregistration": {
                "primary_metric": "trials_to_threshold",
                "dataset_identity": {
                    "identifier": "openml-task-59",
                    "version": "1",
                    "digest": "a" * 64,
                },
                "split_seed": 7,
                "threshold": 0.9,
                "max_trials_per_arm": 4,
                "max_seconds_per_arm": 60.0,
            },
            "execution_metadata": {
                "measurement_availability": {
                    "baseline": dict(availability),
                    "proposed": dict(availability),
                }
            },
        },
        "random_seeds": [7, 11],
        "metrics": {
            "trials_to_threshold": {
                "baseline": {"value": 4, "censored": False, "lower_bound_exclusive": None},
                "proposed": {"value": 3, "censored": False, "lower_bound_exclusive": None},
            },
            "accuracy": {"baseline": 0.90, "proposed": 0.91},
            "elapsed_to_threshold_seconds": {"baseline": 4.0, "proposed": 3.0},
            "total_elapsed_seconds": {"baseline": 5.0, "proposed": 4.0},
            "compute_seconds": {"baseline": 4.5, "proposed": 3.5},
            "interventions": {"baseline": 0, "proposed": 0},
            "cost_usd": {"baseline": 0.0, "proposed": 0.0},
            "token_usage": {"baseline": 0, "proposed": 0},
            "baseline": {
                "attempted_trials": 4,
                "overhead_included": False,
                "measurement_availability": dict(availability),
            },
            "evidence_guided": {
                "attempted_trials": 3,
                "overhead_included": False,
                "measurement_availability": dict(availability),
            },
        },
        "artifact_refs": [
            {
                "uri": "artifact:metrics.json",
                "kind": "metric-log",
                "digest": metrics_artifact,
            }
        ],
        "measurement_support": {},
        "started_at": "2026-10-03T16:06:00Z",
        "completed_at": "2026-10-03T16:10:00Z",
        "status": "PASS",
        "limitations": [],
    }
    result["measurement_support"] = {
        metric: metrics_artifact for metric in result["metrics"]
    }
    return result


def _local_result_evidence(
    tmp_path: Path, prepared: PreparedExperiment, result: dict
) -> tuple[dict, Path]:
    artifact_dir = tmp_path / "result-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "metrics.json").write_bytes(b"metrics")
    payload = {
        "lane_id": prepared.lane_id,
        "run_id": result["run_id"],
        "status": "COMPLETED",
    }
    evidence_path = tmp_path / "harness-terminal.json"
    evidence_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    evidence = {
        **payload,
        "uri": evidence_path.as_uri(),
        "digest": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "acceptance": {
            "decided_at": "2026-10-03T16:11:00Z",
            "content_hash": "d" * 64,
        },
    }
    return evidence, artifact_dir


def test_result_requires_matching_launched_binding_and_exact_specification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio, review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    result = _result(prepared)
    terminal, artifact_dir = _local_result_evidence(tmp_path, prepared, result)
    monkeypatch.setattr(
        harness_adapter_module,
        "verified_terminal_evidence",
        lambda _root, **kwargs: {
            **terminal,
            "result": {"scientific_result": kwargs["scientific_result"]},
        },
    )
    with pytest.raises(HarnessIntegrationError, match="launched"):
        adapter.record_result(
            result, terminal_evidence=terminal, artifact_base_dir=artifact_dir
        )

    _mark_launched(adapter, prepared, run_id="run-1")
    attested_result = _result(prepared)
    monkeypatch.setattr(
        harness_adapter_module,
        "verified_terminal_evidence",
        lambda _root, **_kwargs: {
            **terminal,
            "result": {"scientific_result": attested_result},
        },
    )
    unattested = _result(prepared)
    unattested["metrics"]["accuracy"]["proposed"] = 0.99
    with pytest.raises(HarnessIntegrationError, match="Harness-reviewed scientific_result"):
        adapter.record_result(
            unattested, terminal_evidence=terminal, artifact_base_dir=artifact_dir
        )
    monkeypatch.setattr(
        harness_adapter_module,
        "verified_terminal_evidence",
        lambda _root, **kwargs: {
            **terminal,
            "result": {"scientific_result": kwargs["scientific_result"]},
        },
    )
    changed = _result(prepared)
    changed["random_seeds"] = [99]
    with pytest.raises(HarnessIntegrationError, match="seeds"):
        adapter.record_result(
            changed, terminal_evidence=terminal, artifact_base_dir=artifact_dir
        )
    changed = _result(prepared)
    changed["metrics"]["post_hoc_metric"] = 1
    changed["measurement_support"]["post_hoc_metric"] = changed["artifact_refs"][0]["digest"]
    with pytest.raises(HarnessIntegrationError, match="metrics"):
        adapter.record_result(
            changed, terminal_evidence=terminal, artifact_base_dir=artifact_dir
        )

    (artifact_dir / "metrics.json").unlink()
    with pytest.raises(HarnessIntegrationError, match="artifact does not exist"):
        adapter.record_result(
            result, terminal_evidence=terminal, artifact_base_dir=artifact_dir
        )
    (artifact_dir / "metrics.json").write_bytes(b"metrics")

    stored = adapter.record_result(
        result, terminal_evidence=terminal, artifact_base_dir=artifact_dir
    )
    assert stored["record_digest"]
    terminal_status = adapter.status("experiment-guided")
    assert terminal_status["status"] == "COMPLETED"
    assert terminal_status["acceptance_decided_at"] == terminal["acceptance"][
        "decided_at"
    ]
    assert terminal_status["acceptance_digest"] == terminal["acceptance"][
        "content_hash"
    ]


def test_prepared_value_cannot_substitute_for_durable_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio, review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    forged = replace(prepared, task_card_digest="f" * 64)
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    with pytest.raises(HarnessIntegrationError, match="binding|task card"):
        adapter.launch(
            forged, confirmation=forged.approval_digest,
            provider="codex", model="test-model",
            provider_options={"reasoning_effort": "high", "service_tier": "priority"},
        )


def test_public_lifecycle_requires_confirmation_and_preserves_exact_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio, review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    _mark_launched(adapter, prepared, run_id="lifecycle-run")
    calls: list[tuple[str, ...]] = []

    def operator(*args: str) -> dict:
        calls.append(args)
        return {"ok": True, "arguments": list(args)}

    monkeypatch.setattr(adapter, "_operator", operator)
    assert adapter.wait_for_review(prepared.experiment_id, timeout="30s")["ok"]
    assert calls[-1] == (
        "watch", "--until-review-for", prepared.lane_id, "--timeout", "30s"
    )

    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    with pytest.raises(HarnessIntegrationError, match="approval digest"):
        adapter.review_completion(
            prepared.experiment_id,
            confirmation="wrong",
            review_outcome="PASS",
            approval="ACCEPTED",
            review_summary="Independent checks passed.",
        )
    assert calls[-1][0] == "watch"

    reviewed = adapter.review_completion(
        prepared.experiment_id,
        confirmation=prepared.approval_digest,
        review_outcome="PASS",
        approval="ACCEPTED",
        review_summary="Independent checks passed.",
        evidence=("artifact:metrics.json",),
    )
    assert reviewed["ok"]
    assert calls[-1][:4] == (
        "lane", "completion-review", "--lane-id", prepared.lane_id
    )
    with pytest.raises(HarnessIntegrationError, match="PASS"):
        adapter.review_completion(
            prepared.experiment_id,
            confirmation=prepared.approval_digest,
            review_outcome="FAIL",
            approval="ACCEPTED",
            review_summary="Scientific checks failed.",
        )
    with pytest.raises(HarnessIntegrationError, match="UNKNOWN"):
        adapter.review_completion(
            prepared.experiment_id,
            confirmation=prepared.approval_digest,
            review_outcome="UNKNOWN",
            approval="REJECTED",
            review_summary="No reliable review conclusion exists.",
        )


def test_force_stop_and_shutdown_are_explicit_consequential_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio, review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    _mark_launched(adapter, prepared, run_id="stop-run")
    calls: list[tuple[str, ...]] = []
    lane_evidence = tmp_path / "force-stop-lane.json"
    lane_evidence.write_text(json.dumps({
        "schema": "lane/v1", "lane_id": prepared.lane_id,
        "run_id": "stop-run", "lifecycle": "retired",
    }), encoding="utf-8")

    def operator(*args: str) -> dict:
        calls.append(args)
        if args[:2] == ("lane", "force-stop"):
            return {
                "ok": True, "code": "FORCE_STOP_OK",
                "summary": "lane force-stopped and retired",
                "evidence_paths": [str(lane_evidence)],
                "next_action": "reuse the freed resource",
            }
        return {"ok": True}

    monkeypatch.setattr(adapter, "_operator", operator)
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    with pytest.raises(HarnessIntegrationError, match="approval digest"):
        adapter.force_stop(prepared.experiment_id, confirmation="wrong")
    stopped = adapter.force_stop(
        prepared.experiment_id, confirmation=prepared.approval_digest
    )
    assert stopped["ok"]
    assert stopped["cancellation_receipt"]["status"] == "CANCELLED"
    assert stopped["cancellation_receipt"]["harness_lifecycle"] == "retired"
    assert stopped["cancellation_receipt"]["run_id"] == "stop-run"
    assert calls[-1] == ("lane", "force-stop", "--lane-id", prepared.lane_id)
    assert adapter.status(prepared.experiment_id)["status"] == "CANCELLED"
    assert adapter.cancellation_evidence(prepared.experiment_id) == stopped[
        "cancellation_receipt"
    ]

    with pytest.raises(HarnessIntegrationError, match="shutdown confirmation"):
        adapter.shutdown(confirmation="yes")
    adapter.shutdown(confirmation="SHUTDOWN RESEARCH HARNESS")
    assert calls[-1] == ("harness", "shutdown")


def test_failed_force_stop_does_not_claim_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio, review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    _mark_launched(adapter, prepared, run_id="stop-failed-run")
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    monkeypatch.setattr(adapter, "_operator", lambda *args: {
        "ok": False, "code": "FORCE_STOP_PROCESS_SURVIVED",
        "summary": "provider still alive", "evidence_paths": [],
        "next_action": "escalate",
    })

    with pytest.raises(HarnessIntegrationError, match="did not retire"):
        adapter.force_stop(
            prepared.experiment_id, confirmation=prepared.approval_digest
        )
    assert adapter.status(prepared.experiment_id)["status"] == "LAUNCHED"


@pytest.mark.parametrize("execution_status", ["LAUNCHING", "LAUNCHED"])
def test_force_stop_preserves_cleanup_authority_after_objective_supersession(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_status: str,
) -> None:
    adapter = _adapter(tmp_path)
    objective, portfolio, review = _record_reviewed_chain(adapter)
    prepared = adapter.prepare(
        portfolio,
        review,
        objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    binding = {
        "experiment_id": prepared.experiment_id,
        "experiment_digest": prepared.experiment_digest,
        "approval_digest": prepared.approval_digest,
        "objective_confirmation_digest": prepared.objective_confirmation_digest,
        "task_card_digest": prepared.task_card_digest,
        "task_card_path": prepared.task_card_path,
        "lane_id": prepared.lane_id,
        "run_id": f"cleanup-{execution_status.lower()}",
    }
    adapter.journal.bind_experiment(**binding, status="LAUNCHING")
    if execution_status == "LAUNCHED":
        adapter.journal.bind_experiment(**binding, status="LAUNCHED")

    question = adapter.journal.find("research-question/v1", "question-1")
    assert question is not None
    superseding = _objective(question, objective_id="objective-cleanup-replacement")
    superseding["confirmed_at"] = "2026-10-03T16:30:00Z"
    superseding["supersedes_objective_confirmation_digest"] = objective[
        "record_digest"
    ]
    adapter.journal.append(
        superseding,
        source="human",
        links=((objective["record_digest"], "supersedes-objective"),),
    )
    expected_status_error = (
        "matching launched" if execution_status == "LAUNCHING" else "superseded|stale"
    )
    with pytest.raises(HarnessIntegrationError, match=expected_status_error):
        adapter.harness_status(prepared.experiment_id)

    lane_evidence = tmp_path / f"{execution_status.lower()}-retired-lane.json"
    lane_evidence.write_text(json.dumps({
        "schema": "lane/v1",
        "lane_id": prepared.lane_id,
        "run_id": binding["run_id"],
        "lifecycle": "retired",
    }), encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def operator(*args: str) -> dict:
        calls.append(args)
        return {
            "ok": True,
            "code": "FORCE_STOP_OK",
            "evidence_paths": [str(lane_evidence)],
        }

    monkeypatch.setattr(adapter, "_operator", operator)
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    with pytest.raises(HarnessIntegrationError, match="approval digest"):
        adapter.force_stop(prepared.experiment_id, confirmation="wrong")
    stopped = adapter.force_stop(
        prepared.experiment_id, confirmation=prepared.approval_digest
    )
    assert stopped["cancellation_receipt"]["run_id"] == binding["run_id"]
    assert calls == [("lane", "force-stop", "--lane-id", prepared.lane_id)]
    assert adapter.status(prepared.experiment_id)["status"] == "CANCELLED"
    assert adapter.cancellation_evidence(prepared.experiment_id) == stopped[
        "cancellation_receipt"
    ]


def test_complete_hermetic_workflow_reopens_with_identical_final_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(tmp_path)
    fixture_dir = ROOT / "fixtures" / "openml"
    fixture_digest = json.loads(
        (fixture_dir / "task_59_proxy.metadata.json").read_text(encoding="utf-8")
    )["sha256"]
    question_record = _question()
    question_record.update(
        {
            "question": "Can guided ordering reach accuracy sooner?",
            "primary_metric": "trials_to_threshold",
            "measurable_outcome": "Matched accuracy and trials to threshold.",
        }
    )
    question = adapter.journal.append(question_record, source="human:proposal")
    objective_record = _objective(question)
    objective_record.update(
        {
            "primary_metric": "trials_to_threshold",
            "dataset": {
                "identifier": "synthetic-proxy-openml-task-59-v1",
                "version": "1",
                "digest": fixture_digest,
                "source": (fixture_dir / "task_59_proxy.csv").as_uri(),
            },
            "execution_scope": {
                "max_trials": 8,
                "max_runtime_minutes": 5,
                "max_cost_usd": 0,
                "compute": "local CPU",
                "network_access": "read-only-openml",
                "mutation_permissions": ["artifact directory only"],
            },
        }
    )
    objective = record_human_authority(
        journal_path=adapter.journal.path,
        record=objective_record,
        parent_digest=question["record_digest"],
        human_id="human:test",
        human_session_id="objective-demo",
    )
    human_objective = HumanObjective(
        objective=question["question"], primary_metric="trials_to_threshold", openml_task_id=59,
        dataset_identifier="synthetic-proxy-openml-task-59-v1",
        openml_dataset_id=61, openml_dataset_version=1,
        dataset_digest=fixture_digest, risk_tolerance="low",
        execution_scope=HumanExecutionScope(
            max_trials=8, max_runtime_minutes=5, max_cost_usd=0,
            compute="local CPU", network_access="read-only-openml",
            mutation_permissions=("artifact directory only",),
        ),
        data_governance=DataGovernanceAttestation(
            license_status="VERIFIED", license_evidence="CC0 fixture metadata",
            privacy_status="VERIFIED", privacy_evidence="No personal data",
            verified_by="human:test", verified_at="2026-10-03T16:00:00Z",
        ),
        confirmed_by="human:test", confirmed_at="2026-10-03T16:00:00Z",
        objective_confirmation_digest=objective["record_digest"],
    )
    fixture_data = experiment._load_dataset(
        fixture_dir=fixture_dir,
        live=False,
        network_timeout_seconds=20.0,
    )
    monkeypatch.setattr(experiment, "_load_dataset", lambda **kwargs: fixture_data)
    runtime = runpy.run_path(
        str(ROOT / "agents" / "research-director" / "tools" / "research_runtime_core.py")
    )
    preflight_tool = runtime["preflight_confirmed_objective"]
    preflight_tool.__globals__["_adapter"] = lambda: adapter
    feasibility = preflight_tool(
        objective_confirmation_digest=objective["record_digest"],
        openml_task_id=59,
        openml_dataset_id=61,
        data_governance_json=json.dumps(
            {
                "license_status": "VERIFIED",
                "license_evidence": "CC0 fixture metadata",
                "privacy_status": "VERIFIED",
                "privacy_evidence": "No personal data",
                "verified_by": "human:test",
                "verified_at": "2026-10-03T16:00:00Z",
            }
        ),
        feasibility_check_id="feasibility-1",
        checked_by="operator:test",
        checked_at="2026-10-03T16:01:00Z",
        fallback="Stop and seek a newly confirmed objective.",
        producer_agent_id="research-director",
        producer_session_id="preflight-session",
        live=True,
    )
    evidence_a_payload = _evidence(objective["record_digest"])
    evidence_a_payload["evidence_package_id"] = "evidence-registry"
    evidence_b_payload = json.loads(json.dumps(evidence_a_payload))
    evidence_b_payload["evidence_package_id"] = "evidence-method"
    evidence_b_payload["claims"][0].update(
        {
            "evidence_id": "claim-2",
            "claim": "Matched search orders can be compared at a fixed threshold.",
            "support": "The method fixes the split, candidates, threshold, and budget.",
        }
    )
    evidence_b_payload["claims"][0]["citation"].update(
        {
            "title": "Matched sequential search protocol",
            "url": "https://example.org/matched-search-protocol",
            "publisher_or_source": "Independent Methods Registry",
        }
    )
    evidence_a = adapter.journal.append(
        evidence_a_payload, source="omnigent:evidence-researcher",
        links=((objective["record_digest"], "authorizes-evidence"),),
        producer_agent_id="evidence-researcher-a",
        producer_session_id="branch-session-a",
    )
    evidence_b = adapter.journal.append(
        evidence_b_payload, source="omnigent:evidence-researcher",
        links=((objective["record_digest"], "authorizes-evidence"),),
        producer_agent_id="evidence-researcher-b",
        producer_session_id="branch-session-b",
    )
    branches = []
    for branch_id, evidence, agent_id, session_id, started, completed in (
        (
            "branch-registry", evidence_a, "evidence-researcher-a", "branch-session-a",
            "2026-10-03T16:01:00Z", "2026-10-03T16:03:00Z",
        ),
        (
            "branch-method", evidence_b, "evidence-researcher-b", "branch-session-b",
            "2026-10-03T16:02:00Z", "2026-10-03T16:04:00Z",
        ),
    ):
        response_id = f"response-{branch_id}"
        request_time = datetime.fromisoformat(
            started.replace("Z", "+00:00")
        ).timestamp()
        response_time = datetime.fromisoformat(
            completed.replace("Z", "+00:00")
        ).timestamp()
        marker_start = request_time + 10
        marker_end = response_time - 10
        start_marker_id = f"marker-start-{branch_id}"
        start_call_id = f"call-start-{branch_id}"
        end_call_id = f"call-end-{branch_id}"
        export = "\n".join(
            json.dumps(row)
            for row in (
                {
                    "record_type": "session_meta",
                    "id": session_id,
                    "agent_id": f"durable-{agent_id}",
                    "agent_name": agent_id,
                    "sub_agent_name": "evidence-researcher",
                    "parent_session_id": "research-director-session",
                    "root_conversation_id": "research-director-session",
                    "status": "idle",
                    # Mutable session times deliberately do not define execution.
                    "created_at": 1791042000,
                    "updated_at": 1791046800,
                    "llm_model": "hermetic-provider-model",
                    "harness": "hermetic-omnigent",
                    "last_total_tokens": 100,
                },
                {
                    "record_type": "item",
                    "id": f"request-{branch_id}",
                    "type": "message",
                    "status": "completed",
                    "response_id": response_id,
                    "created_by": "operator",
                    "created_at": request_time,
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Investigate {branch_id}."}
                    ],
                },
                {
                    "record_type": "item", "id": f"start-call-{branch_id}",
                    "type": "function_call", "status": "completed",
                    "response_id": response_id, "created_at": marker_start - 1,
                    "model": agent_id, "name": "mark_provider_execution_start",
                    "arguments": json.dumps({"branch_id": branch_id}),
                    "call_id": start_call_id,
                },
                {
                    "record_type": "item", "id": f"start-result-{branch_id}",
                    "type": "function_call_output", "status": "completed",
                    "response_id": response_id, "created_at": marker_start,
                    "call_id": start_call_id,
                    "output": json.dumps({
                        "schema": "provider-execution-marker/v1", "phase": "START",
                        "branch_id": branch_id, "marker_id": start_marker_id,
                    }),
                },
                {
                    "record_type": "item", "id": f"search-call-{branch_id}",
                    "type": "function_call", "status": "completed",
                    "response_id": response_id, "created_at": marker_start + 1,
                    "model": agent_id, "name": "web_search",
                    "arguments": json.dumps({"query": f"evidence for {branch_id}"}),
                    "call_id": f"call-search-{branch_id}",
                },
                {
                    "record_type": "item", "id": f"search-result-{branch_id}",
                    "type": "function_call_output", "status": "completed",
                    "response_id": response_id, "created_at": marker_start + 2,
                    "call_id": f"call-search-{branch_id}",
                    "output": json.dumps({"results": [{"title": "Evidence"}]}),
                },
                {
                    "record_type": "item", "id": f"end-call-{branch_id}",
                    "type": "function_call", "status": "completed",
                    "response_id": response_id, "created_at": marker_end - 1,
                    "model": agent_id, "name": "mark_provider_execution_end",
                    "arguments": json.dumps({
                        "branch_id": branch_id,
                        "start_marker_id": start_marker_id,
                    }),
                    "call_id": end_call_id,
                },
                {
                    "record_type": "item", "id": f"end-result-{branch_id}",
                    "type": "function_call_output", "status": "completed",
                    "response_id": response_id, "created_at": marker_end,
                    "call_id": end_call_id,
                    "output": json.dumps({
                        "schema": "provider-execution-marker/v1", "phase": "END",
                        "branch_id": branch_id,
                        "marker_id": f"marker-end-{branch_id}",
                        "start_marker_id": start_marker_id,
                    }),
                },
                {
                    "record_type": "item",
                    "id": f"answer-{branch_id}",
                    "type": "message",
                    "status": "completed",
                    "response_id": response_id,
                    "created_by": "assistant",
                    "created_at": response_time,
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": f"Completed {branch_id}."}
                    ],
                },
            )
        ).encode()
        provider = _verify_omnigent_session_export(
            export,
            expected_branch_id=branch_id,
            expected_session_id=session_id,
            expected_agent_id=agent_id,
        )
        receipt = provider.payload
        branch = {
            "schema": "parallel-branch/v1",
            "branch_id": branch_id,
            "question_id": "question-1",
            "objective_confirmation_digest": objective["record_digest"],
            "bounded_question": "Find independent evidence for the fixed matched search.",
            "producer_agent_id": receipt["agent_id"],
            "producer_session_id": receipt["provider_session_id"],
            "started_at": receipt["started_at"],
            "completed_at": receipt["completed_at"],
            "status": "COMPLETED",
            "independent_context": True,
            "invocation_id": receipt["provider_session_id"],
            "invocation_status": "COMPLETED",
            "provider_session_id": receipt["provider_session_id"],
            "provider_receipt_digest": receipt["receipt_digest"],
            "evidence_package_digest": evidence["record_digest"],
        }
        branches.append(
            adapter.journal.append(
                branch,
                source=f"omnigent:{agent_id}",
                links=((evidence["record_digest"], "produced-in-branch"),),
                producer_agent_id=receipt["agent_id"],
                producer_session_id=receipt["provider_session_id"],
                invocation_id=receipt["provider_session_id"],
                invocation_status="COMPLETED",
                provider_invocation=provider,
                invocation_started_at=receipt["started_at"],
                invocation_completed_at=receipt["completed_at"],
            )
        )
    reconciliation = adapter.journal.append(
        {
            "schema": "branch-reconciliation/v1",
            "reconciliation_id": "reconciliation-actual",
            "question_id": "question-1",
            "objective_confirmation_digest": objective["record_digest"],
            "branch_digests": [item["record_digest"] for item in branches],
            "agreements": ["Both sources support a bounded, matched comparison."],
            "conflicts": [],
            "unresolved_questions": ["Generalization beyond the pinned task."],
            "reconciled_evidence_ids": ["claim-1", "claim-2"],
            "parallel_status": "MET",
            "overlapping_branch_pairs": [["branch-method", "branch-registry"]],
        },
        source="omnigent:research-director",
        links=tuple(
            (item["record_digest"], "reconciles-branch") for item in branches
        ),
        producer_agent_id="research-director",
        producer_session_id="reconciliation-session",
    )
    hypotheses = adapter.journal.append(
        _hypotheses(objective["record_digest"]), source="omnigent:hypothesis-scientist",
        links=((reconciliation["record_digest"], "supports-hypotheses"),),
    )
    portfolio_record = _experiment_candidates(objective["record_digest"])
    search_candidates = [
        {
            "candidate_id": candidate_id,
            "feature_indices": feature_indices,
            "neighbors": neighbors,
            "evidence_rationale": f"Reviewed rationale for {candidate_id}.",
            "evidence_references": ["claim-1"],
        }
        for candidate_id, feature_indices, neighbors in (
            ("sepal-k15", [0, 1], 15),
            ("sepal-k7", [0, 1], 7),
            ("all-k7", [0, 1, 2, 3], 7),
            ("petal-k5", [2, 3], 5),
        )
    ]
    approved_parameters = {
        "search_candidates": search_candidates,
        "baseline_order": ["sepal-k15", "sepal-k7", "all-k7", "petal-k5"],
        "evidence_guided_order": ["petal-k5", "all-k7", "sepal-k7", "sepal-k15"],
        "split_seed": 1729,
        "threshold": 0.9,
        "max_trials_per_arm": 4,
        "max_seconds_per_arm": 30.0,
        "quality_noninferiority_margin": 0.02,
    }
    portfolio_record.update(
        {
            "primary_metric": "trials_to_threshold",
            "dataset_identity": {
                "identifier": "synthetic-proxy-openml-task-59-v1",
                "version": "1",
                "digest": fixture_digest,
            },
                "resource_bounds": {
                    "max_trials": 8, "max_runtime_minutes": 5, "max_cost_usd": 0,
                    "compute": "local CPU",
                    "network_access": "read-only-openml",
                    "mutation_permissions": ["artifact directory only"],
                },
        }
    )
    for candidate in portfolio_record["candidates"]:
        candidate.update(
            {
                "parameters": approved_parameters,
                "random_seeds": [approved_parameters["split_seed"]],
                "metrics": ["trials_to_threshold", "accuracy"],
                "estimated_runtime_minutes": 1,
                "estimated_cost_usd": 0,
            }
        )
    portfolio = adapter.journal.append(
        portfolio_record, source="omnigent:experiment-designer",
        links=((hypotheses["record_digest"], "tests-hypothesis"),
               (feasibility["record_digest"], "bounded-by-feasibility")),
    )
    review = adapter.journal.append(
        _safety_review(portfolio), source="omnigent:safety-reviewer",
        links=((portfolio["record_digest"], "reviews-selected-experiment"),),
    )
    prepared = adapter.prepare(
        portfolio, review, objective_confirmation_digest=objective["record_digest"],
        approval_digest=_record_approval(adapter, portfolio, review)["record_digest"],
    )
    _mark_launched(adapter, prepared, run_id="actual-run")
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    artifact_dir = tmp_path / "actual-artifacts"
    outcome = run_matched_experiment(
        human_objective,
        artifact_dir=artifact_dir,
        live=True,
        authorization=ExecutionAuthorization(
            journal_path=adapter.journal.path,
            experiment_id=prepared.experiment_id,
            objective_confirmation_digest=prepared.objective_confirmation_digest,
            experiment_digest=prepared.experiment_digest,
            approval_digest=prepared.approval_digest,
            task_card_digest=prepared.task_card_digest,
        ),
    )
    assert outcome.approved_candidate_parameters == approved_parameters
    result = validate_record(outcome.as_experiment_result(
        question_id="question-1", experiment_id=prepared.experiment_id,
        run_id="actual-run", experiment_digest=prepared.experiment_digest,
        approval_digest=prepared.approval_digest,
        task_card_digest=prepared.task_card_digest,
    ))
    assert result["parameters"]["approved_candidate_parameters"] == approved_parameters
    assert result["parameters"]["observed_preregistration"] == outcome.preregistration
    harness_result = adapter.build_result_envelope(
        prepared.experiment_id,
        result,
        summary="Matched fixture experiment completed under the approved authority.",
        evidence=("artifact:matched-result.json",),
        completed_at=result["completed_at"],
    )
    harness_root = tmp_path / "isolated-harness"
    workspace = tmp_path / "isolated-workspace"
    worktree = tmp_path / "isolated-worktree"
    (harness_root / "local-config").mkdir(parents=True)
    workspace.mkdir()
    worktree.mkdir()
    (harness_root / "local-config" / "harness-config.json").write_text(
        json.dumps(
            {"root_workspace": str(workspace), "managed_coordination": "disabled"}
        ),
        encoding="utf-8",
    )
    (worktree / "RESULT.json").write_text(json.dumps(harness_result), encoding="utf-8")
    task_card = json.loads(prepared.task_card_path.read_text(encoding="utf-8"))
    lane = {
        "lane_id": prepared.lane_id,
        "run_id": "actual-run",
        "task_card_hash": task_card["content_hash"],
        "invocation_hash": "invocation-actual",
        "worktree_path": str(worktree),
        "git": {"branch": "experiment/actual", "bootstrap_tip": "b" * 40},
    }
    lane["result_validation"] = {
        "run_id": "actual-run",
        "result_hash": harness_result["content_hash"],
        "invocation_hash": lane["invocation_hash"],
        "branch": lane["git"]["branch"],
        "commit": "c" * 40,
        "clean": True,
    }
    harness_accepted_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    review_record = {
        "schema": "completion-review/v1",
        "lane_id": prepared.lane_id,
        "run_id": "actual-run",
        "task_card_id": task_card["content_hash"],
        "task_card_hash": task_card["content_hash"],
        "invocation_hash": lane["invocation_hash"],
        "commit": "c" * 40,
        "review_outcome": "PASS",
        "review_summary": "Exact matched result and authority reviewed.",
        "evidence": ["artifact:matched-result.json"],
        "result_id": "actual-run",
        "result_hash": harness_result["content_hash"],
        "reviewed_at": harness_accepted_at,
    }
    review_record["content_hash"] = content_hash(review_record)
    acceptance = {
        "schema": "orchestrator-acceptance/v1",
        "lane_id": prepared.lane_id,
        "run_id": "actual-run",
        "task_card_id": task_card["content_hash"],
        "task_card_hash": task_card["content_hash"],
        "invocation_hash": lane["invocation_hash"],
        "commit": "c" * 40,
        "result_id": "actual-run",
        "result_hash": harness_result["content_hash"],
        "approval": "ACCEPTED",
        "accepted_by": "ROOT",
        "review_ref": review_record["content_hash"],
        "decided_at": harness_accepted_at,
    }
    acceptance["content_hash"] = content_hash(acceptance)
    lane["acceptance_advancement"] = acceptance
    epoch_id = _publish_active_lane(harness_root, workspace, lane)
    publication = (
        workspace / ".harness-runtime" / "epochs" / epoch_id
        / "lanes" / prepared.lane_id
    )
    publication.mkdir(parents=True, exist_ok=True)
    (publication / "COMPLETION_REVIEW.json").write_text(
        json.dumps(review_record), encoding="utf-8"
    )
    (publication / "ORCHESTRATOR_ACCEPTANCE.json").write_text(
        json.dumps(acceptance), encoding="utf-8"
    )
    adapter.harness_root = harness_root
    terminal = adapter.terminal_evidence(prepared.experiment_id)
    assert terminal["result"]["scientific_result"] == result
    stored = adapter.ingest_harness_result(
        prepared.experiment_id, artifact_base_dir=artifact_dir
    )
    assert stored["run_id"] == "actual-run"
    assert "decision_latency_seconds" not in stored["metrics"]
    accepted_binding = adapter.journal.experiment_status(prepared.experiment_id)
    assert accepted_binding is not None
    assert accepted_binding["acceptance_decided_at"] == acceptance["decided_at"]
    assert accepted_binding["acceptance_digest"] == acceptance["content_hash"]
    decision = adapter.journal.append(
        {
            "schema": "updated-decision/v1",
            "run_id": "actual-run",
            "question_id": "question-1",
            "objective_confirmation_digest": objective["record_digest"],
            "hypothesis_id": "hypothesis-1",
            "experiment_id": prepared.experiment_id,
            "result_digest": stored["record_digest"],
            "decision": "support",
            "rationale": "The guided arm reached the preregistered endpoint sooner.",
            "supporting_evidence_ids": ["claim-1", "claim-2"],
            "remaining_uncertainty": ["One pinned benchmark is not broad replication."],
            "interpreted_metrics": ["trials_to_threshold", "accuracy"],
            "next_experiment": {
                "question": "Does the result replicate on another public task?",
                "rationale": "Test whether the ordering effect generalizes.",
            },
            "human_review_required": True,
        },
        source="omnigent:results-analyst",
        links=((stored["record_digest"], "interprets-result"),),
        producer_agent_id="results-analyst",
        producer_session_id="analysis-session",
    )
    assert decision["decision_timing"]["result_digest"] == stored["record_digest"]
    assert decision["decision_timing"]["result_accepted_at"] == acceptance["decided_at"]
    assert decision["decision_timing"]["harness_acceptance_digest"] == acceptance[
        "content_hash"
    ]
    summary = validate_record(outcome.as_acceleration_summary(
        acceleration_summary_id="acceleration-actual",
        question_id="question-1",
        experiment_id=prepared.experiment_id,
        result_digest=stored["record_digest"],
        updated_decision=decision,
    ))
    acceleration = adapter.journal.append(
        summary,
        source="omnigent:results-analyst",
        links=((decision["record_digest"], "quantifies-acceleration"),),
        producer_agent_id="results-analyst",
        producer_session_id="analysis-session",
    )
    assert acceleration["result_digest"] == stored["record_digest"]
    receipt = adapter.journal.learning_receipt("question-1", final=True)
    reopened = ResearchJournal(adapter.journal.path).learning_receipt(
        "question-1", final=True
    )
    assert reopened == receipt
    assert receipt["reconciliation_digest"] == reconciliation["record_digest"]
