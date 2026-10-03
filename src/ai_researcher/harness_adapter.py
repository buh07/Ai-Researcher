"""Narrow authority boundary between Omnigent and the execution harness."""

from __future__ import annotations

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

from memory_harness import contracts
from orchestrator_harness.task_cards import validate_task_card

from .journal import ResearchJournal
from .records import experiment_digest, selected_experiment, validate_record


class HarnessIntegrationError(RuntimeError):
    """The requested harness transition is unauthorized or inconsistent."""


@dataclass(frozen=True)
class PreparedExperiment:
    experiment_id: str
    experiment_digest: str
    approval_digest: str
    lane_id: str
    task_card_path: Path
    task_card: dict[str, Any]


class HarnessAdapter:
    """Translate approved science records into one exact harness task."""

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
    ) -> dict[str, Any]:
        """Persist the reviewed plan and return its exact approval identity."""

        portfolio = validate_record(experiment_candidates, "experiment-candidates/v1")
        review = validate_record(safety_review, "safety-review/v1")
        selected = selected_experiment(portfolio)
        if review["experiment_id"] != selected["experiment_id"]:
            raise HarnessIntegrationError("safety review targets another experiment")
        if review["verdict"] != "APPROVAL_REQUIRED":
            raise HarnessIntegrationError("safety review does not permit an approval request")
        portfolio = self.journal.append(portfolio, source="omnigent:experiment-designer")
        review = self.journal.append(
            review,
            source="omnigent:safety-reviewer",
            links=((portfolio["record_digest"], "reviews-selected-experiment"),),
        )
        return {
            "experiment_id": selected["experiment_id"],
            "experiment_digest": experiment_digest(portfolio),
            "approval_question": review["approval_question"],
            "required_controls": review["required_controls"],
            "prohibited_actions": review["prohibited_actions"],
        }

    def prepare(
        self,
        experiment_candidates: Mapping[str, Any],
        safety_review: Mapping[str, Any],
        approval: Mapping[str, Any],
    ) -> PreparedExperiment:
        portfolio = validate_record(experiment_candidates, "experiment-candidates/v1")
        review = validate_record(safety_review, "safety-review/v1")
        authorized = validate_record(approval, "human-approval/v1")
        request = self.approval_request(portfolio, review)
        selected = selected_experiment(portfolio)
        selected_digest = request["experiment_digest"]
        experiment_id = selected["experiment_id"]

        if review["experiment_id"] != experiment_id:
            raise HarnessIntegrationError("safety review targets another experiment")
        if review["verdict"] != "APPROVAL_REQUIRED":
            raise HarnessIntegrationError("safety review does not permit an approval request")
        if authorized["experiment_id"] != experiment_id:
            raise HarnessIntegrationError("human approval targets another experiment")
        if authorized["experiment_digest"] != selected_digest:
            raise HarnessIntegrationError("human approval does not bind the exact specification")

        portfolio = self.journal.append(portfolio, source="omnigent:experiment-designer")
        review = self.journal.append(
            review,
            source="omnigent:safety-reviewer",
            links=((portfolio["record_digest"], "reviews-selected-experiment"),),
        )
        authorized = self.journal.append(
            authorized,
            source="human",
            links=((review["record_digest"], "approves-after-review"),),
        )

        lane_id = _lane_id(experiment_id)
        task_card = self._task_card(portfolio, selected, review, authorized)
        validate_task_card(task_card, Path("generated-research-task.json"))
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        task_path = self.artifact_root / f"{lane_id}.json"
        _atomic_json(task_path, task_card)
        self.journal.bind_experiment(
            experiment_id=experiment_id,
            experiment_digest=selected_digest,
            approval_digest=authorized["record_digest"],
            task_card_path=task_path,
            lane_id=lane_id,
            status="STAGED",
        )
        return PreparedExperiment(
            experiment_id,
            selected_digest,
            authorized["record_digest"],
            lane_id,
            task_path,
            task_card,
        )

    def launch(
        self,
        prepared: PreparedExperiment,
        *,
        confirmation: str,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        """Launch only with two independent, exact execution gates."""

        if os.environ.get("AI_RESEARCHER_ENABLE_EXECUTION") != "1":
            raise HarnessIntegrationError(
                "execution is disabled; set AI_RESEARCHER_ENABLE_EXECUTION=1 explicitly"
            )
        if confirmation != prepared.approval_digest:
            raise HarnessIntegrationError("launch confirmation does not match the approval digest")
        if not (self.harness_root / "local-config" / "harness-config.json").is_file():
            raise HarnessIntegrationError("run harness setup with a local configuration first")

        bootstrap = self._operator(
            "lane",
            "bootstrap",
            "--lane-id",
            prepared.lane_id,
            "--provider",
            provider,
            "--model",
            model,
            "--task-card",
            str(prepared.task_card_path),
        )
        launch = self._operator("lane", "launch", "--lane-id", prepared.lane_id)
        run_id = _find_value(launch, "run_id") or _find_value(bootstrap, "run_id")
        self.journal.bind_experiment(
            experiment_id=prepared.experiment_id,
            experiment_digest=prepared.experiment_digest,
            approval_digest=prepared.approval_digest,
            task_card_path=prepared.task_card_path,
            lane_id=prepared.lane_id,
            run_id=run_id,
            status="LAUNCHED",
        )
        return {"bootstrap": bootstrap, "launch": launch}

    def status(self, experiment_id: str) -> dict[str, Any] | None:
        return self.journal.experiment_status(experiment_id)

    def record_result(self, result: Mapping[str, Any]) -> dict[str, Any]:
        normalized = validate_record(result, "experiment-result/v1")
        binding = self.journal.experiment_status(normalized["experiment_id"])
        if binding is None:
            raise HarnessIntegrationError("result has no staged experiment binding")
        normalized = self.journal.append(
            normalized,
            source="harness",
            links=((binding["approval_digest"], "authorizes-result-run"),),
        )
        self.journal.bind_experiment(
            experiment_id=binding["experiment_id"],
            experiment_digest=binding["experiment_digest"],
            approval_digest=binding["approval_digest"],
            task_card_path=binding["task_card_path"],
            lane_id=binding["lane_id"],
            run_id=normalized["run_id"],
            status="COMPLETED",
        )
        return normalized

    def _task_card(
        self,
        portfolio: Mapping[str, Any],
        selected: Mapping[str, Any],
        review: Mapping[str, Any],
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        specification = json.dumps(selected, indent=2, sort_keys=True)
        safety = json.dumps(
            {
                "required_controls": review["required_controls"],
                "prohibited_actions": review["prohibited_actions"],
                "approval_constraints": approval["constraints"],
            },
            indent=2,
            sort_keys=True,
        )
        task = (
            "Execute exactly the approved computational experiment below. "
            "Do not broaden the method, dataset, metrics, controls, seeds, or resource bounds. "
            "Return a complete experiment-result/v1 JSON record and artifact references.\n\n"
            f"Approval digest: {approval['record_digest']}\n"
            f"Experiment specification:\n{specification}\n\n"
            f"Mandatory safety controls:\n{safety}"
        )
        metrics = [str(item) for item in selected["metrics"]]
        return contracts.make_task_card(
            task=task,
            base_commit=self._git_head(),
            branch=f"experiment/{_slug(selected['experiment_id'])}",
            acceptance_criteria=[
                "The run uses the exact approved experiment specification and declared controls.",
                "The result reports every predeclared metric: " + ", ".join(metrics),
                "The result includes code, dataset, environment, seed, timing, and artifact identities.",
                "No prohibited action in the linked safety review is performed.",
            ],
            deliverables=[
                "One experiment-result/v1 JSON record",
                "Reproducible run artifacts and machine-readable metrics",
            ],
            reason_for_acceptance_and_deliverables=(
                "These outputs preserve the approved scientific scope and provide the evidence "
                "needed for independent result analysis."
            ),
        )

    def _git_head(self) -> str:
        process = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
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
            [
                sys.executable,
                "-m",
                "orchestrator_harness.operator_launch",
                "--json",
                *arguments,
            ],
            cwd=self.harness_root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
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


def _find_value(value: Any, key: str) -> str | None:
    if isinstance(value, Mapping):
        found = value.get(key)
        if isinstance(found, str) and found:
            return found
        for nested in value.values():
            result = _find_value(nested, key)
            if result:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _find_value(nested, key)
            if result:
                return result
    return None
