"""Narrow authority boundary between Omnigent and the execution harness."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from memory_harness import contracts
from orchestrator_harness.bootstrap import _validate_provider_launch_config
from orchestrator_harness.core import content_hash
from orchestrator_harness.records import read_record
from orchestrator_harness.task_cards import validate_task_card

from .harness_evidence import (
    HarnessEvidenceError,
    acceptance_reference,
    active_harness_run,
    read_verified_terminal_evidence,
    verified_terminal_evidence,
)
from .journal import JournalConflictError, ResearchJournal
from .records import experiment_digest, selected_experiment, validate_record


class HarnessIntegrationError(RuntimeError):
    """The requested harness transition is unauthorized or inconsistent."""


@dataclass(frozen=True)
class PreparedExperiment:
    experiment_id: str
    objective_confirmation_digest: str
    experiment_digest: str
    approval_digest: str
    task_card_digest: str
    lane_id: str
    task_card_path: Path
    task_card: dict[str, Any]


class HarnessAdapter:
    """Translate one complete, human-authorized science chain into one task."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        journal_path: str | Path | None = None,
        artifact_root: str | Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.harness_root = self.repo_root / "harness"
        if not (self.harness_root / "orchestrator_harness").is_dir():
            raise HarnessIntegrationError("integrated harness package is missing")
        self.journal = ResearchJournal(
            journal_path or self.repo_root / "runtime" / "research-journal.sqlite3"
        )
        self.artifact_root = Path(
            artifact_root or self.repo_root / "artifacts" / "harness-tasks"
        ).resolve()

    def approval_request(
        self,
        experiment_candidates: Mapping[str, Any],
        safety_review: Mapping[str, Any],
        *,
        objective_confirmation_digest: str,
    ) -> dict[str, Any]:
        """Return an approval packet only for an already journaled valid chain."""

        portfolio, review, objective, _ = self._reviewed_context(
            experiment_candidates,
            safety_review,
            objective_confirmation_digest=objective_confirmation_digest,
        )
        selected = selected_experiment(portfolio)
        return {
            "question_id": objective["question_id"],
            "experiment_id": selected["experiment_id"],
            "objective_confirmation_digest": objective["record_digest"],
            "experiment_digest": experiment_digest(portfolio),
            "approval_question": review["approval_question"],
            "required_controls": review["required_controls"],
            "prohibited_actions": review["prohibited_actions"],
            "confirmed_scope": objective["execution_scope"],
        }

    def prepare(
        self,
        experiment_candidates: Mapping[str, Any],
        safety_review: Mapping[str, Any],
        *,
        objective_confirmation_digest: str,
        approval_digest: str,
    ) -> PreparedExperiment:
        """Stage a separately journaled human approval; never create one here."""

        portfolio, review, objective, _ = self._reviewed_context(
            experiment_candidates,
            safety_review,
            objective_confirmation_digest=objective_confirmation_digest,
        )
        stored_approval = self.journal.get(approval_digest)
        if stored_approval is None:
            raise HarnessIntegrationError("human approval digest is not journaled")
        authorized = validate_record(stored_approval, "human-approval/v1")
        if authorized["record_digest"] != approval_digest:
            raise HarnessIntegrationError("human approval digest does not match its record")
        self._verify_human_authority_metadata(
            authorized, identity_field="approved_by"
        )
        selected = selected_experiment(portfolio)
        selected_digest = experiment_digest(portfolio)
        experiment_id = selected["experiment_id"]
        authority = objective["record_digest"]

        if authorized["objective_confirmation_digest"] != authority:
            raise HarnessIntegrationError("human approval does not bind the objective authority")
        if authorized["experiment_id"] != experiment_id:
            raise HarnessIntegrationError("human approval targets another experiment")
        if authorized["experiment_digest"] != selected_digest:
            raise HarnessIntegrationError("human approval does not bind the exact specification")

        chain = self.journal.reconstruct_chain(objective["question_id"])
        if authorized["record_digest"] not in {
            record["record_digest"] for record in chain["records"]
        }:
            raise HarnessIntegrationError("human approval is outside the reviewed objective chain")

        lane_id = _lane_id(experiment_id)
        task_card = self._task_card(portfolio, selected, review, authorized, objective)
        validate_task_card(task_card, Path("generated-research-task.json"))
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        task_path = self.artifact_root / f"{lane_id}.json"
        _atomic_json(task_path, task_card)
        task_digest = hashlib.sha256(task_path.read_bytes()).hexdigest()
        try:
            self.journal.bind_experiment(
                experiment_id=experiment_id,
                experiment_digest=selected_digest,
                approval_digest=authorized["record_digest"],
                objective_confirmation_digest=authority,
                task_card_digest=task_digest,
                task_card_path=task_path,
                lane_id=lane_id,
                status="STAGED",
            )
        except JournalConflictError as exc:
            raise HarnessIntegrationError(f"experiment could not be staged: {exc}") from exc
        return PreparedExperiment(
            experiment_id=experiment_id,
            objective_confirmation_digest=authority,
            experiment_digest=selected_digest,
            approval_digest=authorized["record_digest"],
            task_card_digest=task_digest,
            lane_id=lane_id,
            task_card_path=task_path,
            task_card=task_card,
        )

    def launch(
        self,
        prepared: PreparedExperiment,
        *,
        confirmation: str,
        provider: str,
        model: str,
        provider_options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Launch only a still-current staged snapshot with two exact gates."""

        if os.environ.get("AI_RESEARCHER_ENABLE_EXECUTION") != "1":
            raise HarnessIntegrationError(
                "execution is disabled; set AI_RESEARCHER_ENABLE_EXECUTION=1 explicitly"
            )
        if confirmation != prepared.approval_digest:
            raise HarnessIntegrationError("launch confirmation does not match the approval digest")
        binding = self._matching_binding(prepared, required_status="STAGED")
        self._ensure_current_objective(prepared.objective_confirmation_digest)
        options = self._provider_options(provider, model, provider_options or {})

        bootstrap_arguments = [
            "lane", "bootstrap", "--lane-id", prepared.lane_id,
            "--provider", provider, "--model", model,
        ]
        for key, value in sorted(options.items()):
            bootstrap_arguments.extend(("--provider-option", f"{key}={value}"))
        bootstrap_arguments.extend(("--task-card", str(prepared.task_card_path)))
        bootstrap = self._operator(*bootstrap_arguments)
        try:
            _epoch_id, authoritative_lane = active_harness_run(
                self.harness_root, lane_id=prepared.lane_id
            )
        except HarnessEvidenceError as exc:
            raise HarnessIntegrationError(str(exc)) from exc
        run_id = authoritative_lane.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise HarnessIntegrationError(
                "bootstrapped Harness lane does not have a run identity"
            )
        try:
            self.journal.bind_experiment(
                experiment_id=prepared.experiment_id,
                experiment_digest=prepared.experiment_digest,
                approval_digest=prepared.approval_digest,
                objective_confirmation_digest=prepared.objective_confirmation_digest,
                task_card_digest=prepared.task_card_digest,
                task_card_path=prepared.task_card_path,
                lane_id=binding["lane_id"],
                run_id=run_id,
                status="LAUNCHING",
            )
        except JournalConflictError as exc:
            raise HarnessIntegrationError(
                "launch authorization could not be persisted; worker was not launched: "
                f"{exc}"
            ) from exc

        launching_binding = self.journal.experiment_status(prepared.experiment_id)
        assert launching_binding is not None
        try:
            launch = self._operator("lane", "launch", "--lane-id", prepared.lane_id)
            try:
                _epoch_id, launched_lane = active_harness_run(
                    self.harness_root, lane_id=prepared.lane_id
                )
            except HarnessEvidenceError as exc:
                raise HarnessIntegrationError(str(exc)) from exc
            if launched_lane.get("run_id") != run_id:
                raise HarnessIntegrationError("Harness run identity changed during launch")
            self.journal.bind_experiment(
                experiment_id=prepared.experiment_id,
                experiment_digest=prepared.experiment_digest,
                approval_digest=prepared.approval_digest,
                objective_confirmation_digest=prepared.objective_confirmation_digest,
                task_card_digest=prepared.task_card_digest,
                task_card_path=prepared.task_card_path,
                lane_id=binding["lane_id"],
                run_id=run_id,
                status="LAUNCHED",
            )
        except (HarnessIntegrationError, JournalConflictError) as exc:
            cleanup_error = self._abort_launch_handshake(launching_binding)
            if cleanup_error is None:
                raise HarnessIntegrationError(
                    "launch handshake failed; the exact run was force-stopped and its "
                    f"authority was cancelled: {exc}"
                ) from exc
            raise HarnessIntegrationError(
                "launch handshake failed and exact-run cleanup could not be proven; "
                "the durable binding remains LAUNCHING for operator recovery: "
                f"{exc}; cleanup: {cleanup_error}"
            ) from exc
        return {"bootstrap": bootstrap, "launch": launch, "run_id": run_id}

    def status(self, experiment_id: str) -> dict[str, Any] | None:
        return self.journal.experiment_status(experiment_id)

    def harness_status(self, experiment_id: str) -> dict[str, Any]:
        """Return journal authority plus the current authoritative Harness lane."""

        binding = self._launched_binding(experiment_id)
        try:
            epoch_id, lane = active_harness_run(
                self.harness_root, lane_id=binding["lane_id"]
            )
        except HarnessEvidenceError as exc:
            raise HarnessIntegrationError(str(exc)) from exc
        if lane.get("run_id") != binding["run_id"]:
            raise HarnessIntegrationError("Harness status belongs to a different run")
        return {"binding": binding, "epoch_id": epoch_id, "lane": lane}

    def wait_for_review(self, experiment_id: str, *, timeout: str) -> dict[str, Any]:
        """Wait read-only for the exact lane's completion-review boundary."""

        binding = self._launched_binding(experiment_id)
        if not isinstance(timeout, str) or not timeout.strip():
            raise HarnessIntegrationError("wait timeout must be explicit")
        return self._operator(
            "watch", "--until-review-for", binding["lane_id"],
            "--timeout", timeout.strip(),
        )

    def review_completion(
        self,
        experiment_id: str,
        *,
        confirmation: str,
        review_outcome: str,
        approval: str,
        review_summary: str,
        evidence: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Record an explicit ROOT review; never infer or auto-accept a result."""

        binding = self._launched_binding(experiment_id)
        self._require_execution_enabled()
        self._confirm_binding(binding, confirmation)
        if review_outcome not in {"PASS", "FAIL", "BLOCKED", "UNKNOWN"}:
            raise HarnessIntegrationError("unknown completion review outcome")
        if approval not in {"ACCEPTED", "REJECTED"}:
            raise HarnessIntegrationError("unknown completion approval decision")
        if not isinstance(review_summary, str) or not review_summary.strip():
            raise HarnessIntegrationError("completion review summary must be non-empty")
        if review_outcome == "UNKNOWN":
            raise HarnessIntegrationError(
                "UNKNOWN completion reviews cannot produce a scientific decision; "
                "repeat the independent review"
            )
        if approval == "ACCEPTED" and review_outcome != "PASS":
            raise HarnessIntegrationError(
                "scientific result acceptance requires a PASS completion review"
            )
        arguments = [
            "lane", "completion-review", "--lane-id", binding["lane_id"],
            "--review-outcome", review_outcome, "--approval", approval,
            "--review-summary", review_summary.strip(),
        ]
        for item in evidence:
            if not isinstance(item, str) or not item.strip():
                raise HarnessIntegrationError("completion evidence entries must be non-empty")
            arguments.extend(("--evidence", item.strip()))
        return self._operator(*arguments)

    def terminal_evidence(self, experiment_id: str) -> dict[str, Any]:
        """Retrieve accepted terminal evidence from Harness-owned storage."""

        binding = self._launched_binding(experiment_id, allow_terminal=True)
        try:
            return read_verified_terminal_evidence(
                self.harness_root,
                lane_id=binding["lane_id"],
                run_id=binding["run_id"],
                authority=binding,
            )
        except HarnessEvidenceError as exc:
            raise HarnessIntegrationError(str(exc)) from exc

    def build_result_envelope(
        self,
        experiment_id: str,
        result: Mapping[str, Any],
        *,
        summary: str,
        evidence: tuple[str, ...],
        completed_at: str,
    ) -> dict[str, Any]:
        """Build the exact Harness ``RESULT.json`` payload for a matched outcome.

        This pure conversion does not write into a worker's worktree.  The
        launched worker remains responsible for writing these exact bytes so
        Harness can independently hash and review them.
        """

        binding = self._launched_binding(experiment_id)
        normalized = validate_record(result, "experiment-result/v1")
        self._verify_result_authority(binding, normalized)
        if not isinstance(summary, str) or not summary.strip():
            raise HarnessIntegrationError("Harness result summary must be non-empty")
        if not isinstance(completed_at, str) or not completed_at.strip():
            raise HarnessIntegrationError("Harness result completed_at must be non-empty")
        if not isinstance(evidence, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in evidence
        ):
            raise HarnessIntegrationError("Harness result evidence must be a tuple of strings")
        outcome = {
            "PASS": "PASS",
            "FAIL": "FAIL",
            "ERROR": "BLOCKED",
            "CANCELLED": "BLOCKED",
        }[normalized["status"]]
        envelope: dict[str, Any] = {
            "schema": "result/v1",
            "lane_id": binding["lane_id"],
            "run_id": binding["run_id"],
            "outcome": outcome,
            "summary": summary.strip(),
            "evidence": list(evidence),
            "completed_at": completed_at.strip(),
            "scientific_result": normalized,
        }
        envelope["content_hash"] = content_hash(envelope)
        return envelope

    def ingest_harness_result(
        self, experiment_id: str, *, artifact_base_dir: str | Path
    ) -> dict[str, Any]:
        """Ingest the exact scientific result accepted by Harness ROOT."""

        terminal = self.terminal_evidence(experiment_id)
        harness_result = terminal.get("result")
        scientific_result = (
            harness_result.get("scientific_result")
            if isinstance(harness_result, Mapping)
            else None
        )
        if not isinstance(scientific_result, Mapping):
            raise HarnessIntegrationError(
                "Harness-reviewed RESULT.json omits scientific_result"
            )
        return self.record_result(
            scientific_result,
            terminal_evidence=terminal,
            artifact_base_dir=artifact_base_dir,
        )

    def force_stop(
        self, experiment_id: str, *, confirmation: str
    ) -> dict[str, Any]:
        """Hard-stop and finalize one exact run with durable cleanup evidence."""

        binding = self._cleanup_binding(experiment_id)
        self._require_execution_enabled()
        self._confirm_binding(binding, confirmation)
        response = self._operator("lane", "force-stop", "--lane-id", binding["lane_id"])
        receipt = self._force_stop_receipt(binding, response)
        self._advance_binding(binding, status="CANCELLED")
        return {**dict(response), "cancellation_receipt": receipt}

    def cancellation_evidence(self, experiment_id: str) -> dict[str, Any]:
        """Read and revalidate a force-stopped run's terminal cleanup receipt.

        A cancellation is not a reviewed scientific result and cannot be fed to
        result ingestion.  This receipt proves instead that the explicit
        approval-bound force-stop completed and Harness retired the exact run.
        """

        binding = self.journal.experiment_status(experiment_id)
        if binding is None or binding.get("status") != "CANCELLED":
            raise HarnessIntegrationError(
                "experiment does not have a finalized cancelled binding"
            )
        self._verify_task_bytes(binding)
        receipt_path = self.artifact_root / f"{binding['lane_id']}.force-stop.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessIntegrationError(
                f"force-stop cancellation receipt is unavailable: {exc}"
            ) from exc
        if not isinstance(receipt, Mapping) or receipt.get("content_hash") != content_hash(
            receipt
        ):
            raise HarnessIntegrationError("force-stop cancellation receipt is invalid")
        expected = {
            "experiment_id": binding["experiment_id"],
            "lane_id": binding["lane_id"],
            "run_id": binding["run_id"],
            "objective_confirmation_digest": binding[
                "objective_confirmation_digest"
            ],
            "experiment_digest": binding["experiment_digest"],
            "approval_digest": binding["approval_digest"],
            "task_card_digest": binding["task_card_digest"],
            "status": "CANCELLED",
            "harness_lifecycle": "retired",
            "operator_code": "FORCE_STOP_OK",
        }
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise HarnessIntegrationError(
                "force-stop cancellation receipt differs from durable authority"
            )
        lane_path = Path(str(receipt.get("lane_record_path", ""))).resolve()
        try:
            lane_sha256 = hashlib.sha256(lane_path.read_bytes()).hexdigest()
            lane = read_record(lane_path, "lane/v1")
        except (OSError, ValueError) as exc:
            raise HarnessIntegrationError(
                f"force-stop lane evidence is unavailable: {exc}"
            ) from exc
        if (
            lane_sha256 != receipt.get("lane_record_sha256")
            or lane.get("lane_id") != binding["lane_id"]
            or lane.get("run_id") != binding["run_id"]
            or lane.get("lifecycle") != "retired"
        ):
            raise HarnessIntegrationError(
                "force-stop lane evidence differs from the cancelled run"
            )
        return dict(receipt)

    def retire(self, experiment_id: str, *, confirmation: str) -> dict[str, Any]:
        """Retire an accepted lane using its validated Harness acceptance record."""

        binding = self._launched_binding(experiment_id, allow_terminal=True)
        if binding["status"] not in {"COMPLETED", "FAILED", "ERROR"}:
            raise HarnessIntegrationError(
                "ingest the accepted Harness scientific result before retirement"
            )
        self._require_execution_enabled()
        self._confirm_binding(binding, confirmation)
        try:
            reference = acceptance_reference(
                self.harness_root,
                lane_id=binding["lane_id"],
                run_id=binding["run_id"],
                authority=binding,
            )
        except HarnessEvidenceError as exc:
            raise HarnessIntegrationError(str(exc)) from exc
        return self._operator("lane", "retire", "--acceptance-ref", str(reference))

    def shutdown(self, *, confirmation: str) -> dict[str, Any]:
        """Shut down the whole Harness runtime only on an exact explicit phrase."""

        self._require_execution_enabled()
        if confirmation != "SHUTDOWN RESEARCH HARNESS":
            raise HarnessIntegrationError(
                "shutdown confirmation must equal 'SHUTDOWN RESEARCH HARNESS'"
            )
        return self._operator("harness", "shutdown")

    def record_result(
        self,
        result: Mapping[str, Any],
        *,
        terminal_evidence: Mapping[str, Any],
        artifact_base_dir: str | Path,
    ) -> dict[str, Any]:
        """Accept observations only with exact terminal and local artifact evidence."""

        normalized = validate_record(result, "experiment-result/v1")
        binding = self.journal.experiment_status(normalized["experiment_id"])
        if binding is None or binding["status"] != "LAUNCHED":
            raise HarnessIntegrationError("result requires a matching launched experiment binding")
        for field in (
            "objective_confirmation_digest", "experiment_digest", "approval_digest"
        ):
            if normalized[field] != binding[field]:
                raise HarnessIntegrationError(f"result {field} does not match the launched binding")
        if normalized.get("task_card_digest") != binding["task_card_digest"]:
            raise HarnessIntegrationError(
                "result task_card_digest does not match the launched task bytes"
            )
        if not binding["run_id"] or normalized["run_id"] != binding["run_id"]:
            raise HarnessIntegrationError("result run_id does not match the launched binding")
        self._verify_task_bytes(binding)
        self._ensure_current_objective(binding["objective_confirmation_digest"])
        lifecycle_status, acceptance_decided_at, acceptance_digest = self._verify_terminal_evidence(
            binding, normalized, terminal_evidence
        )
        self._verify_result_artifacts(
            normalized,
            artifact_base_dir=Path(artifact_base_dir).expanduser().resolve(),
        )

        objective = self.journal.get(binding["objective_confirmation_digest"])
        if objective is None or objective.get("schema") != "objective-confirmation/v1":
            raise HarnessIntegrationError("result objective authority is absent")
        chain = self.journal.reconstruct_chain(objective["question_id"])
        portfolios = [
            row for row in chain["records"]
            if row["schema"] == "experiment-candidates/v1"
            and row["selected_experiment_id"] == normalized["experiment_id"]
            and experiment_digest(row) == binding["experiment_digest"]
        ]
        if len(portfolios) != 1:
            raise HarnessIntegrationError("result has no unique journaled experiment specification")
        selected = selected_experiment(portfolios[0])
        if normalized.get("question_id") != objective["question_id"]:
            raise HarnessIntegrationError("result question does not match objective authority")
        if normalized.get("primary_metric") != portfolios[0]["primary_metric"]:
            raise HarnessIntegrationError("result primary metric was not predeclared")
        expected_dataset = {
            key: objective["dataset"][key] for key in ("identifier", "version", "digest")
        }
        if normalized["dataset_identity"] != expected_dataset:
            raise HarnessIntegrationError("result dataset identity differs from the confirmed dataset")
        if normalized["random_seeds"] != selected["random_seeds"]:
            raise HarnessIntegrationError("result random seeds differ from the predeclared seeds")
        observed_parameters = normalized["parameters"]
        if observed_parameters == selected["parameters"]:
            approved_parameters = observed_parameters
        else:
            approved_parameters = observed_parameters.get(
                "approved_candidate_parameters"
            )
            if not isinstance(
                observed_parameters.get("observed_preregistration"), Mapping
            ):
                raise HarnessIntegrationError(
                    "result omits the observed runtime preregistration"
                )
        if approved_parameters != selected["parameters"]:
            raise HarnessIntegrationError("result parameters differ from the predeclared parameters")
        primary_metric = portfolios[0]["primary_metric"]
        if primary_metric not in normalized["metrics"]:
            raise HarnessIntegrationError(
                "result metrics omit the predeclared primary metric"
            )
        # Result schemas may add canonical metadata/endpoints. Every explicitly
        # named candidate metric must either be a result key or the declared
        # primary metric named by the canonical metadata field.
        missing = set(selected["metrics"]) - set(normalized["metrics"])
        missing.discard(primary_metric)
        if missing:
            raise HarnessIntegrationError(
                "result omits predeclared metrics: " + ", ".join(sorted(missing))
            )
        canonical_metadata = {
            "primary_metric",
            "primary_metric_metadata",
            "threshold",
            "accuracy",
            "elapsed_to_threshold_seconds",
            "total_elapsed_seconds",
            "compute_seconds",
            "interventions",
            "cost_usd",
            "token_usage",
            "baseline",
            "evidence_guided",
            "acceleration",
            "scaling_analysis",
        }
        unexpected = (
            set(normalized["metrics"])
            - set(selected["metrics"])
            - canonical_metadata
        )
        if unexpected:
            raise HarnessIntegrationError(
                "result contains undeclared non-canonical metrics: "
                + ", ".join(sorted(unexpected))
            )
        try:
            normalized = self.journal.append(
                normalized,
                source="harness",
                links=((binding["approval_digest"], "authorizes-result-run"),),
                producer_session_id=normalized["run_id"],
                producer_agent_id=normalized["execution_source"],
            )
            self.journal.bind_experiment(
                experiment_id=binding["experiment_id"],
                experiment_digest=binding["experiment_digest"],
                approval_digest=binding["approval_digest"],
                objective_confirmation_digest=binding["objective_confirmation_digest"],
                task_card_digest=binding["task_card_digest"],
                task_card_path=binding["task_card_path"],
                lane_id=binding["lane_id"],
                run_id=binding["run_id"],
                acceptance_decided_at=acceptance_decided_at,
                acceptance_digest=acceptance_digest,
                status=lifecycle_status,
            )
        except JournalConflictError as exc:
            raise HarnessIntegrationError(f"result chain is invalid: {exc}") from exc
        return normalized

    def _verify_terminal_evidence(
        self,
        binding: Mapping[str, Any],
        result: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> tuple[str, str, str]:
        lifecycle_status = {
            "PASS": "COMPLETED",
            "FAIL": "COMPLETED",
            "ERROR": "ERROR",
            "CANCELLED": "CANCELLED",
        }[result["status"]]
        try:
            terminal = verified_terminal_evidence(
                self.harness_root,
                lane_id=binding["lane_id"],
                run_id=binding["run_id"],
                supplied=evidence,
                authority=binding,
                scientific_result=result,
            )
        except HarnessEvidenceError as exc:
            raise HarnessIntegrationError(str(exc)) from exc
        harness_result = terminal.get("result")
        scientific_result = (
            harness_result.get("scientific_result")
            if isinstance(harness_result, Mapping)
            else None
        )
        if not isinstance(scientific_result, Mapping):
            raise HarnessIntegrationError(
                "Harness-reviewed RESULT.json omits scientific_result"
            )
        try:
            attested = validate_record(scientific_result, "experiment-result/v1")
        except (TypeError, ValueError) as exc:
            raise HarnessIntegrationError(
                f"Harness-reviewed scientific_result is invalid: {exc}"
            ) from exc
        if attested != dict(result):
            raise HarnessIntegrationError(
                "experiment result differs from the exact Harness-reviewed scientific_result"
            )
        acceptance = terminal.get("acceptance")
        if not isinstance(acceptance, Mapping):
            raise HarnessIntegrationError(
                "Harness terminal evidence omits the acceptance record"
            )
        accepted_at = acceptance.get("decided_at")
        acceptance_digest = acceptance.get("content_hash")
        if not isinstance(accepted_at, str) or not accepted_at.strip():
            raise HarnessIntegrationError(
                "Harness acceptance omits its authoritative decided_at boundary"
            )
        if (
            not isinstance(acceptance_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", acceptance_digest) is None
        ):
            raise HarnessIntegrationError(
                "Harness acceptance omits its immutable content hash"
            )
        return lifecycle_status, accepted_at, acceptance_digest

    def _verify_result_artifacts(
        self,
        result: Mapping[str, Any],
        *,
        artifact_base_dir: Path,
    ) -> None:
        if not artifact_base_dir.is_dir():
            raise HarnessIntegrationError("artifact_base_dir does not exist")
        for artifact in result["artifact_refs"]:
            uri = artifact["uri"]
            if uri.startswith("artifact:"):
                relative = uri.removeprefix("artifact:").lstrip("/")
                candidate = (artifact_base_dir / relative).resolve()
                try:
                    candidate.relative_to(artifact_base_dir)
                except ValueError as exc:
                    raise HarnessIntegrationError(
                        "artifact URI escapes artifact_base_dir"
                    ) from exc
                path = candidate
            else:
                path = _local_file_uri(uri, field="artifact uri")
            if not path.is_file():
                raise HarnessIntegrationError(f"result artifact does not exist: {uri}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["digest"]:
                raise HarnessIntegrationError(f"result artifact digest mismatch: {uri}")

    def _reviewed_context(
        self,
        experiment_candidates: Mapping[str, Any],
        safety_review: Mapping[str, Any],
        *,
        objective_confirmation_digest: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        portfolio = validate_record(experiment_candidates, "experiment-candidates/v1")
        review = validate_record(safety_review, "safety-review/v1")
        if portfolio["objective_confirmation_digest"] != objective_confirmation_digest:
            raise HarnessIntegrationError("candidate objective authority does not match the request")
        if review["objective_confirmation_digest"] != objective_confirmation_digest:
            raise HarnessIntegrationError("safety review objective authority does not match the request")
        self._ensure_current_objective(objective_confirmation_digest)
        objective = self.journal.get(objective_confirmation_digest)
        if objective is None or objective.get("schema") != "objective-confirmation/v1":
            raise HarnessIntegrationError("objective authority is not journaled")
        self._verify_human_authority_metadata(
            objective, identity_field="confirmed_by"
        )
        if portfolio["question_id"] != objective["question_id"]:
            raise HarnessIntegrationError("candidate question differs from objective authority")
        selected = selected_experiment(portfolio)
        selected_digest = experiment_digest(portfolio)
        if review["experiment_id"] != selected["experiment_id"]:
            raise HarnessIntegrationError("safety review targets another experiment")
        if review["experiment_digest"] != selected_digest:
            raise HarnessIntegrationError("safety review does not bind the exact specification")
        if review["verdict"] != "APPROVAL_REQUIRED":
            raise HarnessIntegrationError("safety review does not permit an approval request")

        stored_portfolio = self.journal.get(portfolio["record_digest"])
        stored_review = self.journal.get(review["record_digest"])
        if stored_portfolio != portfolio or stored_review != review:
            raise HarnessIntegrationError(
                "approval requires the exact journaled candidates and safety review"
            )
        chain = self.journal.reconstruct_chain(objective["question_id"])
        digests = {row["record_digest"] for row in chain["records"]}
        if not {portfolio["record_digest"], review["record_digest"]} <= digests:
            raise HarnessIntegrationError("reviewed records are outside the objective chain")
        feasible = [
            row for row in chain["records"]
            if row["schema"] == "feasibility-check/v1"
            and row["objective_confirmation_digest"] == objective_confirmation_digest
            and row["overall_status"] == "PASS"
        ]
        failed_feasibility = [
            row for row in chain["records"]
            if row["schema"] == "feasibility-check/v1"
            and row["objective_confirmation_digest"] == objective_confirmation_digest
            and row["overall_status"] == "FAIL"
        ]
        if failed_feasibility:
            raise HarnessIntegrationError(
                "a failed feasibility check blocks approval and staging"
            )
        if len(feasible) != 1:
            raise HarnessIntegrationError("objective requires one journaled passing feasibility gate")
        self._verify_scope(objective, portfolio, selected)
        return portfolio, review, objective, feasible[0]

    def _verify_human_authority_metadata(
        self, record: Mapping[str, Any], *, identity_field: str
    ) -> None:
        metadata = self.journal.record_metadata(record["record_digest"])
        if (
            metadata is None
            or metadata.get("source") != "human:operator"
            or metadata.get("producer_agent_id") != record[identity_field]
            or str(metadata.get("producer_session_id", "")).startswith("unspecified:")
        ):
            raise HarnessIntegrationError(
                f"{record['schema']} lacks attributable operator-only human provenance"
            )

    def _verify_scope(
        self,
        objective: Mapping[str, Any],
        portfolio: Mapping[str, Any],
        selected: Mapping[str, Any],
    ) -> None:
        if portfolio["primary_metric"] != objective["primary_metric"]:
            raise HarnessIntegrationError("candidate metric exceeds confirmed objective scope")
        expected_dataset = {
            key: objective["dataset"][key] for key in ("identifier", "version", "digest")
        }
        if portfolio["dataset_identity"] != expected_dataset:
            raise HarnessIntegrationError("candidate dataset exceeds confirmed objective scope")
        scope = objective["execution_scope"]
        for field in ("max_trials", "max_runtime_minutes", "max_cost_usd"):
            if portfolio["resource_bounds"][field] > scope[field]:
                raise HarnessIntegrationError(f"candidate {field} exceeds confirmed scope")
        if selected["estimated_runtime_minutes"] > scope["max_runtime_minutes"]:
            raise HarnessIntegrationError("selected runtime estimate exceeds confirmed scope")
        if selected["estimated_cost_usd"] > scope["max_cost_usd"]:
            raise HarnessIntegrationError("selected cost estimate exceeds confirmed scope")

    def _ensure_current_objective(self, digest: str) -> None:
        objective = self.journal.get(digest)
        if objective is None:
            raise HarnessIntegrationError("objective authority is not journaled")
        try:
            records = self.journal.reconstruct_chain(objective["question_id"])["records"]
        except (KeyError, JournalConflictError) as exc:
            raise HarnessIntegrationError("objective authority is not in a valid chain") from exc
        if any(
            record.get("supersedes_objective_confirmation_digest") == digest
            for record in records
        ):
            raise HarnessIntegrationError("objective authority is superseded and stale")

    def _matching_binding(
        self, prepared: PreparedExperiment, *, required_status: str
    ) -> dict[str, Any]:
        binding = self.journal.experiment_status(prepared.experiment_id)
        if binding is None or binding["status"] != required_status:
            raise HarnessIntegrationError(f"experiment binding is not {required_status.lower()}")
        expected = {
            "objective_confirmation_digest": prepared.objective_confirmation_digest,
            "experiment_digest": prepared.experiment_digest,
            "approval_digest": prepared.approval_digest,
            "task_card_digest": prepared.task_card_digest,
            "lane_id": prepared.lane_id,
        }
        if any(binding[key] != value for key, value in expected.items()):
            raise HarnessIntegrationError("prepared task does not match its durable binding")
        self._verify_task_bytes(binding)
        return binding

    def _launched_binding(
        self, experiment_id: str, *, allow_terminal: bool = False
    ) -> dict[str, Any]:
        binding = self.journal.experiment_status(experiment_id)
        allowed = {"LAUNCHED", "RUNNING"}
        if allow_terminal:
            allowed.update({"COMPLETED", "FAILED", "ERROR"})
        if binding is None or binding.get("status") not in allowed:
            raise HarnessIntegrationError(
                "experiment does not have a matching launched Harness binding"
            )
        if not binding.get("lane_id") or not binding.get("run_id"):
            raise HarnessIntegrationError("launched binding omits lane or run identity")
        self._verify_task_bytes(binding)
        self._ensure_current_objective(binding["objective_confirmation_digest"])
        return binding

    def _cleanup_binding(self, experiment_id: str) -> dict[str, Any]:
        """Resolve exact cleanup authority without reviving stale execution.

        Superseding an objective prevents new execution, status adoption, and
        result ingestion, but it cannot revoke the duty to stop a process that
        may already be running. ``LAUNCHING`` is deliberately included because
        that two-phase state means provider start is ambiguous and cleanup must
        assume the process exists until Harness proves retirement.
        """

        binding = self.journal.experiment_status(experiment_id)
        if binding is None or binding.get("status") not in {
            "LAUNCHING",
            "LAUNCHED",
            "RUNNING",
        }:
            raise HarnessIntegrationError(
                "experiment does not have an exact run eligible for cleanup"
            )
        if not binding.get("lane_id") or not binding.get("run_id"):
            raise HarnessIntegrationError("cleanup binding omits lane or run identity")
        self._verify_task_bytes(binding)
        objective = self.journal.get(binding["objective_confirmation_digest"])
        if objective is None or objective.get("schema") != "objective-confirmation/v1":
            raise HarnessIntegrationError(
                "cleanup binding objective authority is unavailable"
            )
        return binding

    @staticmethod
    def _confirm_binding(binding: Mapping[str, Any], confirmation: str) -> None:
        if confirmation != binding["approval_digest"]:
            raise HarnessIntegrationError(
                "confirmation does not match the experiment approval digest"
            )

    @staticmethod
    def _require_execution_enabled() -> None:
        if os.environ.get("AI_RESEARCHER_ENABLE_EXECUTION") != "1":
            raise HarnessIntegrationError(
                "execution is disabled; set AI_RESEARCHER_ENABLE_EXECUTION=1 explicitly"
            )

    def _advance_binding(self, binding: Mapping[str, Any], *, status: str) -> None:
        try:
            self.journal.bind_experiment(
                experiment_id=binding["experiment_id"],
                experiment_digest=binding["experiment_digest"],
                approval_digest=binding["approval_digest"],
                objective_confirmation_digest=binding["objective_confirmation_digest"],
                task_card_digest=binding["task_card_digest"],
                task_card_path=binding["task_card_path"],
                lane_id=binding["lane_id"],
                run_id=binding["run_id"],
                status=status,
            )
        except JournalConflictError as exc:
            raise HarnessIntegrationError(
                f"Harness lifecycle update is inconsistent: {exc}"
            ) from exc

    def _force_stop_receipt(
        self, binding: Mapping[str, Any], response: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Verify Harness cleanup and persist its authority-bound receipt."""

        if (
            not isinstance(response, Mapping)
            or response.get("ok") is not True
            or response.get("code") != "FORCE_STOP_OK"
        ):
            code = response.get("code") if isinstance(response, Mapping) else None
            raise HarnessIntegrationError(
                f"Harness force-stop did not retire the lane (code={code or 'UNKNOWN'})"
            )
        evidence_paths = response.get("evidence_paths")
        if not isinstance(evidence_paths, list) or len(evidence_paths) != 1:
            raise HarnessIntegrationError(
                "successful force-stop must return one authoritative lane record"
            )
        lane_path = Path(str(evidence_paths[0])).expanduser().resolve()
        try:
            lane_bytes = lane_path.read_bytes()
            lane = read_record(lane_path, "lane/v1")
        except (OSError, ValueError) as exc:
            raise HarnessIntegrationError(
                f"successful force-stop lane evidence is invalid: {exc}"
            ) from exc
        if (
            lane.get("lane_id") != binding["lane_id"]
            or lane.get("run_id") != binding["run_id"]
            or lane.get("lifecycle") != "retired"
        ):
            raise HarnessIntegrationError(
                "successful force-stop evidence does not prove exact-run retirement"
            )
        receipt: dict[str, Any] = {
            "schema": "harness-force-stop-evidence/v1",
            "experiment_id": binding["experiment_id"],
            "lane_id": binding["lane_id"],
            "run_id": binding["run_id"],
            "objective_confirmation_digest": binding[
                "objective_confirmation_digest"
            ],
            "experiment_digest": binding["experiment_digest"],
            "approval_digest": binding["approval_digest"],
            "task_card_digest": binding["task_card_digest"],
            "status": "CANCELLED",
            "harness_lifecycle": "retired",
            "operator_code": "FORCE_STOP_OK",
            "lane_record_path": str(lane_path),
            "lane_record_sha256": hashlib.sha256(lane_bytes).hexdigest(),
        }
        receipt["content_hash"] = content_hash(receipt)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            self.artifact_root / f"{binding['lane_id']}.force-stop.json",
            receipt,
        )
        return receipt

    def _abort_launch_handshake(self, binding: Mapping[str, Any]) -> str | None:
        """Stop one possibly-started run and cancel authority only with proof.

        A launcher error is ambiguous: the provider process may already exist.
        Therefore rollback to STAGED is forbidden.  The exact bound lane is
        force-stopped, and only a successful Harness response permits the
        durable authority to advance from LAUNCHING to CANCELLED.
        """

        try:
            stopped = self._operator(
                "lane", "force-stop", "--lane-id", str(binding["lane_id"])
            )
            self._force_stop_receipt(binding, stopped)
            try:
                self._advance_binding(binding, status="CANCELLED")
            except Exception:
                # Do not leave a receipt that claims durable cancellation when
                # the journal transition itself could not be committed.
                (self.artifact_root / f"{binding['lane_id']}.force-stop.json").unlink(
                    missing_ok=True
                )
                raise
        except Exception as exc:  # retain LAUNCHING for explicit operator recovery
            return str(exc)
        return None

    def _provider_options(
        self,
        provider: str,
        model: str,
        provider_options: Mapping[str, Any],
    ) -> dict[str, str]:
        if not isinstance(provider, str) or not provider.strip():
            raise HarnessIntegrationError("provider must be explicit")
        if not isinstance(model, str) or not model.strip():
            raise HarnessIntegrationError("model must be explicit")
        if not isinstance(provider_options, Mapping):
            raise HarnessIntegrationError("provider options must be an object")
        try:
            return _validate_provider_launch_config(
                self.harness_root,
                provider_id=provider.strip(),
                model=model.strip(),
                launch_config=dict(provider_options),
            )
        except Exception as exc:
            raise HarnessIntegrationError(
                f"invalid {provider} provider options: {exc}"
            ) from exc

    @staticmethod
    def _verify_result_authority(
        binding: Mapping[str, Any], result: Mapping[str, Any]
    ) -> None:
        expected = {
            "experiment_id": binding["experiment_id"],
            "run_id": binding["run_id"],
            "objective_confirmation_digest": binding["objective_confirmation_digest"],
            "experiment_digest": binding["experiment_digest"],
            "approval_digest": binding["approval_digest"],
            "task_card_digest": binding["task_card_digest"],
        }
        mismatches = [
            field for field, value in expected.items() if result.get(field) != value
        ]
        if mismatches:
            raise HarnessIntegrationError(
                "scientific result differs from launched authority: "
                + ", ".join(mismatches)
            )

    @staticmethod
    def _verify_task_bytes(binding: Mapping[str, Any]) -> None:
        path = Path(binding["task_card_path"])
        if not path.is_file():
            raise HarnessIntegrationError("staged task card is missing")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != binding["task_card_digest"]:
            raise HarnessIntegrationError("staged task card bytes no longer match the binding")
        text = path.read_text(encoding="utf-8")
        for field in (
            "objective_confirmation_digest", "experiment_digest", "approval_digest"
        ):
            if binding[field] not in text:
                raise HarnessIntegrationError(f"task card omits the bound {field}")

    def _task_card(
        self,
        portfolio: Mapping[str, Any],
        selected: Mapping[str, Any],
        review: Mapping[str, Any],
        approval: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> dict[str, Any]:
        chain = self.journal.reconstruct_chain(objective["question_id"])
        hypotheses = [
            hypothesis
            for record in chain["records"]
            if record["schema"] == "hypothesis-portfolio/v1"
            for hypothesis in record["hypotheses"]
            if hypothesis["hypothesis_id"] == portfolio["hypothesis_id"]
        ]
        if len(hypotheses) != 1:
            raise HarnessIntegrationError(
                "selected experiment requires one exact linked hypothesis"
            )
        execution_specification = {
            "experiment_candidates_id": portfolio["experiment_candidates_id"],
            "hypothesis_id": portfolio["hypothesis_id"],
            "supporting_evidence_ids": hypotheses[0]["supporting_evidence_ids"],
            "selected_candidate": selected,
        }
        specification = json.dumps(execution_specification, indent=2, sort_keys=True)
        safety = json.dumps(
            {
                "required_controls": review["required_controls"],
                "prohibited_actions": review["prohibited_actions"],
                "approval_constraints": approval["constraints"],
                "confirmed_scope": objective["execution_scope"],
            },
            indent=2,
            sort_keys=True,
        )
        task = (
            "Execute exactly the approved computational experiment below. "
            "Do not broaden the method, dataset, metrics, controls, seeds, parameters, "
            "network access, mutations, or resource bounds. Return a complete "
            "experiment-result/v1 JSON record with immutable log/artifact references. "
            "Place that exact record in the Harness RESULT.json object's "
            "scientific_result field so the completion review hashes the measurements.\n\n"
            f"Objective confirmation digest: {objective['record_digest']}\n"
            f"Experiment digest: {experiment_digest(portfolio)}\n"
            f"Approval digest: {approval['record_digest']}\n"
            f"Confirmed dataset digest: {objective['dataset']['digest']}\n"
            f"Experiment specification:\n{specification}\n\n"
            f"Mandatory safety controls:\n{safety}"
        )
        metrics = [str(item) for item in selected["metrics"]]
        card = contracts.make_task_card(
            task=task,
            base_commit=self._git_head(),
            branch=f"experiment/{_slug(selected['experiment_id'])}",
            acceptance_criteria=[
                "The run uses the exact approved experiment specification and declared controls.",
                "The result reports exactly the predeclared metrics: " + ", ".join(metrics),
                "The result preserves dataset, code, environment, parameter, seed, timing, log, and artifact identities.",
                "Harness RESULT.json embeds the exact experiment-result/v1 object under scientific_result.",
                "No prohibited action in the linked safety review is performed.",
            ],
            deliverables=[
                "One experiment-result/v1 JSON record",
                "One Harness result/v1 record embedding that exact scientific_result",
                "Reproducible run artifacts and machine-readable metric logs",
            ],
            reason_for_acceptance_and_deliverables=(
                "These outputs preserve the human-confirmed scope and approved scientific "
                "specification while supporting independent result analysis."
            ),
        )
        card["research_authority"] = {
            "objective_confirmation_digest": objective["record_digest"],
            "experiment_digest": experiment_digest(portfolio),
            "approval_digest": approval["record_digest"],
        }
        # ``make_task_card`` hashes the initial payload. Research authority is
        # part of the executable card, so refresh and revalidate the native
        # Harness identity after adding it. Otherwise terminal evidence would
        # correctly reject the mutated card as hash-inconsistent.
        card["content_hash"] = contracts.content_hash(card)
        contracts.validate_task_card(card)
        return card

    def _git_head(self) -> str:
        process = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo_root,
            text=True, capture_output=True, check=False,
        )
        if process.returncode != 0 or not process.stdout.strip():
            raise HarnessIntegrationError("repository HEAD is unavailable")
        return process.stdout.strip()

    def _operator(self, *arguments: str) -> dict[str, Any]:
        environment = os.environ.copy()
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(self.harness_root) + (
            os.pathsep + existing if existing else ""
        )
        process = subprocess.run(
            [sys.executable, "-m", "orchestrator_harness.operator_launch", "--json", *arguments],
            cwd=self.harness_root, env=environment, text=True,
            capture_output=True, check=False,
        )
        if process.returncode != 0:
            raise HarnessIntegrationError(
                f"harness command failed ({process.returncode}): {process.stderr.strip()}"
            )
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise HarnessIntegrationError("harness returned non-JSON output") from exc


def _lane_id(experiment_id: str) -> str:
    return f"research-{_slug(experiment_id)}"[:80]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.").lower()
    if not slug:
        raise HarnessIntegrationError("experiment_id cannot form a lane identity")
    return slug


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _local_file_uri(value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise HarnessIntegrationError(f"{field} must be a non-empty local file URI")
    parsed = urlparse(value)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise HarnessIntegrationError(f"{field} must use file:// and local bytes")
    return Path(unquote(parsed.path)).expanduser().resolve()
