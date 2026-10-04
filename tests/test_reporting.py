from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_researcher.reporting import (
    build_rubric_artifact_map,
    render_research_report,
    rubric_artifact_json,
)


ROOT = Path(__file__).resolve().parents[1]


def complete_chain() -> dict:
    return {
        "objective": {
            "status": "CONFIRMED",
            "question": "Can guided selection need fewer trials?",
            "confirmed_by": "human-scientist",
        },
        "parallel_evidence": {
            "status": "UNMET",
            "reason": "Fixture contains no authoritative overlapping intervals.",
        },
        "hypothesis": {
            "status": "AGENT_GENERATED",
            "statement": "Guidance reduces trials to threshold.",
        },
        "candidates": {
            "selected": "guided",
            "compared": ["fixed", "guided"],
        },
        "safety": {"verdict": "APPROVAL_REQUIRED"},
        "approval": {"status": "NOT_GRANTED", "human_gate": True},
        "result": {"status": "NOT_RUN", "source": "fixture"},
        "decision": {"status": "UNAVAILABLE_PENDING_RESULT"},
        "acceleration_10x_path": {
            "observed": "NOT_ESTIMABLE",
            "forecast": "Requires multi-task prospective validation.",
        },
        "rubric_evidence": {
            "omnigent_orchestration": {
                "status": "PARTIAL",
                "artifacts": ["agents/research-director/config.yaml"],
            },
            "scientific_rigor": {
                "status": "MET",
                "artifacts": ["tests/test_research_integration.py"],
            },
        },
    }


def reconstructed_chain() -> dict:
    records = [
        {
            "schema": "research-question/v1",
            "question_id": "question-1",
            "question": "Can guided selection need fewer trials?",
            "record_digest": "question-digest",
        },
        {
            "schema": "objective-confirmation/v1",
            "objective_confirmation_id": "objective-1",
            "confirmed_by": "human-scientist",
            "record_digest": "objective-digest",
        },
        {
            "schema": "feasibility-check/v1",
            "feasibility_check_id": "feasibility-1",
            "overall_status": "PASS",
            "record_digest": "feasibility-digest",
        },
        {
            "schema": "evidence-package/v1",
            "evidence_package_id": "evidence-b",
            "record_digest": "evidence-b-digest",
        },
        {
            "schema": "evidence-package/v1",
            "evidence_package_id": "evidence-a",
            "record_digest": "evidence-a-digest",
        },
        {
            "schema": "parallel-branch/v1",
            "branch_id": "branch-b",
            "record_digest": "branch-b-digest",
        },
        {
            "schema": "parallel-branch/v1",
            "branch_id": "branch-a",
            "record_digest": "branch-a-digest",
        },
        {
            "schema": "branch-reconciliation/v1",
            "reconciliation_id": "reconciliation-b",
            "record_digest": "reconciliation-b-digest",
        },
        {
            "schema": "branch-reconciliation/v1",
            "reconciliation_id": "reconciliation-a",
            "record_digest": "reconciliation-a-digest",
        },
        {
            "schema": "hypothesis-portfolio/v1",
            "question_id": "question-1",
            "hypotheses": [{"hypothesis_id": "hypothesis-1"}],
            "record_digest": "hypothesis-digest",
        },
        {
            "schema": "experiment-candidates/v1",
            "question_id": "question-1",
            "selected_experiment_id": "experiment-guided",
            "record_digest": "candidates-digest",
        },
        {
            "schema": "safety-review/v1",
            "experiment_id": "experiment-guided",
            "verdict": "APPROVAL_REQUIRED",
            "record_digest": "safety-digest",
        },
        {
            "schema": "human-approval/v1",
            "approval_id": "approval-1",
            "approved": True,
            "record_digest": "approval-digest",
        },
        {
            "schema": "experiment-result/v1",
            "run_id": "run-1",
            "status": "PASS",
            "record_digest": "result-digest",
        },
        {
            "schema": "updated-decision/v1",
            "run_id": "run-1",
            "decision": "revise",
            "record_digest": "decision-digest",
        },
        {
            "schema": "acceleration-summary/v1",
            "acceleration_summary_id": "acceleration-1",
            "outcome": "NO_IMPROVEMENT",
            "record_digest": "acceleration-digest",
        },
    ]
    return {
        "question_id": "question-1",
        "records": records,
        "links": [],
        "provenance": [],
    }


