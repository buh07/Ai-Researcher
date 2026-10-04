from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
import os
import runpy
import time
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_researcher import experiment
from ai_researcher.experiment import (
    ArmWorkflowMeasurements,
    ArmResult,
    DataGovernanceAttestation,
    Endpoint,
    ExecutionAuthorization,
    ExperimentConfig,
    ExperimentValidationError,
    HumanExecutionScope,
    HumanObjective,
    calculate_acceleration,
    preflight,
    run_matched_experiment,
)
from ai_researcher.journal import ResearchJournal
from ai_researcher.records import (
    RecordValidationError,
    canonical_json,
    experiment_digest,
    validate_record,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "openml"
FIXTURE_DIGEST = json.loads(
    (FIXTURE_DIR / "task_59_proxy.metadata.json").read_text(encoding="utf-8")
)["sha256"]


def confirmed_objective(
    *,
    objective_digest: str | None = None,
    scope: HumanExecutionScope | None = None,
    governance: DataGovernanceAttestation | None = None,
    dataset_digest: str = FIXTURE_DIGEST,
) -> HumanObjective:
    return HumanObjective(
        objective=(
            "Test whether a preregistered evidence-guided ordering reaches the "
            "accuracy target in fewer trials than a fixed baseline ordering."
        ),
        primary_metric="trials_to_threshold",
        openml_task_id=59,
        dataset_identifier="synthetic-proxy-openml-task-59-v1",
        openml_dataset_id=61,
        openml_dataset_version=1,
        dataset_digest=dataset_digest,
        risk_tolerance="low",
        execution_scope=scope
        or HumanExecutionScope(
            max_trials=8,
            max_runtime_minutes=5.0,
            max_cost_usd=0.0,
            compute="local CPU",
            network_access="none",
            mutation_permissions=("artifact directory only",),
        ),
        data_governance=governance
        or DataGovernanceAttestation(
            license_status="VERIFIED",
            license_evidence="Fixture metadata and CC0 dedication were reviewed.",
            privacy_status="VERIFIED",
            privacy_evidence="Synthetic flower measurements contain no personal data.",
            verified_by="test-scientist",
            verified_at="2026-10-03T11:59:00Z",
        ),
        confirmed_by="test-scientist",
        confirmed_at="2026-10-03T12:00:00Z",
        objective_confirmation_digest=objective_digest,
    )


def decision_for_result(
    result: dict,
    *,
    objective_digest: str,
    latency_seconds: float,
) -> dict:
    accepted = datetime.fromisoformat(result["completed_at"].replace("Z", "+00:00"))
    timing = {
        "schema": "decision-timing-measurement/v1",
        "result_digest": result["record_digest"],
        "run_id": result["run_id"],
        "harness_acceptance_digest": "e" * 64,
        "result_accepted_at": accepted.isoformat(),
        "decision_completed_at": (
            accepted + timedelta(seconds=latency_seconds)
        ).isoformat(),
        "latency_seconds": latency_seconds,
    }
    return validate_record(
        {
            "schema": "updated-decision/v1",
            "run_id": result["run_id"],
            "question_id": result["question_id"],
            "objective_confirmation_digest": objective_digest,
            "hypothesis_id": "hypothesis-1",
            "experiment_id": result["experiment_id"],
            "result_digest": result["record_digest"],
            "decision": "support",
            "rationale": "Interpretation of the accepted immutable result.",
            "interpreted_metrics": ["trials_to_threshold", "accuracy"],
            "supporting_evidence_ids": [],
            "remaining_uncertainty": ["One task."],
            "next_experiment": {
                "question": "Does the result replicate?",
                "rationale": "Reduce uncertainty.",
            },
            "human_review_required": True,
            "decision_timing": timing,
            "decision_timing_source_digest": hashlib.sha256(
                canonical_json(timing)
            ).hexdigest(),
        }
    )


def test_primary_endpoint_is_trials_to_threshold_and_accuracy_is_quality() -> None:
    objective = confirmed_objective()

    assert objective.primary_metric == "trials_to_threshold"
    assert objective.quality_metric == "accuracy"
    with pytest.raises(ExperimentValidationError, match="trials_to_threshold"):
        replace(objective, primary_metric="accuracy")


def test_fixture_preflight_is_digest_bound_and_explicit_about_proxy_data(
    tmp_path: Path,
) -> None:
    first = preflight(confirmed_objective(), fixture_dir=FIXTURE_DIR)
    second = preflight(confirmed_objective(), fixture_dir=FIXTURE_DIR)

    assert first.preflight_digest == second.preflight_digest
    assert first.checks["objective_confirmation"] == "UNBOUND_FIXTURE"
    assert set(first.checks.values()) == {"PASS", "UNBOUND_FIXTURE"}
    assert first.dataset["mode"] == "synthetic-hermetic-proxy"
    assert first.dataset["scientific_use"] == "tests-only"
    assert first.dataset["openml_task_id"] == 59
    assert first.dataset["license_spdx"] == "CC0-1.0"
    assert len(first.dataset["sha256"]) == 64

    with pytest.raises(ExperimentValidationError, match="journal objective"):
        first.as_feasibility_check(
            feasibility_check_id="feasibility-1",
            question_id="question-1",
            checked_by="test-runner",
            checked_at="2026-10-03T12:01:00Z",
            fallback="Stop and request a newly confirmed dataset.",
            journal_path=tmp_path / "journal.sqlite3",
        )

    journal_path = tmp_path / "bound-journal.sqlite3"
    journal = ResearchJournal(journal_path)
    question = journal.append(
        {
            "schema": "research-question/v1",
            "question_id": "question-1",
            "question": "Can guided ordering reduce trials to target?",
            "domain": "machine learning",
            "intended_scientific_use": "A bounded workflow-acceleration demonstration.",
            "measurable_outcome": "Trials to accuracy target",
            "primary_metric": "trials_to_threshold",
            "constraints": ["bounded fixture"],
            "assumptions": ["fixed split"],
        },
        source="human:test",
    )
    objective_record = journal.append(
        {
            "schema": "objective-confirmation/v1",
            "objective_confirmation_id": "objective-1",
            "question_id": "question-1",
            "question_digest": question["record_digest"],
            "primary_metric": "trials_to_threshold",
            "dataset": {
                "identifier": "synthetic-proxy-openml-task-59-v1",
                "version": "1",
                "digest": FIXTURE_DIGEST,
                "source": (FIXTURE_DIR / "task_59_proxy.csv").as_uri(),
            },
            "risk_tolerance": {
                "level": "low",
                "allowed_risks": ["inconclusive fixture result"],
                "prohibited_actions": ["external mutation"],
                "privacy_constraints": ["verified non-personal data"],
                "acceptable_failure_modes": ["trial failure"],
            },
            "execution_scope": {
                "max_trials": 8,
                "max_runtime_minutes": 5.0,
                "max_cost_usd": 0.0,
                "compute": "local CPU",
                "network_access": "none",
                "mutation_permissions": ["artifact directory only"],
            },
            "confirmed_by": "test-scientist",
            "confirmed_at": "2026-10-03T12:00:00Z",
        },
        source="human:test",
        links=((question["record_digest"], "confirms-objective"),),
    )
    bound = preflight(
        confirmed_objective(objective_digest=objective_record["record_digest"]),
        fixture_dir=FIXTURE_DIR,
    )
    feasibility = bound.as_feasibility_check(
        feasibility_check_id="feasibility-1",
        question_id="question-1",
        checked_by="test-runner",
        checked_at="2026-10-03T12:01:00Z",
        fallback="Stop and request a newly confirmed dataset.",
        journal_path=journal_path,
    )
    assert validate_record(feasibility)["overall_status"] == "PASS"


def test_preflight_fails_closed_when_objective_or_fixture_is_not_exact(
    tmp_path: Path,
) -> None:
    with pytest.raises(ExperimentValidationError, match="confirmed_by"):
        preflight(replace(confirmed_objective(), confirmed_by=""), fixture_dir=FIXTURE_DIR)

    copied = tmp_path / "openml"
    copied.mkdir()
    for name in ("task_59_proxy.csv", "task_59_proxy.metadata.json"):
        (copied / name).write_bytes((FIXTURE_DIR / name).read_bytes())
    (copied / "task_59_proxy.csv").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ExperimentValidationError, match="digest"):
        preflight(confirmed_objective(), fixture_dir=copied)

    with pytest.raises(ExperimentValidationError, match="human-confirmed dataset"):
        preflight(
            confirmed_objective(dataset_digest="f" * 64), fixture_dir=FIXTURE_DIR
        )


