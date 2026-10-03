from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_researcher.harness_adapter import HarnessAdapter, HarnessIntegrationError
from ai_researcher.journal import JournalConflictError, ResearchJournal
from ai_researcher.records import RecordValidationError, experiment_digest, validate_record


ROOT = Path(__file__).resolve().parents[1]


def experiment_candidates() -> dict:
    return {
        "schema": "experiment-candidates/v1",
        "question_id": "question-1",
        "hypothesis_id": "hypothesis-1",
        "candidates": [
            {
                "experiment_id": "experiment-guided",
                "method": "Run evidence-guided selection on a fixed split.",
                "baseline": "Fixed grid search on the same split.",
                "controls": ["same split", "same seeds"],
                "inputs": ["openml-task-31"],
                "parameters": {"trials": 4},
                "random_seeds": [7, 11],
                "metrics": ["validation_accuracy", "trial_count"],
                "success_threshold": "Reach target accuracy in fewer trials.",
                "expected_learning": "Whether evidence improves sample efficiency.",
                "estimated_runtime_minutes": 20,
                "estimated_cost_usd": 1,
                "risk_level": "low",
            },
            {
                "experiment_id": "experiment-ablation",
                "method": "Remove reviewed failure memory.",
                "baseline": "Use reviewed failure memory.",
                "controls": ["same split", "same seeds"],
                "inputs": ["openml-task-31"],
                "parameters": {"trials": 4},
                "random_seeds": [7, 11],
                "metrics": ["validation_accuracy", "trial_count"],
                "success_threshold": "Detect a trial-count difference.",
                "expected_learning": "Whether reviewed failures affect selection.",
                "estimated_runtime_minutes": 20,
                "estimated_cost_usd": 1,
                "risk_level": "low",
            },
        ],
        "selected_experiment_id": "experiment-guided",
        "selection_rationale": "Best expected learning under the time budget.",
        "rejected_candidate_rationales": {"experiment-ablation": "Run second."},
    }


def safety_review() -> dict:
    return {
        "schema": "safety-review/v1",
        "experiment_id": "experiment-guided",
        "verdict": "APPROVAL_REQUIRED",
        "risks": ["Compute overrun"],
        "required_controls": ["Hard four-trial cap"],
        "prohibited_actions": ["No external data mutation"],
        "approval_question": "Approve this exact four-trial experiment?",
        "review_limitations": [],
    }


def approval(portfolio: dict) -> dict:
    return {
        "schema": "human-approval/v1",
        "approval_id": "approval-1",
        "experiment_id": "experiment-guided",
        "experiment_digest": experiment_digest(portfolio),
        "approved": True,
        "approved_by": "test-human",
        "approved_at": "2026-10-03T16:00:00Z",
        "scope": "execute-exact-experiment",
        "constraints": ["Hard four-trial cap"],
    }


def test_experiment_portfolio_requires_competing_candidates() -> None:
    portfolio = experiment_candidates()
    portfolio["candidates"] = portfolio["candidates"][:1]
    with pytest.raises(RecordValidationError, match="at least two"):
        validate_record(portfolio)


def test_journal_rejects_conflicting_identity(tmp_path: Path) -> None:
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    record = {
        "schema": "research-question/v1",
        "question_id": "question-1",
        "question": "Does the method improve trial efficiency?",
        "domain": "AI research",
        "measurable_outcome": "Trials to target",
        "primary_metric": "trial_count",
        "constraints": [],
        "assumptions": [],
    }
    journal.append(record, source="test")
    changed = dict(record, question="A different question")
    with pytest.raises(JournalConflictError):
        journal.append(changed, source="test")


def test_approval_stages_exact_harness_task_without_launch(tmp_path: Path) -> None:
    portfolio = experiment_candidates()
    adapter = HarnessAdapter(
        ROOT,
        journal_path=tmp_path / "journal.sqlite3",
        artifact_root=tmp_path / "tasks",
    )
    request = adapter.approval_request(portfolio, safety_review())
    assert request["experiment_digest"] == experiment_digest(portfolio)
    prepared = adapter.prepare(portfolio, safety_review(), approval(portfolio))
    assert prepared.task_card_path.is_file()
    task = json.loads(prepared.task_card_path.read_text(encoding="utf-8"))
    assert task["schema"] == "project-task-card/v1"
    assert prepared.approval_digest in task["task"]
    assert adapter.status("experiment-guided")["status"] == "STAGED"


def test_mismatched_approval_fails_closed(tmp_path: Path) -> None:
    portfolio = experiment_candidates()
    wrong = approval(portfolio)
    wrong["experiment_digest"] = "0" * 64
    adapter = HarnessAdapter(
        ROOT,
        journal_path=tmp_path / "journal.sqlite3",
        artifact_root=tmp_path / "tasks",
    )
    with pytest.raises(HarnessIntegrationError, match="does not bind"):
        adapter.prepare(portfolio, safety_review(), wrong)


def test_launch_requires_independent_environment_gate(tmp_path: Path, monkeypatch) -> None:
    portfolio = experiment_candidates()
    adapter = HarnessAdapter(
        ROOT,
        journal_path=tmp_path / "journal.sqlite3",
        artifact_root=tmp_path / "tasks",
    )
    prepared = adapter.prepare(portfolio, safety_review(), approval(portfolio))
    monkeypatch.delenv("AI_RESEARCHER_ENABLE_EXECUTION", raising=False)
    with pytest.raises(HarnessIntegrationError, match="execution is disabled"):
        adapter.launch(
            prepared,
            confirmation=prepared.approval_digest,
            provider="codex",
            model="test-model",
        )


def test_result_closes_staged_binding(tmp_path: Path) -> None:
    portfolio = experiment_candidates()
    adapter = HarnessAdapter(
        ROOT,
        journal_path=tmp_path / "journal.sqlite3",
        artifact_root=tmp_path / "tasks",
    )
    adapter.prepare(portfolio, safety_review(), approval(portfolio))
    result = {
        "schema": "experiment-result/v1",
        "experiment_id": "experiment-guided",
        "run_id": "run-1",
        "execution_source": "integrated-harness",
        "code_identity": "commit-1",
        "dataset_identity": "openml-31-v1",
        "environment_identity": "lock-1",
        "parameters": {"trials": 4},
        "random_seeds": [7, 11],
        "metrics": {"validation_accuracy": 0.91, "trial_count": 3},
        "artifact_refs": ["artifact://run-1/metrics.json"],
        "started_at": "2026-10-03T16:00:00Z",
        "completed_at": "2026-10-03T16:10:00Z",
        "status": "PASS",
        "limitations": [],
    }
    stored = adapter.record_result(result)
    assert stored["record_digest"]
    assert adapter.status("experiment-guided")["status"] == "COMPLETED"