def test_terminal_report_has_fixed_order_and_is_deterministic() -> None:
    chain = complete_chain()
    report = render_research_report(chain)
    reordered = dict(reversed(list(chain.items())))

    assert report == render_research_report(reordered)
    headings = [
        "OBJECTIVE",
        "PARALLEL EVIDENCE",
        "HYPOTHESIS",
        "CANDIDATES",
        "SAFETY",
        "APPROVAL",
        "RESULT",
        "DECISION",
        "ACCELERATION / 10X PATH",
    ]
    offsets = [report.index(heading) for heading in headings]
    assert offsets == sorted(offsets)
    assert "human-scientist" in report
    assert "NOT_ESTIMABLE" in report


def test_terminal_report_marks_missing_evidence_unavailable() -> None:
    report = render_research_report({"objective": {"status": "PROPOSED"}})

    assert report.count("[UNAVAILABLE]") == 8
    assert "live run completed" not in report.lower()
    assert "10x achieved" not in report.lower()


def test_terminal_report_accepts_direct_learning_receipt_and_shows_identity() -> None:
    receipt = {
        "schema": "learning-receipt/v1",
        "question_id": "question-1",
        "question_digest": "q-digest",
        "objective_confirmation_digest": "objective-digest",
        "evidence_package_digests": ["evidence-b", "evidence-a"],
        "receipt_digest": "receipt-digest",
    }

    report = render_research_report(receipt)

    assert "RECEIPT DIGEST: receipt-digest" in report
    assert '"question_id": "question-1"' in report
    assert '"evidence_package_digests"' in report


def test_terminal_report_consumes_reconstructed_chain_deterministically() -> None:
    chain = reconstructed_chain()
    reversed_chain = chain | {"records": list(reversed(chain["records"]))}

    report = render_research_report(chain)

    assert report == render_research_report(reversed_chain)
    assert '"research_question"' in report
    assert '"objective_confirmation"' in report
    assert '"feasibility_checks"' in report
    assert report.index('"evidence_package_id": "evidence-a"') < report.index(
        '"evidence_package_id": "evidence-b"'
    )
    assert report.index('"branch_id": "branch-a"') < report.index(
        '"branch_id": "branch-b"'
    )
    assert report.index('"reconciliation_id": "reconciliation-a"') < report.index(
        '"reconciliation_id": "reconciliation-b"'
    )
    assert '"decision": "revise"' in report
    assert report.count("[UNAVAILABLE]") == 0


def test_terminal_report_supports_nested_chain_and_receipt() -> None:
    chain = reconstructed_chain()
    chain["records"] = [
        record
        for record in chain["records"]
        if record["schema"] != "experiment-result/v1"
    ]
    supplied = {
        "research_chain": chain,
        "learning_receipt": {
            "schema": "learning-receipt/v1",
            "receipt_digest": "receipt-digest",
            "experiment_result_digest": "result-from-receipt",
        },
    }

    report = render_research_report(supplied)

    assert "RECEIPT DIGEST: receipt-digest" in report
    assert '"experiment_result_digest": "result-from-receipt"' in report
    assert '"question": "Can guided selection need fewer trials?"' in report


def test_terminal_report_rejects_conflicting_singular_records() -> None:
    chain = reconstructed_chain()
    chain["records"].append(
        {
            "schema": "updated-decision/v1",
            "run_id": "run-2",
            "decision": "support",
            "record_digest": "decision-2-digest",
        }
    )

    with pytest.raises(ValueError, match="conflicting.*updated-decision/v1"):
        render_research_report(chain)