def test_public_live_preflight_exercises_pinned_openml_transport_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise ``live=True`` through HTTP parsing, not a replaced data loader."""

    live_url = "https://fixtures.invalid/openml/iris.arff"
    raw_arff = b"""@RELATION iris
@ATTRIBUTE sepal_length NUMERIC
@ATTRIBUTE sepal_width NUMERIC
@ATTRIBUTE petal_length NUMERIC
@ATTRIBUTE petal_width NUMERIC
@ATTRIBUTE class {setosa,versicolor,virginica}
@DATA
5.0,3.4,1.3,0.2,setosa
5.4,3.0,1.5,0.2,setosa
6.1,2.8,4.0,1.3,versicolor
6.5,2.8,4.6,1.5,versicolor
6.5,3.0,5.8,2.2,virginica
7.1,3.0,5.9,2.1,virginica
"""
    payloads = {
        experiment.OPENML_TASK_URL: json.dumps(
            {
                "task": {
                    "task_id": 59,
                    "input": [
                        {
                            "name": "source_data",
                            "data_set": {
                                "data_set_id": 61,
                                "target_feature": "class",
                            },
                        }
                    ],
                }
            }
        ).encode(),
        experiment.OPENML_DATASET_METADATA_URL: json.dumps(
            {
                "data_set_description": {
                    "id": 61,
                    "version": 1,
                    "default_target_attribute": "class",
                    "licence": "Public",
                    "url": live_url,
                    "md5_checksum": hashlib.md5(
                        raw_arff, usedforsecurity=False
                    ).hexdigest(),
                }
            }
        ).encode(),
        live_url: raw_arff,
    }
    requests: list[tuple[str, float, str | None]] = []

    def urlopen(request: object, *, timeout: float) -> io.BytesIO:
        url = str(getattr(request, "full_url"))
        user_agent = getattr(request, "get_header")("User-agent")
        requests.append((url, timeout, user_agent))
        return io.BytesIO(payloads[url])

    monkeypatch.setattr(experiment.urllib.request, "urlopen", urlopen)
    dataset_digest = hashlib.sha256(raw_arff).hexdigest()
    dataset_identifier = "openml-task-59-dataset-61-v1"
    scope = HumanExecutionScope(
        max_trials=8,
        max_runtime_minutes=5.0,
        max_cost_usd=0.0,
        compute="local CPU",
        network_access="read-only-openml",
        mutation_permissions=("artifact directory only",),
    )
    journal = ResearchJournal(tmp_path / "journal.sqlite3")
    question = journal.append(
        {
            "schema": "research-question/v1",
            "question_id": "question-live-preflight",
            "question": "Can guided ordering reduce trials on pinned OpenML task 59?",
            "domain": "machine learning",
            "intended_scientific_use": "Verify the live dataset boundary before execution.",
            "measurable_outcome": "Trials to the fixed accuracy target.",
            "primary_metric": "trials_to_threshold",
            "constraints": ["read-only OpenML access", "local CPU"],
            "assumptions": ["OpenML task identity remains pinned"],
        },
        source="human:test",
    )
    objective_record = journal.append(
        {
            "schema": "objective-confirmation/v1",
            "objective_confirmation_id": "objective-live-preflight",
            "question_id": question["question_id"],
            "question_digest": question["record_digest"],
            "primary_metric": "trials_to_threshold",
            "dataset": {
                "identifier": dataset_identifier,
                "version": "1",
                "digest": dataset_digest,
                "source": experiment.OPENML_TASK_URL,
            },
            "risk_tolerance": {
                "level": "low",
                "allowed_risks": ["bounded download failure"],
                "prohibited_actions": ["external mutation"],
                "privacy_constraints": ["public non-personal data only"],
                "acceptable_failure_modes": ["preflight stops unavailable"],
            },
            "execution_scope": {
                "max_trials": scope.max_trials,
                "max_runtime_minutes": scope.max_runtime_minutes,
                "max_cost_usd": scope.max_cost_usd,
                "compute": scope.compute,
                "network_access": scope.network_access,
                "mutation_permissions": list(scope.mutation_permissions),
            },
            "confirmed_by": "human:test",
            "confirmed_at": "2026-10-03T12:00:00Z",
        },
        source="human:test",
        links=((question["record_digest"], "confirms-objective"),),
    )
    objective = HumanObjective(
        objective=question["question"],
        primary_metric="trials_to_threshold",
        openml_task_id=59,
        dataset_identifier=dataset_identifier,
        openml_dataset_id=61,
        openml_dataset_version=1,
        dataset_digest=dataset_digest,
        risk_tolerance="low",
        execution_scope=scope,
        data_governance=DataGovernanceAttestation(
            license_status="VERIFIED",
            license_evidence="OpenML metadata license reviewed by the test scientist.",
            privacy_status="VERIFIED",
            privacy_evidence="Iris contains no personal data.",
            verified_by="human:test",
            verified_at="2026-10-03T11:59:00Z",
        ),
        confirmed_by="human:test",
        confirmed_at="2026-10-03T12:00:00Z",
        objective_confirmation_digest=objective_record["record_digest"],
    )

    runtime = runpy.run_path(
        str(
            ROOT
            / "agents"
            / "research-director"
            / "tools"
            / "research_runtime_core.py"
        )
    )
    preflight_tool = runtime["preflight_confirmed_objective"]

    class AdapterStub:
        def __init__(self, journal: ResearchJournal) -> None:
            self.journal = journal

    preflight_tool.__globals__["_adapter"] = lambda: AdapterStub(journal)
    feasibility = preflight_tool(
        objective_confirmation_digest=objective.objective_confirmation_digest,
        openml_task_id=objective.openml_task_id,
        openml_dataset_id=objective.openml_dataset_id,
        data_governance_json=json.dumps(asdict(objective.data_governance)),
        feasibility_check_id="feasibility-live-preflight",
        checked_by="operator:test",
        checked_at="2026-10-03T12:01:00Z",
        fallback="Stop and seek a newly confirmed objective.",
        producer_agent_id="research-director",
        producer_session_id="preflight-live-session",
        live=True,
    )

    assert feasibility["objective_confirmation_digest"] == objective_record[
        "record_digest"
    ]
    assert feasibility["overall_status"] == "PASS"
    assert set(feasibility["checks"]) == {
        "access",
        "identity",
        "license",
        "privacy",
        "api",
        "compute",
    }
    assert all(item["status"] == "PASS" for item in feasibility["checks"].values())
    assert dataset_digest in feasibility["checks"]["access"]["evidence"]
    assert requests == [
        (experiment.OPENML_TASK_URL, 20.0, "ai-researcher/0.2"),
        (experiment.OPENML_DATASET_METADATA_URL, 20.0, "ai-researcher/0.2"),
        (live_url, 20.0, "ai-researcher/0.2"),
    ]


def test_scope_and_governance_are_enforced_before_execution(tmp_path: Path) -> None:
    too_small = replace(confirmed_objective().execution_scope, max_trials=7)
    with pytest.raises(ExperimentValidationError, match="trial budget exceeds"):
        run_matched_experiment(
            confirmed_objective(scope=too_small), artifact_dir=tmp_path
        )
    short_runtime = replace(
        confirmed_objective().execution_scope, max_runtime_minutes=0.5
    )
    with pytest.raises(ExperimentValidationError, match="runtime budget exceeds"):
        run_matched_experiment(
            confirmed_objective(scope=short_runtime), artifact_dir=tmp_path
        )
    with pytest.raises(ExperimentValidationError, match="cost exceeds"):
        run_matched_experiment(
            confirmed_objective(),
            config=ExperimentConfig(estimated_cost_usd=0.01),
            artifact_dir=tmp_path,
        )

    unknown = replace(
        confirmed_objective().data_governance, privacy_status="UNKNOWN"
    )
    with pytest.raises(ExperimentValidationError, match="privacy status"):
        run_matched_experiment(
            confirmed_objective(governance=unknown), artifact_dir=tmp_path
        )

    measured = ArmWorkflowMeasurements(
        retrieval_seconds=0,
        planning_seconds=0,
        approval_seconds=0,
        preflight_seconds=0,
        agent_tool_seconds=0,
        human_interventions=0,
        cost_usd=0.01,
        token_usage=1,
        source_digest="e" * 64,
    )
    with pytest.raises(ExperimentValidationError, match="measured cost exceeds"):
        run_matched_experiment(
            confirmed_objective(),
            artifact_dir=tmp_path,
            arm_measurements={"baseline": measured, "evidence_guided": measured},
        )


def test_live_mode_fails_before_network_without_exact_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_scope = replace(
        confirmed_objective().execution_scope, network_access="read-only-openml"
    )
    objective = confirmed_objective(
        scope=live_scope,
        objective_digest="d" * 64,
        dataset_digest="38110f3fd3cef003ca4909038a4d6b235f36a85d036dc7eedeff67c5925e826c",
    )
    monkeypatch.delenv("AI_RESEARCHER_ENABLE_EXECUTION", raising=False)
    with pytest.raises(ExperimentValidationError, match="execution is disabled"):
        run_matched_experiment(objective, artifact_dir=tmp_path, live=True)

    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    with pytest.raises(ExperimentValidationError, match="journal-backed"):
        run_matched_experiment(objective, artifact_dir=tmp_path, live=True)

    authorization = ExecutionAuthorization(
        journal_path=tmp_path / "missing.sqlite3",
        experiment_id="experiment-guided",
        objective_confirmation_digest="d" * 64,
        experiment_digest="e" * 64,
        approval_digest="a" * 64,
        task_card_digest="c" * 64,
    )
    with pytest.raises(ExperimentValidationError, match="journal record"):
        run_matched_experiment(
            objective,
            artifact_dir=tmp_path,
            live=True,
            authorization=authorization,
        )


def test_matched_experiment_is_deterministic_bounded_and_auditable(
    tmp_path: Path,
) -> None:
    config = ExperimentConfig(
        threshold=0.90,
        split_seed=1729,
        max_trials_per_arm=4,
        max_seconds_per_arm=5.0,
    )
    outcome = run_matched_experiment(
        confirmed_objective(objective_digest="d" * 64),
        config=config,
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path / "first",
    )
    rerun = run_matched_experiment(
        confirmed_objective(objective_digest="d" * 64),
        config=config,
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path / "second",
    )

    assert outcome.preregistration["digest"] == rerun.preregistration["digest"]
    assert outcome.preregistration["primary_metric"] == "trials_to_threshold"
    assert outcome.preregistration["quality_metric"] == "accuracy"
    assert outcome.preflight.dataset["split_digest"] == rerun.preflight.dataset["split_digest"]
    assert [t.candidate_id for t in outcome.baseline.trials] == [
        t.candidate_id for t in rerun.baseline.trials
    ]
    assert [t.metric for t in outcome.guided.trials] == [
        t.metric for t in rerun.guided.trials
    ]
    assert outcome.baseline.control_digest == outcome.guided.control_digest
    assert outcome.baseline.candidate_set_digest == outcome.guided.candidate_set_digest
    assert len(outcome.baseline.trials) <= config.max_trials_per_arm
    assert len(outcome.guided.trials) <= config.max_trials_per_arm
    assert outcome.guided.trials[0].candidate_id == "petal-k5"
    assert outcome.baseline.trials[0].candidate_id == "sepal-k15"

    for artifact in outcome.artifacts:
        path = tmp_path / "first" / artifact["name"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]

    assert outcome.identities["code"]["sha256"]
    assert outcome.identities["environment"]["python_version"]
    assert outcome.identities["packages"]["ai-researcher"] == "0.2.0"
    assert outcome.identities["lockfile"]["sha256"]
    assert [s["scenario"] for s in outcome.scaling_analysis["scenarios"]] == [
        "conservative",
        "expected",
        "optimistic",
    ]
    assert all(s["kind"] == "forecast" for s in outcome.scaling_analysis["scenarios"])

    assert outcome.preregistration["dataset_identity"] == {
        "identifier": "synthetic-proxy-openml-task-59-v1",
        "version": "1",
        "digest": FIXTURE_DIGEST,
    }
    json.dumps(outcome.to_dict(), allow_nan=False)
    with pytest.raises(ExperimentValidationError, match="journal-verified authority"):
        outcome.as_experiment_result(
            question_id="question-1",
            experiment_id="experiment-guided",
            run_id="fixture-run-1",
            experiment_digest="b" * 64,
            approval_digest="c" * 64,
            task_card_digest="d" * 64,
        )
    with pytest.raises(ExperimentValidationError, match="journal-verified authority"):
        outcome.as_acceleration_summary(
            acceleration_summary_id="acceleration-fixture-run-1",
            question_id="question-1",
            experiment_id="experiment-guided",
            result_digest="a" * 64,
        )
    assert outcome.acceleration["timing_scope"] == "model-evaluation-only"
    assert outcome.acceleration["overhead_included"] is False
    assert outcome.acceleration["overall_discovery_speed_claim"] is False


def test_wall_compute_and_unavailable_provider_resources_are_not_conflated(
    tmp_path: Path,
) -> None:
    wall_value = 0.0
    cpu_value = 0.0

    def wall_clock() -> float:
        nonlocal wall_value
        wall_value += 0.010
        return wall_value

    def cpu_clock() -> float:
        nonlocal cpu_value
        cpu_value += 0.002
        return cpu_value

    outcome = run_matched_experiment(
        confirmed_objective(objective_digest="d" * 64),
        config=ExperimentConfig(max_trials_per_arm=2, max_seconds_per_arm=5.0),
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path,
        monotonic=wall_clock,
        process_clock=cpu_clock,
    )

    for arm in (outcome.baseline, outcome.guided):
        assert arm.elapsed_seconds > arm.compute_seconds > 0
        assert arm.overhead_included is False
        assert arm.human_interventions is None
        assert arm.cost_usd is None
        assert arm.token_usage is None
        payload = arm.to_dict()
        assert payload["measurement_availability"] == {
            "workflow_overhead": "UNAVAILABLE",
            "compute_seconds": "MEASURED",
            "human_interventions": "UNAVAILABLE",
            "cost_usd": "UNAVAILABLE",
            "token_usage": "UNAVAILABLE",
        }


def test_digest_sourced_workflow_measurements_make_arm_timing_end_to_end(
    tmp_path: Path,
) -> None:
    measurements = ArmWorkflowMeasurements(
        retrieval_seconds=0.4,
        planning_seconds=0.3,
        approval_seconds=0.2,
        preflight_seconds=0.1,
        agent_tool_seconds=0.5,
        human_interventions=1,
        cost_usd=None,
        token_usage=None,
        source_digest="e" * 64,
    )
    outcome = run_matched_experiment(
        confirmed_objective(objective_digest="d" * 64),
        config=ExperimentConfig(max_trials_per_arm=1, max_seconds_per_arm=5.0),
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path,
        arm_measurements={"baseline": measurements, "evidence_guided": measurements},
    )

    for arm in (outcome.baseline, outcome.guided):
        assert arm.overhead_included is True
        assert arm.external_overhead_seconds == pytest.approx(1.5)
        assert arm.elapsed_seconds >= 1.5
        assert arm.human_interventions == 1
        assert arm.cost_usd is None
        assert arm.token_usage is None
        assert arm.measurement_source_digest == "e" * 64
    assert outcome.acceleration["overhead_included"] is True
    assert outcome.acceleration["timing_scope"] == "end-to-end-arm-workflow"


def test_result_is_finalized_before_decision_and_post_decision_summary_has_provenance(
    tmp_path: Path,
) -> None:
    measurements = ArmWorkflowMeasurements(
        retrieval_seconds=0.01,
        planning_seconds=0.01,
        approval_seconds=0.01,
        preflight_seconds=0.01,
        agent_tool_seconds=0.01,
        human_interventions=1,
        cost_usd=None,
        token_usage=None,
        source_digest="e" * 64,
    )
    raw = run_matched_experiment(
        confirmed_objective(objective_digest="d" * 64),
        config=ExperimentConfig(max_trials_per_arm=4, max_seconds_per_arm=5.0),
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path,
        arm_measurements={"baseline": measurements, "evidence_guided": measurements},
    )
    authority = {
        "question_id": "question-1",
        "experiment_id": "experiment-guided",
        "objective_confirmation_digest": "d" * 64,
        "experiment_digest": "b" * 64,
        "approval_digest": "c" * 64,
        "task_card_digest": "a" * 64,
    }
    outcome = replace(
        raw,
        verified_authority=authority,
        approved_candidate_parameters={"approved": "exact"},
    )
    result = validate_record(outcome.as_experiment_result(
        question_id="question-1",
        experiment_id="experiment-guided",
        run_id="run-1",
        experiment_digest="b" * 64,
        approval_digest="c" * 64,
        task_card_digest="a" * 64,
    ))
    assert "decision_latency_seconds" not in result["metrics"]
    assert "decision_latency" not in result["parameters"]["execution_metadata"][
        "measurement_availability"
    ]
    invalid_result = json.loads(json.dumps(result))
    invalid_result.pop("record_digest")
    invalid_result["metrics"]["decision_latency_seconds"] = 7.25
    invalid_result["measurement_support"]["decision_latency_seconds"] = (
        next(iter(invalid_result["measurement_support"].values()))
    )
    with pytest.raises(RecordValidationError, match="precedes independent analysis"):
        validate_record(invalid_result)

    accepted = datetime.fromisoformat(outcome.completed_at.replace("Z", "+00:00"))
    decided = accepted + timedelta(seconds=7.25)
    timing = {
        "schema": "decision-timing-measurement/v1",
        "result_digest": result["record_digest"],
        "run_id": "run-1",
        "harness_acceptance_digest": "e" * 64,
        "result_accepted_at": accepted.isoformat(),
        "decision_completed_at": decided.isoformat(),
        "latency_seconds": 7.25,
    }
    decision = validate_record({
        "schema": "updated-decision/v1",
        "run_id": "run-1",
        "question_id": "question-1",
        "objective_confirmation_digest": "d" * 64,
        "hypothesis_id": "hypothesis-1",
        "experiment_id": "experiment-guided",
        "result_digest": result["record_digest"],
        "decision": "support",
        "rationale": "The result supports the hypothesis.",
        "interpreted_metrics": ["trials_to_threshold", "accuracy"],
        "supporting_evidence_ids": [],
        "remaining_uncertainty": ["One task."],
        "next_experiment": {
            "question": "Does the result replicate?",
            "rationale": "Reduce uncertainty.",
        },
        "human_review_required": True,
        "decision_timing": timing,
        "decision_timing_source_digest": hashlib.sha256(
            canonical_json(timing)
        ).hexdigest(),
    })
    summary = validate_record(outcome.as_acceleration_summary(
        acceleration_summary_id="acceleration-run-1",
        question_id="question-1",
        experiment_id="experiment-guided",
        result_digest=result["record_digest"],
        updated_decision=decision,
    ))
    assert result["primary_metric"] == "trials_to_threshold"
    assert result["metrics"]["trials_to_threshold"] == {
        "baseline": asdict(outcome.baseline.trials_to_threshold),
        "proposed": asdict(outcome.guided.trials_to_threshold),
    }
    assert result["metrics"]["accuracy"] == {
        "baseline": outcome.baseline.best_metric,
        "proposed": outcome.guided.best_metric,
    }
    assert result["metrics"]["cost_usd"] == {
        "baseline": None,
        "proposed": None,
    }
    assert summary["decision_latency_seconds"] == 7.25
    assert summary["decision_timing_source_digest"] == decision[
        "decision_timing_source_digest"
    ]
    assert summary["updated_decision_digest"] == decision["record_digest"]
    assert summary["result_digest"] == result["record_digest"]
    assert validate_record(result) == result
    assert validate_record(summary) == summary

def test_failed_trials_count_and_censored_endpoints_are_not_inflated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_every_trial(*args: object, **kwargs: object) -> float:
        raise RuntimeError("deliberate evaluator failure")

    monkeypatch.setattr(experiment, "_evaluate_candidate", fail_every_trial)
    outcome = run_matched_experiment(
        confirmed_objective(objective_digest="d" * 64),
        config=ExperimentConfig(max_trials_per_arm=2, max_seconds_per_arm=5.0),
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path,
    )

    for arm in (outcome.baseline, outcome.guided):
        assert arm.attempted_trials == 2
        assert arm.failed_trials == 2
        assert [trial.status for trial in arm.trials] == ["ERROR", "ERROR"]
        assert arm.trials_to_threshold == Endpoint(
            value=None,
            censored=True,
            lower_bound_exclusive=2,
            censoring_reason="trial-budget-exhausted",
        )
    assert outcome.acceleration["status"] == "NOT_ESTIMABLE"
    assert outcome.acceleration["trial_speedup"] is None
    assert outcome.acceleration["positive_acceleration_claim"] is False
    assert outcome.to_dict()["execution_status"] == "ERROR"

    journal_ready = replace(
        outcome,
        verified_authority={
            "question_id": "question-1",
            "experiment_id": "experiment-guided",
            "objective_confirmation_digest": "d" * 64,
            "experiment_digest": "b" * 64,
            "approval_digest": "c" * 64,
            "task_card_digest": "a" * 64,
        },
        approved_candidate_parameters={"approved": "exact"},
    )
    result = validate_record(journal_ready.as_experiment_result(
        question_id="question-1",
        experiment_id="experiment-guided",
        run_id="run-all-errors",
        experiment_digest="b" * 64,
        approval_digest="c" * 64,
        task_card_digest="a" * 64,
    ))
    accepted = datetime.fromisoformat(
        journal_ready.completed_at.replace("Z", "+00:00")
    )
    timing = {
        "schema": "decision-timing-measurement/v1",
        "result_digest": result["record_digest"],
        "run_id": "run-all-errors",
        "harness_acceptance_digest": "e" * 64,
        "result_accepted_at": accepted.isoformat(),
        "decision_completed_at": (accepted + timedelta(seconds=1)).isoformat(),
        "latency_seconds": 1.0,
    }
    decision = validate_record({
        "schema": "updated-decision/v1",
        "run_id": "run-all-errors",
        "question_id": "question-1",
        "objective_confirmation_digest": "d" * 64,
        "hypothesis_id": "hypothesis-1",
        "experiment_id": "experiment-guided",
        "result_digest": result["record_digest"],
        "decision": "inconclusive",
        "rationale": "No successful trial produced an interpretable metric.",
        "interpreted_metrics": ["trials_to_threshold", "accuracy"],
        "supporting_evidence_ids": [],
        "remaining_uncertainty": ["All candidate evaluations failed."],
        "next_experiment": {
            "question": "Can the evaluator failure be reproduced?",
            "rationale": "Resolve execution uncertainty before inference.",
        },
        "human_review_required": True,
        "decision_timing": timing,
        "decision_timing_source_digest": hashlib.sha256(
            canonical_json(timing)
        ).hexdigest(),
    })
    summary = validate_record(journal_ready.as_acceleration_summary(
        acceleration_summary_id="acceleration-all-errors",
        question_id="question-1",
        experiment_id="experiment-guided",
        result_digest=result["record_digest"],
        updated_decision=decision,
    ))
    assert result["status"] == "ERROR"
    assert summary["outcome"] == "NOT_ESTIMABLE"
    assert summary["overall_discovery_speed_claim"] is False
    assert summary["arms"]["baseline"]["best_metric"] is None
    assert summary["quality_non_inferiority"] == {
        "margin": 0.02,
        "higher_is_better": True,
        "estimable": False,
        "passed": False,
    }
    assert "quality_non_inferiority_not_estimable" in summary["claim_blockers"]


def test_wall_time_cap_terminates_evaluator_without_background_activity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("hard evaluator deadline regression requires POSIX fork")
    late_marker = tmp_path / "evaluator-continued-after-timeout"

    def slow_evaluator(*args: object, **kwargs: object) -> float:
        deadline = time.perf_counter() + 0.20
        accumulator = 0
        while time.perf_counter() < deadline:
            accumulator += 1
        late_marker.write_text("leaked", encoding="utf-8")
        return 0.99 if accumulator else 0.0

    monkeypatch.setattr(experiment, "_evaluate_candidate", slow_evaluator)
    children_before = {child.pid for child in multiprocessing.active_children()}
    started = time.perf_counter()
    outcome = run_matched_experiment(
        confirmed_objective(objective_digest="d" * 64),
        config=ExperimentConfig(max_trials_per_arm=4, max_seconds_per_arm=0.03),
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path / "artifacts",
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.30
    for arm in (outcome.baseline, outcome.guided):
        assert arm.attempted_trials == 1
        assert arm.trials[0].status == "TIMEOUT"
        assert arm.trials[0].metric is None
        assert arm.trials[0].compute_seconds is None
        assert arm.compute_seconds is None
        assert arm.to_dict()["measurement_availability"]["compute_seconds"] == (
            "UNAVAILABLE"
        )
        assert arm.stop_reason == "wall-time-budget-exhausted"
        assert arm.trials_to_threshold.lower_bound_exclusive == 1
        assert arm.trials_to_threshold.censoring_reason == "wall-time-budget-exhausted"
    time.sleep(0.25)
    assert not late_marker.exists()
    assert {
        child.pid for child in multiprocessing.active_children()
    } <= children_before
    assert "compute_unavailable" in outcome.acceleration["claim_blockers"]
    assert outcome.acceleration["overall_discovery_speed_claim"] is False

    journal_ready = replace(
        outcome,
        verified_authority={
            "question_id": "question-1",
            "experiment_id": "experiment-guided",
            "objective_confirmation_digest": "d" * 64,
            "experiment_digest": "b" * 64,
            "approval_digest": "c" * 64,
            "task_card_digest": "a" * 64,
        },
        approved_candidate_parameters={"approved": "exact"},
    )
    result = validate_record(journal_ready.as_experiment_result(
        question_id="question-1",
        experiment_id="experiment-guided",
        run_id="run-timeout",
        experiment_digest="b" * 64,
        approval_digest="c" * 64,
        task_card_digest="a" * 64,
    ))
    assert result["metrics"]["compute_seconds"] == {
        "baseline": None,
        "proposed": None,
    }
    assert result["parameters"]["execution_metadata"][
        "measurement_availability"
    ]["baseline"]["compute_seconds"] == "UNAVAILABLE"


def test_fatal_evaluator_exit_is_counted_with_unavailable_compute_and_finalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fatal evaluator regression requires POSIX fork")

    def fatal_evaluator(*args: object, **kwargs: object) -> float:
        os._exit(23)

    monkeypatch.setattr(experiment, "_evaluate_candidate", fatal_evaluator)
    outcome = run_matched_experiment(
        confirmed_objective(objective_digest="d" * 64),
        config=ExperimentConfig(max_trials_per_arm=1, max_seconds_per_arm=1.0),
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path,
    )
    for arm in (outcome.baseline, outcome.guided):
        assert arm.attempted_trials == 1
        assert arm.trials[0].status == "ERROR"
        assert "exitcode=23" in (arm.trials[0].error or "")
        assert arm.trials[0].compute_seconds is None
        assert arm.compute_seconds is None
        assert arm.to_dict()["measurement_availability"]["compute_seconds"] == (
            "UNAVAILABLE"
        )
    assert outcome.to_dict()["execution_status"] == "ERROR"
    assert outcome.acceleration["status"] == "NOT_ESTIMABLE"
    assert "compute_unavailable" in outcome.acceleration["claim_blockers"]

    ready = replace(
        outcome,
        verified_authority={
            "question_id": "question-1",
            "experiment_id": "experiment-guided",
            "objective_confirmation_digest": "d" * 64,
            "experiment_digest": "b" * 64,
            "approval_digest": "c" * 64,
            "task_card_digest": "a" * 64,
        },
        approved_candidate_parameters={"approved": "exact"},
    )
    result = validate_record(ready.as_experiment_result(
        question_id="question-1",
        experiment_id="experiment-guided",
        run_id="run-fatal-exit",
        experiment_digest="b" * 64,
        approval_digest="c" * 64,
        task_card_digest="a" * 64,
    ))
    mislabeled = json.loads(json.dumps(result))
    mislabeled.pop("record_digest")
    mislabeled["parameters"]["execution_metadata"]["measurement_availability"][
        "baseline"
    ]["compute_seconds"] = "MEASURED"
    mislabeled["metrics"]["baseline"]["measurement_availability"][
        "compute_seconds"
    ] = "MEASURED"
    with pytest.raises(RecordValidationError, match="compute availability"):
        validate_record(mislabeled)
    accepted = datetime.fromisoformat(ready.completed_at.replace("Z", "+00:00"))
    timing = {
        "schema": "decision-timing-measurement/v1",
        "result_digest": result["record_digest"],
        "run_id": "run-fatal-exit",
        "harness_acceptance_digest": "e" * 64,
        "result_accepted_at": accepted.isoformat(),
        "decision_completed_at": (accepted + timedelta(seconds=1)).isoformat(),
        "latency_seconds": 1.0,
    }
    decision = validate_record({
        "schema": "updated-decision/v1",
        "run_id": "run-fatal-exit",
        "question_id": "question-1",
        "objective_confirmation_digest": "d" * 64,
        "hypothesis_id": "hypothesis-1",
        "experiment_id": "experiment-guided",
        "result_digest": result["record_digest"],
        "decision": "inconclusive",
        "rationale": "The evaluator exited before returning a measurement.",
        "interpreted_metrics": ["trials_to_threshold", "accuracy"],
        "supporting_evidence_ids": [],
        "remaining_uncertainty": ["Evaluator integrity must be restored."],
        "next_experiment": {
            "question": "Can the fatal evaluator exit be reproduced?",
            "rationale": "Repair execution before scientific inference.",
        },
        "human_review_required": True,
        "decision_timing": timing,
        "decision_timing_source_digest": hashlib.sha256(
            canonical_json(timing)
        ).hexdigest(),
    })
    summary = validate_record(ready.as_acceleration_summary(
        acceleration_summary_id="acceleration-fatal-exit",
        question_id="question-1",
        experiment_id="experiment-guided",
        result_digest=result["record_digest"],
        updated_decision=decision,
    ))
    assert summary["outcome"] == "NOT_ESTIMABLE"
    assert summary["arms"]["baseline"]["compute_seconds"] is None
    assert summary["overall_discovery_speed_claim"] is False


def test_authorized_live_path_preserves_exact_authority_and_dataset_linkage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_card = tmp_path / "task-card.json"
    task_card.write_text('{"task":"authorized"}\n', encoding="utf-8")
    task_digest = hashlib.sha256(task_card.read_bytes()).hexdigest()
    scope = replace(
        confirmed_objective().execution_scope, network_access="read-only-openml"
    )
    objective = confirmed_objective(
        objective_digest="d" * 64,
        scope=scope,
    )
    search_candidates = [
        {
            "candidate_id": candidate_id,
            "feature_indices": feature_indices,
            "neighbors": neighbors,
            "evidence_rationale": f"Reviewed rationale for {candidate_id}.",
            "evidence_references": [f"evidence-{candidate_id}"],
        }
        for candidate_id, feature_indices, neighbors in (
            ("sepal-k15", [0, 1], 15),
            ("sepal-k7", [0, 1], 7),
            ("all-k7", [0, 1, 2, 3], 7),
            ("petal-k5", [2, 3], 5),
        )
    ]
    parameters = {
        "search_candidates": search_candidates,
        "baseline_order": ["sepal-k15", "sepal-k7", "all-k7", "petal-k5"],
        "evidence_guided_order": ["petal-k5", "all-k7", "sepal-k7", "sepal-k15"],
        "split_seed": 1729,
        "threshold": 0.9,
        "max_trials_per_arm": 4,
        "max_seconds_per_arm": 30.0,
        "quality_noninferiority_margin": 0.02,
    }

    def candidate(identifier: str) -> dict:
        return {
            "experiment_id": identifier,
            "method": "Matched classifier search.",
            "baseline": "Fixed ordering.",
            "controls": ["same split and candidate set"],
            "inputs": ["synthetic fixture"],
            "parameters": parameters,
            "random_seeds": [1729],
            "metrics": ["trials_to_threshold", "accuracy"],
            "success_threshold": "accuracy >= 0.9",
            "expected_learning": "Whether ordering reduces trials.",
            "estimated_runtime_minutes": 1.0,
            "estimated_cost_usd": 0.0,
            "risk_level": "low",
        }

    portfolio = validate_record(
        {
            "schema": "experiment-candidates/v1",
            "experiment_candidates_id": "candidate-portfolio-1",
            "question_id": "question-1",
            "objective_confirmation_digest": "d" * 64,
            "hypothesis_id": "hypothesis-1",
            "primary_metric": "trials_to_threshold",
            "dataset_identity": {
                "identifier": "synthetic-proxy-openml-task-59-v1",
                "version": "1",
                "digest": FIXTURE_DIGEST,
            },
            "resource_bounds": {
                "max_trials": 8,
                "max_runtime_minutes": 5.0,
                "max_cost_usd": 0.0,
                "compute": "local CPU",
                "network_access": "read-only-openml",
                "mutation_permissions": ["artifact directory only"],
            },
            "risk_tolerance": {
                "level": "low",
                "allowed_risks": ["inconclusive fixture result"],
                "prohibited_actions": ["external mutation"],
                "privacy_constraints": ["verified non-personal data"],
                "acceptable_failure_modes": ["trial failure"],
            },
            "candidates": [
                candidate("experiment-guided"),
                candidate("experiment-alternative"),
            ],
            "selected_experiment_id": "experiment-guided",
            "selection_rationale": "Evidence references predeclare the guided order.",
            "rejected_candidate_rationales": {
                "experiment-alternative": "Lower expected learning."
            },
        }
    )
    selected_digest = experiment_digest(portfolio)
    binding = {
        "experiment_id": "experiment-guided",
        "objective_confirmation_digest": "d" * 64,
        "experiment_digest": selected_digest,
        "approval_digest": "c" * 64,
        "task_card_digest": task_digest,
        "task_card_path": str(task_card),
        "status": "LAUNCHED",
    }

    class FakeJournal:
        def __init__(self, path: Path) -> None:
            self.path = path

        def experiment_status(self, experiment_id: str) -> dict:
            assert experiment_id == "experiment-guided"
            return binding

        def get(self, digest: str) -> dict | None:
            if digest == "c" * 64:
                return {
                    "schema": "human-approval/v1",
                    "approved": True,
                    "experiment_id": "experiment-guided",
                    "experiment_digest": selected_digest,
                    "objective_confirmation_digest": "d" * 64,
                }
            if digest == "d" * 64:
                return {
                    "schema": "objective-confirmation/v1",
                    "question_id": "question-1",
                    "primary_metric": "trials_to_threshold",
                    "dataset": {
                        "identifier": "synthetic-proxy-openml-task-59-v1",
                        "version": "1",
                        "digest": FIXTURE_DIGEST,
                        "source": "file:///fixture.csv",
                    },
                    "risk_tolerance": {"level": "low"},
                    "execution_scope": {
                        "max_trials": 8,
                        "max_runtime_minutes": 5.0,
                        "max_cost_usd": 0.0,
                        "compute": "local CPU",
                        "network_access": "read-only-openml",
                        "mutation_permissions": ["artifact directory only"],
                    },
                }
            return None

        def reconstruct_chain(self, question_id: str) -> dict:
            assert question_id == "question-1"
            return {
                "records": [
                    {
                        "schema": "feasibility-check/v1",
                        "objective_confirmation_digest": "d" * 64,
                        "overall_status": "PASS",
                        "checks": {
                            "license": {
                                "status": "PASS",
                                "evidence": "License attestation reviewed.",
                            },
                            "privacy": {
                                "status": "PASS",
                                "evidence": "Privacy attestation reviewed.",
                            },
                        },
                    },
                    portfolio,
                ]
            }

    fixture_data = experiment._load_dataset(
        fixture_dir=FIXTURE_DIR,
        live=False,
        network_timeout_seconds=20.0,
    )
    monkeypatch.setattr(experiment, "ResearchJournal", FakeJournal)
    monkeypatch.setattr(experiment, "_load_dataset", lambda **kwargs: fixture_data)
    monkeypatch.delenv("AI_RESEARCHER_ENABLE_EXECUTION", raising=False)
    report = preflight(
        objective,
        live=True,
        journal_path=tmp_path / "journal.sqlite3",
    )
    assert report.checks["objective_confirmation"] == "PASS"
    assert report.dataset["digest"] == FIXTURE_DIGEST
    monkeypatch.setenv("AI_RESEARCHER_ENABLE_EXECUTION", "1")
    authorization = ExecutionAuthorization(
        journal_path=tmp_path / "journal.sqlite3",
        experiment_id="experiment-guided",
        objective_confirmation_digest="d" * 64,
        experiment_digest=selected_digest,
        approval_digest="c" * 64,
        task_card_digest=task_digest,
    )
    outcome = run_matched_experiment(
        objective,
        artifact_dir=tmp_path / "artifacts",
        live=True,
        authorization=authorization,
    )
    record = outcome.as_experiment_result(
        question_id="question-1",
        experiment_id="experiment-guided",
        run_id="authorized-run-1",
        experiment_digest=selected_digest,
        approval_digest="c" * 64,
        task_card_digest=task_digest,
    )
    assert record["dataset_identity"] == {
        "identifier": "synthetic-proxy-openml-task-59-v1",
        "version": "1",
        "digest": FIXTURE_DIGEST,
    }
    assert record["status"] == "PASS"
    assert record["metrics"]["trials_to_threshold"]["proposed"] == asdict(
        outcome.guided.trials_to_threshold
    )
    assert record["metrics"]["accuracy"] == {
        "baseline": outcome.baseline.best_metric,
        "proposed": outcome.guided.best_metric,
    }
    assert record["metrics"]["primary_metric_metadata"] == {
        "name": "trials_to_threshold",
        "proposed_value": outcome.guided.trials_to_threshold.value,
        "baseline_value": outcome.baseline.trials_to_threshold.value,
        "higher_is_better": False,
    }
    assert record["parameters"]["approved_candidate_parameters"] == parameters
    assert (
        record["parameters"]["observed_preregistration"]
        == outcome.preregistration
    )
    normalized_record = validate_record(record)
    assert normalized_record["run_id"] == "authorized-run-1"
    decision = decision_for_result(
        normalized_record,
        objective_digest="d" * 64,
        latency_seconds=1.5,
    )
    summary = outcome.as_acceleration_summary(
        acceleration_summary_id="acceleration-authorized-run-1",
        question_id="question-1",
        experiment_id="experiment-guided",
        result_digest=normalized_record["record_digest"],
        updated_decision=decision,
    )
    assert summary["overhead_included"] is False
    assert summary["overall_discovery_speed_claim"] is False
    assert "overhead_missing" in summary["claim_blockers"]
    assert validate_record(summary)["outcome"] in {
        "TRIAL_EFFICIENCY_ONLY",
        "NO_IMPROVEMENT",
    }

    with pytest.raises(ExperimentValidationError, match="caller config overrides"):
        run_matched_experiment(
            objective,
            config=ExperimentConfig(threshold=0.8),
            artifact_dir=tmp_path / "overridden-artifacts",
            live=True,
            authorization=authorization,
        )


def _arm(
    name: str,
    *,
    trials: int | None,
    budget: int = 4,
    best_metric: float = 0.95,
    elapsed_to_threshold: float | None = 1.0,
) -> ArmResult:
    endpoint = Endpoint(
        value=trials,
        censored=trials is None,
        lower_bound_exclusive=budget if trials is None else None,
        censoring_reason="trial-budget-exhausted" if trials is None else None,
    )
    time_endpoint = Endpoint(
        value=elapsed_to_threshold,
        censored=elapsed_to_threshold is None,
        lower_bound_exclusive=1.0 if elapsed_to_threshold is None else None,
        censoring_reason="trial-budget-exhausted" if elapsed_to_threshold is None else None,
    )
    return ArmResult(
        arm=name,
        policy="test",
        trials=(),
        attempted_trials=budget,
        failed_trials=0,
        best_metric=best_metric,
        trials_to_threshold=endpoint,
        seconds_to_threshold=time_endpoint,
        elapsed_seconds=elapsed_to_threshold or 1.0,
        compute_seconds=0.25,
        compute_seconds_to_threshold=(0.25 if trials is not None else None),
        external_overhead_seconds=0.0,
        overhead_included=False,
        human_interventions=None,
        cost_usd=None,
        token_usage=None,
        measurement_source_digest=None,
        stop_reason="threshold-reached" if trials else "trial-budget-exhausted",
        control_digest="same-control",
        candidate_set_digest="same-candidates",
    )


def test_acceleration_uses_censoring_and_no_inflation_rules() -> None:
    lower_bound = calculate_acceleration(
        _arm("baseline", trials=None, budget=4, elapsed_to_threshold=None),
        _arm("evidence_guided", trials=2),
        quality_noninferiority_margin=0.02,
        threshold_was_preregistered=True,
    )
    assert lower_bound["status"] == "BASELINE_CENSORED_GUIDED_REACHED"
    assert lower_bound["trial_speedup"] is None
    assert lower_bound["trial_speedup_lower_bound_exclusive"] == 2.0
    assert lower_bound["positive_acceleration_claim"] is False

    trial_only = calculate_acceleration(
        _arm("baseline", trials=4, elapsed_to_threshold=1.0),
        _arm("evidence_guided", trials=2, elapsed_to_threshold=2.0),
        quality_noninferiority_margin=0.02,
        threshold_was_preregistered=True,
    )
    assert trial_only["trial_speedup"] == 2.0
    assert trial_only["time_speedup"] == 0.5
    assert trial_only["claim"] == "TRIAL_EFFICIENCY_ONLY"
    assert trial_only["positive_acceleration_claim"] is False

    post_hoc = calculate_acceleration(
        _arm("baseline", trials=4, elapsed_to_threshold=4.0),
        _arm("evidence_guided", trials=2, elapsed_to_threshold=1.0),
        quality_noninferiority_margin=0.02,
        threshold_was_preregistered=False,
    )
    assert post_hoc["trial_speedup"] == 2.0
    assert post_hoc["positive_acceleration_claim"] is False
    assert "threshold_not_preregistered" in post_hoc["validity_failures"]


def test_resource_caps_are_hard_failures() -> None:
    with pytest.raises(ExperimentValidationError, match="hard cap"):
        ExperimentConfig(max_trials_per_arm=experiment.MAX_TRIALS_PER_ARM + 1)
    with pytest.raises(ExperimentValidationError, match="hard cap"):
        ExperimentConfig(max_seconds_per_arm=experiment.MAX_SECONDS_PER_ARM + 1)


def test_wall_time_cap_stops_each_arm_and_counts_timed_out_attempt(
    tmp_path: Path,
) -> None:
    ticks = iter((0.0, 0.0, 2.0, 2.0, 2.0, 2.0, 4.0, 4.0))
    outcome = run_matched_experiment(
        confirmed_objective(),
        config=ExperimentConfig(max_trials_per_arm=4, max_seconds_per_arm=1.0),
        fixture_dir=FIXTURE_DIR,
        artifact_dir=tmp_path,
        monotonic=lambda: next(ticks),
    )

    for arm in (outcome.baseline, outcome.guided):
        assert arm.attempted_trials == 1
        assert arm.failed_trials == 1
        assert arm.trials[0].status == "TIMEOUT"
        assert arm.stop_reason == "wall-time-budget-exhausted"