def test_rubric_mapping_requires_explicit_status_and_totals_100_percent() -> None:
    mapping = build_rubric_artifact_map(complete_chain())

    assert mapping["schema"] == "rubric-artifact-map/v1"
    assert sum(item["weight_percent"] for item in mapping["criteria"]) == 100
    by_id = {item["criterion_id"]: item for item in mapping["criteria"]}
    assert by_id["omnigent_orchestration"]["status"] == "PARTIAL"
    assert by_id["scientific_rigor"]["status"] == "MET"
    assert by_id["breakthrough_potential"]["status"] == "UNAVAILABLE"
    assert by_id["breakthrough_potential"]["evidence_artifacts"] == []


def test_rubric_json_is_canonical_and_does_not_infer_live_evidence() -> None:
    first = rubric_artifact_json(complete_chain())
    second = rubric_artifact_json(dict(reversed(list(complete_chain().items()))))

    assert first == second
    decoded = json.loads(first)
    assert decoded["criteria"][0]["criterion_id"] == "omnigent_orchestration"
    assert '"status":"UNAVAILABLE"' in first


@pytest.mark.parametrize(
    "bad_chain",
    [None, [], "chain"],
)
def test_reporting_rejects_non_mapping_input(bad_chain: object) -> None:
    with pytest.raises(TypeError, match="mapping"):
        render_research_report(bad_chain)  # type: ignore[arg-type]


def test_rubric_mapping_rejects_unrecognized_claim_status() -> None:
    chain = {"rubric_evidence": {"scientific_rigor": {"status": "PASSED"}}}

    with pytest.raises(ValueError, match="rubric status"):
        build_rubric_artifact_map(chain)


def test_report_cli_renders_stdout_and_writes_rubric_json(tmp_path: Path) -> None:
    chain_path = tmp_path / "chain.json"
    rubric_path = tmp_path / "rubric.json"
    chain_path.write_text(json.dumps(complete_chain()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_research_report.py"),
            str(chain_path),
            "--rubric-output",
            str(rubric_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == render_research_report(complete_chain())
    assert rubric_path.read_text(encoding="utf-8") == rubric_artifact_json(
        complete_chain()
    )
    assert list(tmp_path.glob(".rubric.json.*.tmp")) == []


def test_matched_experiment_cli_is_explicitly_fixture_and_writes_result(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "matched-result.json"
    artifact_dir = tmp_path / "trial-artifacts"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_matched_experiment.py"),
            "--mode",
            "fixture",
            "--objective",
            "Test a bounded evidence-guided selection proxy.",
            "--primary-metric",
            "trials_to_threshold",
            "--openml-task-id",
            "59",
            "--dataset-identifier",
            "synthetic-proxy-openml-task-59-v1",
            "--openml-dataset-id",
            "61",
            "--openml-dataset-version",
            "1",
            "--dataset-digest",
            "e47234e8ba0a4c512a49e895747d8f51f9d8e9d4d75f405070e9d279589063a4",
            "--risk-tolerance",
            "low; local CPU only",
            "--execution-scope-json",
            json.dumps(
                {
                    "max_trials": 8,
                    "max_runtime_minutes": 2,
                    "max_cost_usd": 0,
                    "compute": "local CPU",
                    "network_access": "none",
                    "mutation_permissions": ["artifact directory only"],
                }
            ),
            "--data-governance-json",
            json.dumps(
                {
                    "license_status": "VERIFIED",
                    "license_evidence": "Original synthetic fixture under CC0-1.0.",
                    "privacy_status": "VERIFIED",
                    "privacy_evidence": "Synthetic flower measurements contain no people.",
                    "verified_by": "fixture-test-human",
                    "verified_at": "2026-10-03T12:00:00Z",
                }
            ),
            "--confirmed-by",
            "fixture-test-human",
            "--confirmed-at",
            "2026-10-03T12:00:00Z",
            "--artifact-dir",
            str(artifact_dir),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["execution_mode"] == "hermetic-fixture"
    assert result["preflight"]["checks"]["license"] == "PASS"
    assert "not scientific evidence" in completed.stdout.lower()
    assert (artifact_dir / "baseline-trials.json").is_file()
    assert (artifact_dir / "evidence-guided-trials.json").is_file()
