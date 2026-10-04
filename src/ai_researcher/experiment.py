"""Bounded, reproducible baseline-versus-guided classification experiment.

The hermetic path uses an explicitly synthetic, tests-only fixture.  The live
path verifies and retrieves pinned OpenML task 59 (Iris, dataset 61, version 1)
without requiring an OpenML client dependency.  Both arms evaluate the same
candidate set, split, metric, threshold, trial cap, and wall-time cap; only the
preregistered candidate ordering differs.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import io
import json
import math
import multiprocessing
import os
import platform
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .journal import ResearchJournal
from .records import experiment_digest as approved_experiment_digest
from .records import validate_record


OPENML_TASK_ID = 59
OPENML_DATASET_ID = 61
OPENML_DATASET_VERSION = 1
OPENML_TARGET = "class"
PRIMARY_METRIC = "trials_to_threshold"
QUALITY_METRIC = "accuracy"
OPENML_TASK_URL = "https://www.openml.org/api/v1/json/task/59"
OPENML_DATASET_METADATA_URL = "https://www.openml.org/api/v1/json/data/61"
OPENML_DATA_URL = "https://openml.org/data/v1/download/61/iris.arff"

MAX_TRIALS_PER_ARM = 16
MAX_SECONDS_PER_ARM = 900.0
MAX_DATA_BYTES = 5_000_000
MAX_ROWS = 10_000
MAX_FEATURES = 128
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "openml"


class ExperimentValidationError(ValueError):
    """An objective, dataset, or experiment condition failed closed."""


class LiveDataUnavailableError(RuntimeError):
    """The pinned OpenML task could not be verified or retrieved."""


@dataclass(frozen=True)
class ArmWorkflowMeasurements:
    """Observed workflow overhead and optional provider resource telemetry.

    These values are accepted only with a digest-addressed measurement source.
    They are observations from the orchestration/harness boundary, not estimates.
    A missing object means that the corresponding values are unavailable; it
    must never be interpreted as zero.
    """

    retrieval_seconds: float
    planning_seconds: float
    approval_seconds: float
    preflight_seconds: float
    agent_tool_seconds: float
    human_interventions: int | None
    cost_usd: float | None
    token_usage: int | None
    source_digest: str

    @classmethod
    def from_value(
        cls, value: ArmWorkflowMeasurements | Mapping[str, Any]
    ) -> ArmWorkflowMeasurements:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ExperimentValidationError(
                "arm workflow measurements must be a structured object"
            )
        try:
            return cls(**{field: value[field] for field in cls.__dataclass_fields__})
        except (KeyError, TypeError) as exc:
            raise ExperimentValidationError(
                "arm workflow measurements are missing required fields"
            ) from exc

    def __post_init__(self) -> None:
        for field in (
            "retrieval_seconds",
            "planning_seconds",
            "approval_seconds",
            "preflight_seconds",
            "agent_tool_seconds",
        ):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ExperimentValidationError(
                    f"arm workflow measurement {field} must be finite and non-negative"
                )
        for field in ("human_interventions", "token_usage"):
            value = getattr(self, field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ExperimentValidationError(
                    f"arm workflow measurement {field} must be a non-negative integer or null"
                )
        if self.cost_usd is not None and (
            isinstance(self.cost_usd, bool)
            or not isinstance(self.cost_usd, (int, float))
            or not math.isfinite(self.cost_usd)
            or self.cost_usd < 0
        ):
            raise ExperimentValidationError(
                "arm workflow measurement cost_usd must be finite, non-negative, or null"
            )
        if re.fullmatch(r"[0-9a-f]{64}", self.source_digest) is None:
            raise ExperimentValidationError(
                "arm workflow measurement source_digest must be a lowercase SHA-256 digest"
            )

    @property
    def overhead_seconds(self) -> float:
        return float(
            self.retrieval_seconds
            + self.planning_seconds
            + self.approval_seconds
            + self.preflight_seconds
            + self.agent_tool_seconds
        )


@dataclass(frozen=True)
class HumanExecutionScope:
    """Machine-enforced limits copied from the human-confirmed objective."""

    max_trials: int
    max_runtime_minutes: float
    max_cost_usd: float
    compute: str
    network_access: str
    mutation_permissions: tuple[str, ...]

    @classmethod
    def from_value(
        cls, value: HumanExecutionScope | Mapping[str, Any]
    ) -> HumanExecutionScope:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ExperimentValidationError("execution_scope must be a structured object")
        try:
            permissions = value["mutation_permissions"]
            if not isinstance(permissions, (list, tuple)):
                raise TypeError
            return cls(
                max_trials=value["max_trials"],
                max_runtime_minutes=value["max_runtime_minutes"],
                max_cost_usd=value["max_cost_usd"],
                compute=value["compute"],
                network_access=value["network_access"],
                mutation_permissions=tuple(permissions),
            )
        except (KeyError, TypeError) as exc:
            raise ExperimentValidationError(
                "execution_scope is missing required structured fields"
            ) from exc

    def __post_init__(self) -> None:
        if isinstance(self.max_trials, bool) or not isinstance(self.max_trials, int):
            raise ExperimentValidationError("execution_scope.max_trials must be an integer")
        if self.max_trials < 1:
            raise ExperimentValidationError("execution_scope.max_trials must be positive")
        for field in ("max_runtime_minutes", "max_cost_usd"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ExperimentValidationError(f"execution_scope.{field} must be numeric")
            if not math.isfinite(value) or value < 0:
                raise ExperimentValidationError(
                    f"execution_scope.{field} must be finite and non-negative"
                )
        for field in ("compute", "network_access"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ExperimentValidationError(
                    f"execution_scope.{field} must be a non-empty string"
                )
        if not self.mutation_permissions or any(
            not isinstance(item, str) or not item.strip()
            for item in self.mutation_permissions
        ):
            raise ExperimentValidationError(
                "execution_scope.mutation_permissions must be non-empty strings"
            )


@dataclass(frozen=True)
class DataGovernanceAttestation:
    """Human-reviewed license and privacy evidence for one exact dataset digest."""

    license_status: str
    license_evidence: str
    privacy_status: str
    privacy_evidence: str
    verified_by: str
    verified_at: str

    @classmethod
    def from_value(
        cls, value: DataGovernanceAttestation | Mapping[str, Any]
    ) -> DataGovernanceAttestation:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ExperimentValidationError("data_governance must be a structured object")
        try:
            return cls(**{field: value[field] for field in cls.__dataclass_fields__})
        except (KeyError, TypeError) as exc:
            raise ExperimentValidationError(
                "data_governance is missing required attestation fields"
            ) from exc

    def __post_init__(self) -> None:
        for field in ("license_status", "privacy_status"):
            if getattr(self, field) not in {"VERIFIED", "UNKNOWN", "REJECTED"}:
                raise ExperimentValidationError(
                    f"data_governance.{field} must be VERIFIED, UNKNOWN, or REJECTED"
                )
        for field in (
            "license_evidence",
            "privacy_evidence",
            "verified_by",
            "verified_at",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ExperimentValidationError(
                    f"data_governance.{field} must be a non-empty string"
                )
        _require_timestamp(self.verified_at, "data_governance.verified_at")


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Exact journal-backed authority required before any live data access."""

    journal_path: Path
    experiment_id: str
    objective_confirmation_digest: str
    experiment_digest: str
    approval_digest: str
    task_card_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "journal_path", Path(self.journal_path).expanduser().resolve()
        )
        if not self.experiment_id.strip():
            raise ExperimentValidationError("authorization experiment_id is required")
        for field in (
            "objective_confirmation_digest",
            "experiment_digest",
            "approval_digest",
            "task_card_digest",
        ):
            if re.fullmatch(r"[0-9a-f]{64}", getattr(self, field)) is None:
                raise ExperimentValidationError(
                    f"authorization {field} must be a lowercase SHA-256 digest"
                )


def _canonical_bytes(value: Mapping[str, Any] | Sequence[Any]) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExperimentValidationError("experiment values must be finite JSON") from exc


def _digest(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ExperimentValidationError(f"{field} must include a timezone")


@dataclass(frozen=True)
class HumanObjective:
    """The five human-owned scope fields plus attributable confirmation."""

    objective: str
    primary_metric: str
    openml_task_id: int
    dataset_identifier: str
    openml_dataset_id: int
    openml_dataset_version: int
    dataset_digest: str
    risk_tolerance: str
    execution_scope: HumanExecutionScope | Mapping[str, Any]
    data_governance: DataGovernanceAttestation | Mapping[str, Any]
    confirmed_by: str
    confirmed_at: str
    objective_confirmation_digest: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "objective",
            "primary_metric",
            "dataset_identifier",
            "risk_tolerance",
            "confirmed_by",
            "confirmed_at",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ExperimentValidationError(f"{field} must be a non-empty string")
        if self.primary_metric != PRIMARY_METRIC:
            raise ExperimentValidationError(
                f"primary_metric must be preregistered as {PRIMARY_METRIC}"
            )
        if self.openml_task_id != OPENML_TASK_ID:
            raise ExperimentValidationError(
                f"openml_task_id must be the pinned task {OPENML_TASK_ID}"
            )
        if self.openml_dataset_id != OPENML_DATASET_ID:
            raise ExperimentValidationError(
                f"openml_dataset_id must be the pinned dataset {OPENML_DATASET_ID}"
            )
        if self.openml_dataset_version != OPENML_DATASET_VERSION:
            raise ExperimentValidationError(
                "openml_dataset_version does not match the pinned version"
            )
        if re.fullmatch(r"[0-9a-f]{64}", self.dataset_digest) is None:
            raise ExperimentValidationError(
                "dataset_digest must be a lowercase SHA-256 digest"
            )
        object.__setattr__(
            self, "execution_scope", HumanExecutionScope.from_value(self.execution_scope)
        )
        object.__setattr__(
            self,
            "data_governance",
            DataGovernanceAttestation.from_value(self.data_governance),
        )
        if self.objective_confirmation_digest is not None and re.fullmatch(
            r"[0-9a-f]{64}", self.objective_confirmation_digest
        ) is None:
            raise ExperimentValidationError(
                "objective_confirmation_digest must be a lowercase SHA-256 digest"
            )
        _require_timestamp(self.confirmed_at, "confirmed_at")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        supplied_digest = payload.pop("objective_confirmation_digest")
        payload["quality_metric"] = QUALITY_METRIC
        payload["objective_packet_digest"] = _digest(payload)
        payload["objective_confirmation_digest"] = supplied_digest
        return payload

    @property
    def quality_metric(self) -> str:
        return QUALITY_METRIC


def _required_objective_digest(objective: Mapping[str, Any]) -> str:
    value = objective.get("objective_confirmation_digest")
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ExperimentValidationError(
            "an exact journal objective_confirmation_digest is required for integration output"
        )
    return value


def _enforce_scope(
    objective: HumanObjective,
    config: ExperimentConfig,
    *,
    live: bool,
    network_timeout_seconds: float,
) -> None:
    scope = objective.execution_scope
    assert isinstance(scope, HumanExecutionScope)
    attempted_trials = config.max_trials_per_arm * 2
    if attempted_trials > scope.max_trials:
        raise ExperimentValidationError(
            "experiment trial budget exceeds human-confirmed execution_scope.max_trials"
        )
    network_budget = network_timeout_seconds * 3 if live else 0.0
    requested_seconds = config.max_seconds_per_arm * 2 + network_budget
    if requested_seconds > scope.max_runtime_minutes * 60:
        raise ExperimentValidationError(
            "experiment runtime budget exceeds human-confirmed execution_scope"
        )
    requested_cost_usd = config.estimated_cost_usd
    if requested_cost_usd > scope.max_cost_usd:
        raise ExperimentValidationError("experiment cost exceeds execution_scope")
    if "cpu" not in scope.compute.lower():
        raise ExperimentValidationError("execution_scope.compute does not authorize CPU")
    if not any("artifact" in item.lower() for item in scope.mutation_permissions):
        raise ExperimentValidationError(
            "execution_scope does not authorize local artifact writes"
        )
    network = scope.network_access.strip().lower()
    if live and network not in {
        "dataset-download-only",
        "read-only-openml",
        "openml-read-only",
    }:
        raise ExperimentValidationError(
            "execution_scope.network_access does not authorize read-only OpenML access"
        )


def _verify_governance(objective: HumanObjective) -> None:
    governance = objective.data_governance
    assert isinstance(governance, DataGovernanceAttestation)
    if governance.license_status != "VERIFIED":
        raise ExperimentValidationError(
            "license status is not VERIFIED; UNKNOWN and REJECTED fail closed"
        )
    if governance.privacy_status != "VERIFIED":
        raise ExperimentValidationError(
            "privacy status is not VERIFIED; UNKNOWN and REJECTED fail closed"
        )


def _scope_payload(scope: HumanExecutionScope) -> dict[str, Any]:
    payload = asdict(scope)
    payload["mutation_permissions"] = list(scope.mutation_permissions)
    return payload


def _verify_journal_objective(
    objective: HumanObjective, journal_path: str | Path | None
) -> tuple[ResearchJournal, dict[str, Any]]:
    if journal_path is None:
        raise ExperimentValidationError(
            "live preflight requires journal_path for the human-confirmed objective"
        )
    if objective.objective_confirmation_digest is None:
        raise ExperimentValidationError(
            "live preflight requires a real objective_confirmation_digest"
        )
    journal = ResearchJournal(journal_path)
    confirmed = journal.get(objective.objective_confirmation_digest)
    if confirmed is None or confirmed.get("schema") != "objective-confirmation/v1":
        raise ExperimentValidationError("objective authorization is not a journal record")
    dataset = confirmed.get("dataset")
    if not isinstance(dataset, Mapping) or (
        dataset.get("identifier") != objective.dataset_identifier
        or str(dataset.get("version")) != str(objective.openml_dataset_version)
        or dataset.get("digest") != objective.dataset_digest
        or confirmed.get("primary_metric") != objective.primary_metric
    ):
        raise ExperimentValidationError(
            "live objective dataset or primary metric does not match the journal"
        )
    if confirmed.get("execution_scope") != _scope_payload(objective.execution_scope):
        raise ExperimentValidationError(
            "live execution scope does not match the journal-confirmed scope"
        )
    risk = confirmed.get("risk_tolerance")
    if not isinstance(risk, Mapping) or risk.get("level") != objective.risk_tolerance:
        raise ExperimentValidationError(
            "live risk tolerance does not match the journal-confirmed objective"
        )
    return journal, confirmed


def _verify_live_authorization(
    objective: HumanObjective, authorization: ExecutionAuthorization | None
) -> tuple[dict[str, str], _ApprovedPlan]:
    if os.environ.get("AI_RESEARCHER_ENABLE_EXECUTION") != "1":
        raise ExperimentValidationError(
            "live execution is disabled; set AI_RESEARCHER_ENABLE_EXECUTION=1"
        )
    if authorization is None:
        raise ExperimentValidationError(
            "live execution requires exact journal-backed HarnessAdapter authorization"
        )
    if objective.objective_confirmation_digest is None:
        raise ExperimentValidationError(
            "live execution requires a real objective_confirmation_digest"
        )
    if (
        objective.objective_confirmation_digest
        != authorization.objective_confirmation_digest
    ):
        raise ExperimentValidationError("objective authorization digest mismatch")
    journal, confirmed = _verify_journal_objective(
        objective, authorization.journal_path
    )
    binding = journal.experiment_status(authorization.experiment_id)
    if binding is None:
        raise ExperimentValidationError("live experiment has no journal binding")
    expected = {
        "objective_confirmation_digest": authorization.objective_confirmation_digest,
        "experiment_digest": authorization.experiment_digest,
        "approval_digest": authorization.approval_digest,
        "task_card_digest": authorization.task_card_digest,
    }
    for field, value in expected.items():
        if binding.get(field) != value:
            raise ExperimentValidationError(f"live binding {field} mismatch")
    if binding.get("status") not in {"LAUNCHING", "LAUNCHED"}:
        raise ExperimentValidationError(
            "live execution requires a HarnessAdapter binding in LAUNCHING or LAUNCHED state"
        )
    task_path = Path(str(binding["task_card_path"])).expanduser().resolve()
    if not task_path.is_file() or _sha256(task_path.read_bytes()) != authorization.task_card_digest:
        raise ExperimentValidationError("authorized task-card bytes are missing or changed")
    approval = journal.get(authorization.approval_digest)
    if (
        approval is None
        or approval.get("schema") != "human-approval/v1"
        or approval.get("approved") is not True
        or approval.get("experiment_id") != authorization.experiment_id
        or approval.get("experiment_digest") != authorization.experiment_digest
        or approval.get("objective_confirmation_digest")
        != authorization.objective_confirmation_digest
    ):
        raise ExperimentValidationError("live approval record does not match authority")
    question_id = confirmed.get("question_id")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ExperimentValidationError("objective authorization has no question linkage")
    chain = journal.reconstruct_chain(question_id)
    feasibility_records = [
        record
        for record in chain.get("records", [])
        if record.get("schema") == "feasibility-check/v1"
        and record.get("objective_confirmation_digest")
        == authorization.objective_confirmation_digest
    ]
    if not any(
        record.get("overall_status") == "PASS"
        and all(
            isinstance(record.get("checks", {}).get(name), Mapping)
            and record["checks"][name].get("status") == "PASS"
            and isinstance(record["checks"][name].get("evidence"), str)
            and record["checks"][name]["evidence"].strip()
            for name in ("license", "privacy")
        )
        for record in feasibility_records
    ):
        raise ExperimentValidationError(
            "live execution requires journaled PASS license and privacy attestations"
        )
    portfolios = [
        record
        for record in chain.get("records", [])
        if record.get("schema") == "experiment-candidates/v1"
        and record.get("objective_confirmation_digest")
        == authorization.objective_confirmation_digest
        and record.get("selected_experiment_id") == authorization.experiment_id
    ]
    portfolios = [
        record
        for record in portfolios
        if approved_experiment_digest(record) == authorization.experiment_digest
    ]
    if len(portfolios) != 1:
        raise ExperimentValidationError(
            "live execution requires exactly one approved candidate portfolio"
        )
    plan = _approved_plan_from_portfolio(portfolios[0], objective)
    authority = {
        "question_id": question_id,
        "experiment_id": authorization.experiment_id,
        **expected,
    }
    return authority, plan


@dataclass(frozen=True)
class ExperimentConfig:
    """Preregistered endpoints and hard resource limits."""

    threshold: float = 0.90
    split_seed: int = 1729
    max_trials_per_arm: int = 4
    max_seconds_per_arm: float = 30.0
    estimated_cost_usd: float = 0.0
    quality_noninferiority_margin: float = 0.02
    threshold_was_preregistered: bool = True

    def __post_init__(self) -> None:
        if not 0.0 < self.threshold <= 1.0:
            raise ExperimentValidationError("threshold must be in (0, 1]")
        if not isinstance(self.split_seed, int):
            raise ExperimentValidationError("split_seed must be an integer")
        if not 1 <= self.max_trials_per_arm <= MAX_TRIALS_PER_ARM:
            raise ExperimentValidationError(
                f"trial budget exceeds hard cap {MAX_TRIALS_PER_ARM}"
            )
        if not 0.0 < self.max_seconds_per_arm <= MAX_SECONDS_PER_ARM:
            raise ExperimentValidationError(
                f"time budget exceeds hard cap {MAX_SECONDS_PER_ARM:g} seconds"
            )
        if not 0.0 <= self.quality_noninferiority_margin <= 1.0:
            raise ExperimentValidationError(
                "quality_noninferiority_margin must be in [0, 1]"
            )
        if (
            isinstance(self.estimated_cost_usd, bool)
            or not isinstance(self.estimated_cost_usd, (int, float))
            or not math.isfinite(self.estimated_cost_usd)
            or self.estimated_cost_usd < 0
        ):
            raise ExperimentValidationError(
                "estimated_cost_usd must be finite and non-negative"
            )


@dataclass(frozen=True)
class PreflightReport:
    schema: str
    objective: dict[str, Any]
    dataset: dict[str, Any]
    resource_estimate: dict[str, Any]
    checks: dict[str, str]
    preflight_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_feasibility_check(
        self,
        *,
        feasibility_check_id: str,
        question_id: str,
        checked_by: str,
        checked_at: str,
        fallback: str,
        journal_path: str | Path,
    ) -> dict[str, Any]:
        """Translate the passed gate into the feasibility-check/v1 contract."""

        values = {
            "feasibility_check_id": feasibility_check_id,
            "question_id": question_id,
            "checked_by": checked_by,
            "checked_at": checked_at,
            "fallback": fallback,
        }
        for field, value in values.items():
            if not value.strip():
                raise ExperimentValidationError(f"{field} is required")
        objective_digest = _required_objective_digest(self.objective)
        journal_objective = ResearchJournal(journal_path).get(objective_digest)
        if (
            journal_objective is None
            or journal_objective.get("schema") != "objective-confirmation/v1"
            or journal_objective.get("question_id") != question_id
            or journal_objective.get("primary_metric")
            != self.objective["primary_metric"]
            or not isinstance(journal_objective.get("dataset"), Mapping)
            or _dataset_identity(journal_objective["dataset"])
            != _dataset_identity(self.dataset)
        ):
            raise ExperimentValidationError(
                "feasibility output requires an exact journal objective record"
            )
        dataset_label = (
            f"task={self.dataset['openml_task_id']} "
            f"dataset_sha256={self.dataset['sha256']}"
        )
        license_value = self.dataset.get("license_spdx") or self.dataset.get(
            "license_declared_by_openml"
        )
        governance = self.objective["data_governance"]
        checks = {
            "access": {"status": "PASS", "evidence": f"Loaded {dataset_label}."},
            "identity": {
                "status": "PASS",
                "evidence": (
                    f"Pinned task, version, content, and split; "
                    f"split_sha256={self.dataset['split_digest']}."
                ),
            },
            "license": {
                "status": "PASS",
                "evidence": (
                    f"Verified license/access status {license_value}: "
                    f"{governance['license_evidence']}"
                ),
            },
            "privacy": {
                "status": "PASS",
                "evidence": governance["privacy_evidence"],
            },
            "api": {
                "status": "PASS",
                "evidence": "Source is available without credentials or secret persistence.",
            },
            "compute": {
                "status": "PASS",
                "evidence": (
                    f"CPU-only bounds: <= {self.resource_estimate['maximum_trials']} "
                    f"total trials and <= "
                    f"{self.resource_estimate['maximum_runtime_seconds']} seconds."
                ),
            },
        }
        return {
            "schema": "feasibility-check/v1",
            **values,
            "objective_confirmation_digest": objective_digest,
            "checks": checks,
            "overall_status": "PASS",
        }


@dataclass(frozen=True)
class Endpoint:
    value: int | float | None
    censored: bool
    lower_bound_exclusive: int | float | None
    censoring_reason: str | None


@dataclass(frozen=True)
class TrialResult:
    ordinal: int
    candidate_id: str
    status: str
    metric: float | None
    elapsed_seconds: float
    compute_seconds: float | None
    error: str | None = None


@dataclass(frozen=True)
class ArmResult:
    arm: str
    policy: str
    trials: tuple[TrialResult, ...]
    attempted_trials: int
    failed_trials: int
    best_metric: float | None
    trials_to_threshold: Endpoint
    seconds_to_threshold: Endpoint
    elapsed_seconds: float
    compute_seconds: float | None
    compute_seconds_to_threshold: float | None
    external_overhead_seconds: float
    overhead_included: bool
    human_interventions: int | None
    cost_usd: float | None
    token_usage: int | None
    measurement_source_digest: str | None
    stop_reason: str
    control_digest: str
    candidate_set_digest: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trials"] = [asdict(trial) for trial in self.trials]
        payload["measurement_availability"] = {
            "workflow_overhead": (
                "MEASURED" if self.overhead_included else "UNAVAILABLE"
            ),
            "compute_seconds": (
                "MEASURED" if self.compute_seconds is not None else "UNAVAILABLE"
            ),
            "human_interventions": (
                "MEASURED" if self.human_interventions is not None else "UNAVAILABLE"
            ),
            "cost_usd": "MEASURED" if self.cost_usd is not None else "UNAVAILABLE",
            "token_usage": (
                "MEASURED" if self.token_usage is not None else "UNAVAILABLE"
            ),
        }
        return payload


@dataclass(frozen=True)
class ExperimentOutcome:
    preflight: PreflightReport
    preregistration: dict[str, Any]
    approved_candidate_parameters: dict[str, Any] | None
    baseline: ArmResult
    guided: ArmResult
    acceleration: dict[str, Any]
    scaling_analysis: dict[str, Any]
    identities: dict[str, Any]
    artifacts: tuple[dict[str, Any], ...]
    started_at: str
    completed_at: str
    execution_mode: str
    limitations: tuple[str, ...]
    verified_authority: dict[str, str] | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "matched-classifier-experiment/v1",
            "preflight": self.preflight.to_dict(),
            "preregistration": self.preregistration,
            "approved_candidate_parameters": self.approved_candidate_parameters,
            "arms": {
                "baseline": self.baseline.to_dict(),
                "evidence_guided": self.guided.to_dict(),
            },
            "acceleration": self.acceleration,
            "scaling_analysis": self.scaling_analysis,
            "identities": self.identities,
            "artifacts": list(self.artifacts),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "execution_mode": self.execution_mode,
            "execution_status": _experiment_result_status(
                self.baseline, self.guided
            ),
            "verified_authority": self.verified_authority,
            "limitations": list(self.limitations),
        }
        payload["result_digest"] = _digest(payload)
        return payload

    def as_experiment_result(
        self,
        *,
        question_id: str,
        experiment_id: str,
        run_id: str,
        experiment_digest: str,
        approval_digest: str,
        task_card_digest: str,
    ) -> dict[str, Any]:
        """Translate execution measurements before independent interpretation.

        Decision latency is deliberately absent.  It does not exist until this
        immutable result has passed Harness review and an independent analyst
        has completed ``updated-decision/v1``.
        """

        for field, value in (
            ("question_id", question_id),
            ("experiment_id", experiment_id),
            ("run_id", run_id),
            ("experiment_digest", experiment_digest),
            ("approval_digest", approval_digest),
            ("task_card_digest", task_card_digest),
        ):
            if not value.strip():
                raise ExperimentValidationError(f"{field} is required")
        if self.verified_authority is None:
            raise ExperimentValidationError(
                "integration-ready experiment-result requires journal-verified authority"
            )
        if self.approved_candidate_parameters is None:
            raise ExperimentValidationError(
                "integration-ready experiment-result requires exact approved candidate parameters"
            )
        supplied = {
            "question_id": question_id,
            "experiment_id": experiment_id,
            "experiment_digest": experiment_digest,
            "approval_digest": approval_digest,
            "task_card_digest": task_card_digest,
        }
        for field, value in supplied.items():
            if self.verified_authority.get(field) != value:
                raise ExperimentValidationError(
                    f"experiment-result {field} does not match verified authority"
                )
        artifact_refs = [
            {
                "uri": f"artifact:{artifact['name']}",
                "kind": artifact["kind"],
                "digest": artifact["sha256"],
            }
            for artifact in self.artifacts
        ]
        summary_digest = next(
            artifact["sha256"]
            for artifact in self.artifacts
            if artifact["kind"] == "matched-result-summary"
        )
        primary_metric = self.preregistration["primary_metric"]
        metrics = {
            primary_metric: {
                "baseline": asdict(self.baseline.trials_to_threshold),
                "proposed": asdict(self.guided.trials_to_threshold),
            },
            QUALITY_METRIC: {
                "baseline": self.baseline.best_metric,
                "proposed": self.guided.best_metric,
            },
            "primary_metric_metadata": {
                "name": primary_metric,
                "proposed_value": self.guided.trials_to_threshold.value,
                "baseline_value": self.baseline.trials_to_threshold.value,
                "higher_is_better": False,
            },
            "threshold": self.preregistration["threshold"],
            "elapsed_to_threshold_seconds": {
                "baseline": self.baseline.seconds_to_threshold.value,
                "proposed": self.guided.seconds_to_threshold.value,
            },
            "total_elapsed_seconds": {
                "baseline": self.baseline.elapsed_seconds,
                "proposed": self.guided.elapsed_seconds,
            },
            "compute_seconds": {
                "baseline": self.baseline.compute_seconds,
                "proposed": self.guided.compute_seconds,
            },
            "interventions": {
                "baseline": self.baseline.human_interventions,
                "proposed": self.guided.human_interventions,
            },
            "cost_usd": {
                "baseline": self.baseline.cost_usd,
                "proposed": self.guided.cost_usd,
            },
            "token_usage": {
                "baseline": self.baseline.token_usage,
                "proposed": self.guided.token_usage,
            },
            "baseline": _arm_metrics(self.baseline),
            "evidence_guided": _arm_metrics(self.guided),
            "acceleration": self.acceleration,
            "scaling_analysis": self.scaling_analysis,
        }
        return {
            "schema": "experiment-result/v1",
            "run_id": run_id,
            "question_id": question_id,
            "experiment_id": experiment_id,
            "objective_confirmation_digest": _required_objective_digest(
                self.preflight.objective
            ),
            "execution_source": f"ai_researcher.experiment:{self.execution_mode}",
            "experiment_digest": experiment_digest,
            "approval_digest": approval_digest,
            "task_card_digest": task_card_digest,
            "primary_metric": self.preregistration["primary_metric"],
            "code_identity": self.identities["code"]["sha256"],
            "dataset_identity": _dataset_identity(self.preflight.dataset),
            "environment_identity": self.identities["environment"]["digest"],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": _experiment_result_status(self.baseline, self.guided),
            "metrics": metrics,
            "parameters": {
                "approved_candidate_parameters": self.approved_candidate_parameters,
                "observed_preregistration": self.preregistration,
                "execution_metadata": {
                    "preflight_digest": self.preflight.preflight_digest,
                    "objective_confirmation_digest": self.preflight.objective[
                        "objective_confirmation_digest"
                    ],
                    "dataset_identity": _dataset_identity(self.preflight.dataset),
                    "authority": {
                        "experiment_digest": experiment_digest,
                        "approval_digest": approval_digest,
                        "task_card_digest": task_card_digest,
                    },
                    "measurement_availability": {
                        "baseline": self.baseline.to_dict()[
                            "measurement_availability"
                        ],
                        "proposed": self.guided.to_dict()[
                            "measurement_availability"
                        ],
                    },
                },
            },
            "random_seeds": [self.preregistration["split_seed"]],
            "artifact_refs": artifact_refs,
            "measurement_support": {
                metric: summary_digest for metric in metrics
            },
            "limitations": list(self.limitations),
        }

    def as_acceleration_summary(
        self,
        *,
        acceleration_summary_id: str,
        question_id: str,
        experiment_id: str,
        result_digest: str,
        updated_decision: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the post-decision acceleration record.

        Latency is never accepted as a caller-authored scalar.  It is read from
        the validated, immutable updated-decision record whose embedded timing
        artifact binds the Harness acceptance boundary to decision completion.
        """

        for field, value in (
            ("acceleration_summary_id", acceleration_summary_id),
            ("question_id", question_id),
            ("experiment_id", experiment_id),
            ("result_digest", result_digest),
        ):
            if not value.strip():
                raise ExperimentValidationError(f"{field} is required")
        if self.verified_authority is None:
            raise ExperimentValidationError(
                "integration-ready acceleration summary requires journal-verified authority"
            )
        try:
            decision = validate_record(updated_decision, "updated-decision/v1")
        except (TypeError, ValueError) as exc:
            raise ExperimentValidationError(
                f"updated_decision is not a valid immutable decision: {exc}"
            ) from exc
        if (
            decision["question_id"] != question_id
            or decision["experiment_id"] != experiment_id
            or decision["result_digest"] != result_digest
            or decision["objective_confirmation_digest"]
            != _required_objective_digest(self.preflight.objective)
        ):
            raise ExperimentValidationError(
                "updated_decision does not bind the exact objective, result, and experiment"
            )
        timing = decision["decision_timing"]
        decision_latency_seconds = timing["latency_seconds"]
        decision_timing_source_digest = decision["decision_timing_source_digest"]
        if (
            self.verified_authority.get("question_id") != question_id
            or self.verified_authority.get("experiment_id") != experiment_id
        ):
            raise ExperimentValidationError(
                "acceleration summary does not match verified question/experiment authority"
            )
        if not self.acceleration["matched_controls"]:
            raise ExperimentValidationError(
                "acceleration-summary/v1 requires matched controls"
            )
        if not self.preregistration["threshold_was_preregistered"]:
            raise ExperimentValidationError(
                "acceleration-summary/v1 requires a predeclared threshold"
            )
        outcome = "NOT_ESTIMABLE"
        if self.guided.trials_to_threshold.censored:
            outcome = "NOT_ESTIMABLE"
        elif self.baseline.trials_to_threshold.censored:
            outcome = "LOWER_BOUND_ONLY"
        elif (
            not self.acceleration["quality_non_inferiority"]["passed"]
            or self.acceleration["trial_speedup"] is None
            or self.acceleration["trial_speedup"] <= 1
        ):
            outcome = "NO_IMPROVEMENT"
        elif (
            self.acceleration["time_speedup"] is not None
            and self.acceleration["time_speedup"] > 1
            and self.acceleration["overhead_included"]
            and self.baseline.compute_seconds is not None
            and self.guided.compute_seconds is not None
        ):
            outcome = "POSITIVE"
        else:
            outcome = "TRIAL_EFFICIENCY_ONLY"
        scenario_records = {
            scenario["scenario"]: {
                "assumptions": [
                    f"fixed_fraction={scenario['fixed_fraction']}",
                    f"serial_fraction={scenario['serial_fraction']}",
                    f"parallel_fraction={scenario['parallel_fraction']}",
                    f"parallel_workers={scenario['parallel_workers']}",
                ],
                "projected_speedup": scenario["projected_speedup"],
                "boundaries": [
                    "Forecast only; not an observed experimental result.",
                    "Requires no loss of scientific quality or safety.",
                ],
            }
            for scenario in self.scaling_analysis["scenarios"]
        }
        return {
            "schema": "acceleration-summary/v1",
            "acceleration_summary_id": acceleration_summary_id,
            "question_id": question_id,
            "objective_confirmation_digest": _required_objective_digest(
                self.preflight.objective
            ),
            "experiment_id": experiment_id,
            "result_digest": result_digest,
            "updated_decision_digest": decision["record_digest"],
            "primary_metric": self.preregistration["primary_metric"],
            "dataset_identity": _dataset_identity(self.preflight.dataset),
            "threshold_predeclared": self.preregistration[
                "threshold_was_preregistered"
            ],
            "matched_conditions": self.acceleration["matched_controls"],
            "overhead_included": self.acceleration["overhead_included"],
            "timing_scope": self.acceleration["timing_scope"],
            "overall_discovery_speed_claim": self.acceleration[
                "overall_discovery_speed_claim"
            ],
            "arms": {
                "baseline": _acceleration_arm(self.baseline, self.preregistration),
                "proposed": _acceleration_arm(self.guided, self.preregistration),
            },
            "trial_count_rule": self.preregistration["endpoint_rules"]["attempt"],
            "formula": "baseline_trials_to_threshold / proposed_trials_to_threshold",
            "outcome": outcome,
            "observed_trial_speedup": self.acceleration["trial_speedup"],
            "observed_time_speedup": self.acceleration["time_speedup"],
            "decision_latency_seconds": decision_latency_seconds,
            "decision_timing_source_digest": decision_timing_source_digest,
            "trial_speedup_lower_bound": self.acceleration[
                "trial_speedup_lower_bound"
            ],
            "quality_non_inferiority": self.acceleration[
                "quality_non_inferiority"
            ],
            "claim_blockers": self.acceleration["claim_blockers"],
            "matched_controls_digest": self.baseline.control_digest,
            "endpoint_rules": self.preregistration["endpoint_rules"],
            "threats_to_validity": list(self.limitations),
            "scaling_analysis": {
                "remaining_bottlenecks": self.scaling_analysis[
                    "remaining_bottlenecks"
                ],
                "parallelizable_or_automatable": self.scaling_analysis[
                    "parallelizable_or_automatable"
                ],
                "evidence_still_needed": self.scaling_analysis[
                    "evidence_still_needed"
                ],
                "conditions_for_approaching_10x": self.scaling_analysis[
                    "conditions_for_10x"
                ],
                "boundaries": [
                    "Scaling values are Amdahl-style sensitivity forecasts, not measurements.",
                    "Human objective ownership and consequential approval remain serial gates.",
                ],
                "scenarios": scenario_records,
            },
        }

@dataclass(frozen=True)
class _Dataset:
    features: tuple[tuple[float, ...], ...]
    labels: tuple[str, ...]
    feature_names: tuple[str, ...]
    raw_sha256: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _Candidate:
    candidate_id: str
    feature_indices: tuple[int, ...]
    neighbors: int
    evidence_priority: int
    evidence_rationale: str
    evidence_references: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _ApprovedPlan:
    config: ExperimentConfig
    candidates: tuple[_Candidate, ...]
    baseline_order: tuple[str, ...]
    guided_order: tuple[str, ...]
    primary_metric: str
    dataset_identity: dict[str, str]
    approved_candidate_parameters: dict[str, Any]


def _approved_plan_from_portfolio(
    portfolio: Mapping[str, Any], objective: HumanObjective
) -> _ApprovedPlan:
    selected = next(
        candidate
        for candidate in portfolio["candidates"]
        if candidate["experiment_id"] == portfolio["selected_experiment_id"]
    )
    parameters = selected.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ExperimentValidationError("approved candidate parameters are missing")
    try:
        raw_candidates = parameters["search_candidates"]
        baseline_order = tuple(parameters["baseline_order"])
        guided_order = tuple(parameters["evidence_guided_order"])
        split_seed = parameters["split_seed"]
        threshold = parameters["threshold"]
        max_trials = parameters["max_trials_per_arm"]
        max_seconds = parameters["max_seconds_per_arm"]
        margin = parameters["quality_noninferiority_margin"]
    except (KeyError, TypeError) as exc:
        raise ExperimentValidationError(
            "approved candidate lacks exact search/split/threshold/resource parameters"
        ) from exc
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ExperimentValidationError("approved search_candidates must be non-empty")
    candidates: list[_Candidate] = []
    for index, item in enumerate(raw_candidates, start=1):
        if not isinstance(item, Mapping):
            raise ExperimentValidationError("approved search candidate must be an object")
        references = item.get("evidence_references")
        indices = item.get("feature_indices")
        if (
            not isinstance(references, list)
            or not references
            or any(not isinstance(value, str) or not value.strip() for value in references)
            or not isinstance(indices, list)
            or not indices
            or any(isinstance(value, bool) or not isinstance(value, int) for value in indices)
        ):
            raise ExperimentValidationError(
                "every approved search candidate needs feature indices and evidence references"
            )
        candidates.append(
            _Candidate(
                candidate_id=str(item["candidate_id"]),
                feature_indices=tuple(indices),
                neighbors=int(item["neighbors"]),
                evidence_priority=index,
                evidence_rationale=str(item["evidence_rationale"]),
                evidence_references=tuple(references),
            )
        )
    identifiers = tuple(candidate.candidate_id for candidate in candidates)
    if (
        len(set(identifiers)) != len(identifiers)
        or set(baseline_order) != set(identifiers)
        or set(guided_order) != set(identifiers)
        or len(baseline_order) != len(identifiers)
        or len(guided_order) != len(identifiers)
    ):
        raise ExperimentValidationError(
            "approved baseline/guided ordering must cover the exact candidate set"
        )
    selected_metrics = selected.get("metrics", [])
    if portfolio.get("primary_metric") != objective.primary_metric or (
        objective.primary_metric not in selected_metrics
        or objective.quality_metric not in selected_metrics
    ):
        raise ExperimentValidationError("approved primary metric does not match objective")
    dataset_identity = portfolio.get("dataset_identity")
    expected_dataset = {
        "identifier": objective.dataset_identifier,
        "version": str(objective.openml_dataset_version),
        "digest": objective.dataset_digest,
    }
    if dataset_identity != expected_dataset:
        raise ExperimentValidationError("approved dataset identity does not match objective")
    if split_seed not in selected.get("random_seeds", []):
        raise ExperimentValidationError("approved split seed is not in random_seeds")
    config = ExperimentConfig(
        threshold=threshold,
        split_seed=split_seed,
        max_trials_per_arm=max_trials,
        max_seconds_per_arm=max_seconds,
        estimated_cost_usd=selected["estimated_cost_usd"],
        quality_noninferiority_margin=margin,
        threshold_was_preregistered=True,
    )
    bounds = portfolio["resource_bounds"]
    if (
        config.max_trials_per_arm * 2 > bounds["max_trials"]
        or config.max_seconds_per_arm * 2 > bounds["max_runtime_minutes"] * 60
        or config.estimated_cost_usd > bounds["max_cost_usd"]
    ):
        raise ExperimentValidationError("approved parameters exceed portfolio bounds")
    return _ApprovedPlan(
        config=config,
        candidates=tuple(candidates),
        baseline_order=baseline_order,
        guided_order=guided_order,
        primary_metric=objective.primary_metric,
        dataset_identity=expected_dataset,
        approved_candidate_parameters=json.loads(
            _canonical_bytes(parameters).decode("utf-8")
        ),
    )


def preflight(
    objective: HumanObjective,
    *,
    fixture_dir: str | Path = DEFAULT_FIXTURE_DIR,
    live: bool = False,
    config: ExperimentConfig | None = None,
    network_timeout_seconds: float = 20.0,
    journal_path: str | Path | None = None,
) -> PreflightReport:
    """Run the objective, access, license, privacy, API, identity, and compute gate."""

    config = config or ExperimentConfig()
    _enforce_scope(
        objective,
        config,
        live=live,
        network_timeout_seconds=network_timeout_seconds,
    )
    _verify_governance(objective)
    if live:
        _verify_journal_objective(objective, journal_path)
    dataset = _load_dataset(
        fixture_dir=Path(fixture_dir),
        live=live,
        network_timeout_seconds=network_timeout_seconds,
    )
    return _make_preflight(objective, dataset, live=live, config=config)


def _make_preflight(
    objective: HumanObjective,
    dataset: _Dataset,
    *,
    live: bool,
    config: ExperimentConfig,
) -> PreflightReport:
    if dataset.raw_sha256 != objective.dataset_digest:
        raise ExperimentValidationError(
            "loaded dataset digest does not match the human-confirmed dataset"
        )
    if (
        dataset.metadata.get("openml_task_id") != objective.openml_task_id
        or dataset.metadata.get("openml_dataset_id") != objective.openml_dataset_id
        or dataset.metadata.get("openml_dataset_version")
        != objective.openml_dataset_version
    ):
        raise ExperimentValidationError(
            "loaded dataset identifiers do not match the human-confirmed dataset"
        )
    train_indices, test_indices = _stratified_split(
        dataset.labels, config.split_seed
    )
    split_payload = {
        "algorithm": "deterministic-stratified-75-25/v1",
        "seed": config.split_seed,
        "train_indices": train_indices,
        "test_indices": test_indices,
    }
    dataset_identity = dict(dataset.metadata)
    dataset_identity.update(
        {
            "sha256": dataset.raw_sha256,
            "identifier": objective.dataset_identifier,
            "version": str(objective.openml_dataset_version),
            "digest": dataset.raw_sha256,
            "row_count": len(dataset.labels),
            "feature_count": len(dataset.feature_names),
            "feature_names": list(dataset.feature_names),
            "target": OPENML_TARGET,
            "split_digest": _digest(split_payload),
            "split": split_payload,
        }
    )
    resource_estimate = {
        "download_bytes": 0 if not live else dataset.metadata.get("byte_count"),
        "rows": len(dataset.labels),
        "features": len(dataset.feature_names),
        "cpu_only": True,
        "gpu_required": False,
        "maximum_trials": config.max_trials_per_arm * 2,
        "maximum_runtime_seconds": config.max_seconds_per_arm * 2,
        "estimated_cost_usd": config.estimated_cost_usd,
    }
    checks = {
        "objective_confirmation": (
            "PASS"
            if objective.objective_confirmation_digest is not None
            else "UNBOUND_FIXTURE"
        ),
        "access": "PASS",
        "identity": "PASS",
        "license": "PASS",
        "privacy": "PASS",
        "api": "PASS",
        "compute": "PASS",
    }
    unsigned = {
        "schema": "experiment-preflight/v1",
        "objective": objective.to_dict(),
        "dataset": dataset_identity,
        "resource_estimate": resource_estimate,
        "checks": checks,
    }
    return PreflightReport(
        schema="experiment-preflight/v1",
        objective=objective.to_dict(),
        dataset=dataset_identity,
        resource_estimate=resource_estimate,
        checks=checks,
        preflight_digest=_digest(unsigned),
    )


def run_matched_experiment(
    objective: HumanObjective,
    *,
    artifact_dir: str | Path,
    config: ExperimentConfig | None = None,
    fixture_dir: str | Path = DEFAULT_FIXTURE_DIR,
    live: bool = False,
    network_timeout_seconds: float = 20.0,
    authorization: ExecutionAuthorization | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
    process_clock: Callable[[], float] = time.process_time,
    arm_measurements: Mapping[
        str, ArmWorkflowMeasurements | Mapping[str, Any]
    ] | None = None,
) -> ExperimentOutcome:
    """Run both preregistered arms and return an integration-ready result."""

    _verify_governance(objective)
    verified_authority: dict[str, str] | None = None
    approved_plan: _ApprovedPlan | None = None
    if live:
        verified_authority, approved_plan = _verify_live_authorization(
            objective, authorization
        )
        if config is not None and config != approved_plan.config:
            raise ExperimentValidationError(
                "caller config overrides the exact approved experiment parameters"
            )
        config = approved_plan.config
    elif authorization is not None:
        raise ExperimentValidationError(
            "execution authorization is not accepted in fixture mode"
        )
    else:
        config = config or ExperimentConfig()
    _enforce_scope(
        objective,
        config,
        live=live,
        network_timeout_seconds=network_timeout_seconds,
    )
    started_at = _utc_now()
    dataset = _load_dataset(
        fixture_dir=Path(fixture_dir),
        live=live,
        network_timeout_seconds=network_timeout_seconds,
    )
    report = _make_preflight(objective, dataset, live=live, config=config)
    train_indices = report.dataset["split"]["train_indices"]
    test_indices = report.dataset["split"]["test_indices"]
    candidates = (
        approved_plan.candidates
        if approved_plan is not None
        else _candidate_pool(len(dataset.feature_names))
    )
    candidate_set_digest = _digest(
        sorted(
            (candidate.to_dict() for candidate in candidates),
            key=lambda item: item["candidate_id"],
        )
    )
    control_payload = {
        "dataset_identity": _dataset_identity(report.dataset),
        "split_digest": report.dataset["split_digest"],
        "split_seed": config.split_seed,
        "primary_metric": objective.primary_metric,
        "quality_metric": objective.quality_metric,
        "threshold": config.threshold,
        "trial_budget": config.max_trials_per_arm,
        "seconds_budget": config.max_seconds_per_arm,
        "estimated_cost_usd": config.estimated_cost_usd,
        "candidate_set_digest": candidate_set_digest,
        "evaluator": "standardized-knn/v1",
    }
    control_digest = _digest(control_payload)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    if approved_plan is not None:
        baseline_order = [by_id[identifier] for identifier in approved_plan.baseline_order]
        guided_order = [by_id[identifier] for identifier in approved_plan.guided_order]
    else:
        baseline_order = list(candidates)
        guided_order = sorted(
            candidates,
            key=lambda candidate: (
                candidate.evidence_priority,
                candidate.candidate_id,
            ),
        )
    preregistration: dict[str, Any] = {
        "schema": "matched-classifier-preregistration/v1",
        "preflight_digest": report.preflight_digest,
        "objective_confirmation_digest": report.objective[
            "objective_confirmation_digest"
        ],
        "primary_metric": objective.primary_metric,
        "quality_metric": objective.quality_metric,
        "dataset_identity": _dataset_identity(report.dataset),
        "threshold": config.threshold,
        "threshold_was_preregistered": config.threshold_was_preregistered,
        "split_seed": config.split_seed,
        "split_digest": report.dataset["split_digest"],
        "max_trials_per_arm": config.max_trials_per_arm,
        "max_seconds_per_arm": config.max_seconds_per_arm,
        "estimated_cost_usd": config.estimated_cost_usd,
        "quality_noninferiority_margin": config.quality_noninferiority_margin,
        "candidate_set_digest": candidate_set_digest,
        "control_digest": control_digest,
        "baseline_order": [candidate.candidate_id for candidate in baseline_order],
        "evidence_guided_order": [candidate.candidate_id for candidate in guided_order],
        "evidence_guided_rationales": {
            candidate.candidate_id: candidate.evidence_rationale
            for candidate in guided_order
        },
        "endpoint_rules": _endpoint_rules(),
    }
    preregistration["digest"] = _digest(preregistration)

    measured_arms = _normalize_arm_measurements(arm_measurements)
    observed_costs = [
        measurement.cost_usd
        for measurement in measured_arms.values()
        if measurement.cost_usd is not None
    ]
    if observed_costs and sum(observed_costs) > objective.execution_scope.max_cost_usd:
        raise ExperimentValidationError(
            "measured cost exceeds human-confirmed execution_scope.max_cost_usd"
        )
    baseline = _run_arm(
        "baseline",
        "fixed preregistered order; no validation feedback changes the order",
        baseline_order,
        dataset,
        train_indices,
        test_indices,
        config,
        control_digest,
        candidate_set_digest,
        monotonic,
        process_clock,
        measured_arms.get("baseline"),
    )
    guided = _run_arm(
        "evidence_guided",
        "preregistered domain-evidence priority; no validation feedback changes the order",
        guided_order,
        dataset,
        train_indices,
        test_indices,
        config,
        control_digest,
        candidate_set_digest,
        monotonic,
        process_clock,
        measured_arms.get("evidence_guided"),
    )
    acceleration = calculate_acceleration(
        baseline,
        guided,
        quality_noninferiority_margin=config.quality_noninferiority_margin,
        threshold_was_preregistered=config.threshold_was_preregistered,
    )
    scaling_analysis = _scaling_analysis()
    identities = _runtime_identities()
    target_dir = Path(artifact_dir).expanduser().resolve()
    artifacts = (
        _write_artifact(
            target_dir, "baseline-trials.json", baseline.to_dict(), kind="trial-log"
        ),
        _write_artifact(
            target_dir,
            "evidence-guided-trials.json",
            guided.to_dict(),
            kind="trial-log",
        ),
        _write_artifact(
            target_dir,
            "matched-result-summary.json",
            {
                "preregistration": preregistration,
                "approved_candidate_parameters": (
                    approved_plan.approved_candidate_parameters
                    if approved_plan is not None
                    else None
                ),
                "baseline": baseline.to_dict(),
                "evidence_guided": guided.to_dict(),
                "acceleration": acceleration,
                "scaling_analysis": scaling_analysis,
                "identities": identities,
            },
            kind="matched-result-summary",
        ),
    )
    limitations = [
        "One small task cannot establish general superiority or a causal effect "
        "of evidence guidance.",
        "The live runner pins the OpenML task's dataset and target but uses its own "
        "preregistered holdout split, not OpenML task 59's official ten-fold protocol.",
        "Wall-clock measurements on short local trials are sensitive to host scheduling noise.",
        "The evidence-guided ordering is a preregistered heuristic, not a learned policy.",
        "Repeated seeds, multiple tasks, uncertainty intervals, and prospective "
        "domain validation remain required.",
    ]
    if not acceleration["overhead_included"]:
        limitations.insert(
            3,
            "External retrieval, planning, approval, preflight, and agent/tool "
            "timings were unavailable; the measured time covers model evaluation "
            "and result ingestion only and cannot support an overall discovery-speed claim.",
        )
    if not live:
        limitations.insert(
            0,
            "The hermetic CC0 fixture is synthetic and tests-only; its scores are "
            "not evidence about OpenML task 59.",
        )
    return ExperimentOutcome(
        preflight=report,
        preregistration=preregistration,
        approved_candidate_parameters=(
            approved_plan.approved_candidate_parameters
            if approved_plan is not None
            else None
        ),
        baseline=baseline,
        guided=guided,
        acceleration=acceleration,
        scaling_analysis=scaling_analysis,
        identities=identities,
        artifacts=artifacts,
        started_at=started_at,
        completed_at=_utc_now(),
        execution_mode="openml-live" if live else "hermetic-fixture",
        limitations=tuple(limitations),
        verified_authority=verified_authority,
    )


def calculate_acceleration(
    baseline: ArmResult,
    guided: ArmResult,
    *,
    quality_noninferiority_margin: float,
    threshold_was_preregistered: bool,
) -> dict[str, Any]:
    """Apply censoring and no-inflation rules to matched arm results."""

    matched = (
        baseline.control_digest == guided.control_digest
        and baseline.candidate_set_digest == guided.candidate_set_digest
    )
    quality_estimable = (
        baseline.best_metric is not None and guided.best_metric is not None
    )
    quality_ok = bool(
        quality_estimable
        and guided.best_metric is not None
        and baseline.best_metric is not None
        and guided.best_metric + quality_noninferiority_margin >= baseline.best_metric
    )
    b_trials = baseline.trials_to_threshold
    g_trials = guided.trials_to_threshold
    b_time = baseline.seconds_to_threshold
    g_time = guided.seconds_to_threshold
    overhead_included = baseline.overhead_included and guided.overhead_included
    result: dict[str, Any] = {
        "kind": "observed",
        "status": "NOT_ESTIMABLE",
        "trial_speedup": None,
        "time_speedup": None,
        "trial_speedup_lower_bound": None,
        "trial_speedup_lower_bound_exclusive": None,
        "positive_acceleration_claim": False,
        "overall_discovery_speed_claim": False,
        "claim": "NO_POSITIVE_CLAIM",
        "claim_blockers": [],
        "validity_failures": [],
        "matched_controls": matched,
        "quality_noninferiority_passed": quality_ok,
        "quality_non_inferiority": {
            "margin": quality_noninferiority_margin,
            "higher_is_better": True,
            "estimable": quality_estimable,
            "passed": quality_ok,
        },
        "threshold_was_preregistered": threshold_was_preregistered,
        "timing_scope": (
            "end-to-end-arm-workflow"
            if overhead_included
            else "model-evaluation-only"
        ),
        "overhead_included": overhead_included,
        "timing_boundary": (
            "Includes measured retrieval, planning, approval, preflight, agent/tool "
            "overhead, candidate computation, metric acceptance, and result ingestion "
            "through the threshold event for both arms."
            if overhead_included
            else "Includes only in-process candidate computation, metric acceptance, "
            "and result ingestion; external retrieval, planning, approval, preflight, "
            "and agent/tool overhead are unavailable."
        ),
        "formula": {
            "trial_speedup": "baseline_trials_to_threshold / guided_trials_to_threshold",
            "time_speedup": (
                "baseline_elapsed_seconds_to_threshold / "
                "guided_elapsed_seconds_to_threshold"
            ),
        },
        "baseline_trials_to_threshold": asdict(b_trials),
        "guided_trials_to_threshold": asdict(g_trials),
        "baseline_seconds_to_threshold": asdict(b_time),
        "guided_seconds_to_threshold": asdict(g_time),
    }
    blockers: list[str] = []
    validity_failures: list[str] = []
    if not matched:
        validity_failures.append("controls_or_candidate_sets_differ")
    if not quality_estimable:
        blockers.append("quality_non_inferiority_not_estimable")
    elif not quality_ok:
        blockers.append("quality_non_inferiority_failed")
    if not threshold_was_preregistered:
        validity_failures.append("threshold_not_preregistered")

    if not b_trials.censored and not g_trials.censored:
        assert b_trials.value is not None and g_trials.value is not None
        trial_ratio = float(b_trials.value) / float(g_trials.value)
        time_ratio = (
            float(b_time.value) / float(g_time.value)
            if b_time.value is not None
            and g_time.value is not None
            and float(g_time.value) > 0
            else None
        )
        result.update(
            status="BOTH_REACHED",
            trial_speedup=trial_ratio,
            time_speedup=time_ratio,
        )
        if trial_ratio <= 1.0:
            blockers.append("trial_speedup_not_above_one")
        if time_ratio is None:
            blockers.append("time_speedup_not_estimable")
        elif time_ratio <= 1.0:
            blockers.append("time_speedup_not_above_one")
        if trial_ratio > 1.0 and matched and quality_ok and threshold_was_preregistered:
            result["claim"] = "TRIAL_EFFICIENCY_ONLY"
    elif b_trials.censored and not g_trials.censored:
        assert b_trials.lower_bound_exclusive is not None and g_trials.value is not None
        lower_bound = float(b_trials.lower_bound_exclusive) / float(g_trials.value)
        result.update(
            status="BASELINE_CENSORED_GUIDED_REACHED",
            trial_speedup_lower_bound=lower_bound,
            trial_speedup_lower_bound_exclusive=lower_bound,
            claim="CATEGORICAL_GUIDED_REACHED_BASELINE_DID_NOT",
        )
        blockers.extend(("baseline_censored", "time_speedup_not_estimable"))
    elif not b_trials.censored and g_trials.censored:
        result["status"] = "GUIDED_CENSORED"
        blockers.extend(("proposed_censored", "time_speedup_not_estimable"))
    else:
        blockers.extend(
            ("baseline_censored", "proposed_censored", "time_speedup_not_estimable")
        )
    if not result["overhead_included"]:
        blockers.append("overhead_missing")
    if baseline.compute_seconds is None or guided.compute_seconds is None:
        blockers.append("compute_unavailable")
    if (
        not blockers
        and not validity_failures
        and result["trial_speedup"] is not None
        and result["time_speedup"] is not None
    ):
        result["positive_acceleration_claim"] = True
        result["overall_discovery_speed_claim"] = True
        result["claim"] = "POSITIVE"
    result["claim_blockers"] = sorted(set(blockers))
    result["validity_failures"] = sorted(validity_failures)
    return result


def _candidate_evaluation_worker(
    connection: Any,
    candidate: _Candidate,
    dataset: _Dataset,
    train_indices: Sequence[int],
    test_indices: Sequence[int],
) -> None:
    """Evaluate in a killable process and report measured child CPU use."""

    started = time.process_time()
    try:
        metric = _evaluate_candidate(candidate, dataset, train_indices, test_indices)
        message: tuple[str, Any, float] = (
            "PASS",
            metric,
            max(0.0, time.process_time() - started),
        )
    except BaseException as exc:  # The child must serialize failures, not disappear.
        message = (
            "ERROR",
            f"{type(exc).__name__}: {exc}"[:240],
            max(0.0, time.process_time() - started),
        )
    try:
        connection.send(message)
    finally:
        connection.close()


def _bounded_candidate_evaluation(
    candidate: _Candidate,
    dataset: _Dataset,
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    *,
    timeout_seconds: float,
) -> tuple[str, float | None, str | None, float | None]:
    """Run one evaluator under a real deadline and reap it before returning.

    A thread timeout cannot stop model code that continues running after the
    budget is exhausted.  Each trial therefore gets a dedicated process.  A
    timeout terminates (and, if necessary, kills) that exact process and joins
    it before reporting ``TIMEOUT``, so no evaluator activity survives into a
    later trial or arm.
    """

    if timeout_seconds <= 0:
        return "TIMEOUT", None, "hard per-arm wall-time budget exhausted", 0.0
    methods = multiprocessing.get_all_start_methods()
    context = multiprocessing.get_context("fork" if "fork" in methods else "spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_candidate_evaluation_worker,
        args=(sender, candidate, dataset, train_indices, test_indices),
        daemon=True,
    )
    deadline = time.monotonic() + timeout_seconds
    started = False
    try:
        process.start()
        started = True
        sender.close()
        process.join(max(0.0, deadline - time.monotonic()))
        if started and process.is_alive():
            process.terminate()
            process.join(1.0)
            if process.is_alive():
                process.kill()
                process.join(1.0)
            if process.is_alive():  # pragma: no cover - an OS-level failure
                raise ExperimentValidationError(
                    "timed-out evaluator process could not be reaped"
                )
            return (
                "TIMEOUT",
                None,
                "TimeoutError: hard per-arm wall-time deadline exceeded",
                None,
            )
        if not receiver.poll():
            return (
                "ERROR",
                None,
                f"evaluator process exited without a result (exitcode={process.exitcode})",
                None,
            )
        try:
            outcome, value, child_cpu = receiver.recv()
        except (EOFError, OSError):
            return (
                "ERROR",
                None,
                f"evaluator process closed without a result (exitcode={process.exitcode})",
                None,
            )
        if outcome == "PASS":
            return "PASS", value, None, float(child_cpu)
        return "ERROR", None, str(value), float(child_cpu)
    finally:
        sender.close()
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(1.0)
            if process.is_alive():
                process.kill()
                process.join(1.0)
        elif started:
            process.join()


def _run_arm(
    arm: str,
    policy: str,
    candidates: Sequence[_Candidate],
    dataset: _Dataset,
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    config: ExperimentConfig,
    control_digest: str,
    candidate_set_digest: str,
    monotonic: Callable[[], float],
    process_clock: Callable[[], float],
    workflow_measurements: ArmWorkflowMeasurements | None,
) -> ArmResult:
    arm_start = monotonic()
    cpu_start = process_clock()
    external_overhead = (
        workflow_measurements.overhead_seconds
        if workflow_measurements is not None
        else 0.0
    )
    results: list[TrialResult] = []
    first_threshold_ordinal: int | None = None
    first_threshold_seconds: float | None = None
    stop_reason = "completed-fixed-trial-budget"
    for candidate in candidates[: config.max_trials_per_arm]:
        before = monotonic()
        elapsed_before = external_overhead + max(0.0, before - arm_start)
        if elapsed_before >= config.max_seconds_per_arm:
            stop_reason = "wall-time-budget-exhausted"
            break
        ordinal = len(results) + 1
        cpu_before = process_clock()
        remaining_seconds = config.max_seconds_per_arm - elapsed_before
        status, metric, error, evaluator_cpu = _bounded_candidate_evaluation(
            candidate,
            dataset,
            train_indices,
            test_indices,
            timeout_seconds=remaining_seconds,
        )
        if status == "PASS" and metric is not None and (
            not math.isfinite(metric) or not 0.0 <= metric <= 1.0
        ):
            status = "ERROR"
            metric = None
            error = "ExperimentValidationError: evaluator returned an invalid accuracy"
        after = monotonic()
        cpu_after = process_clock()
        trial_elapsed = max(0.0, after - before)
        trial_compute = (
            evaluator_cpu + max(0.0, cpu_after - cpu_before)
            if evaluator_cpu is not None
            else None
        )
        total_elapsed = external_overhead + max(0.0, after - arm_start)
        if total_elapsed > config.max_seconds_per_arm:
            status = "TIMEOUT"
            metric = None
            error = "hard per-arm wall-time budget exceeded"
        results.append(
            TrialResult(
                ordinal=ordinal,
                candidate_id=candidate.candidate_id,
                status=status,
                metric=metric,
                elapsed_seconds=trial_elapsed,
                compute_seconds=trial_compute,
                error=error,
            )
        )
        if (
            status == "PASS"
            and metric is not None
            and metric >= config.threshold
            and first_threshold_ordinal is None
        ):
            first_threshold_ordinal = ordinal
            first_threshold_seconds = total_elapsed
        if status == "TIMEOUT":
            stop_reason = "wall-time-budget-exhausted"
            break
    arm_elapsed = external_overhead + max(0.0, monotonic() - arm_start)
    trial_compute_values = [trial.compute_seconds for trial in results]
    arm_compute = (
        None
        if any(value is None for value in trial_compute_values)
        else max(
            sum(float(value) for value in trial_compute_values),
            max(0.0, process_clock() - cpu_start),
        )
    )
    attempted = len(results)
    failures = sum(trial.status != "PASS" for trial in results)
    successful_metrics = [
        trial.metric
        for trial in results
        if trial.status == "PASS" and trial.metric is not None
    ]
    censor_reason = None
    if first_threshold_ordinal is None:
        censor_reason = (
            "wall-time-budget-exhausted"
            if stop_reason == "wall-time-budget-exhausted"
            else "trial-budget-exhausted"
        )
    trial_endpoint = Endpoint(
        value=first_threshold_ordinal,
        censored=first_threshold_ordinal is None,
        lower_bound_exclusive=attempted if first_threshold_ordinal is None else None,
        censoring_reason=censor_reason,
    )
    time_endpoint = Endpoint(
        value=first_threshold_seconds,
        censored=first_threshold_seconds is None,
        lower_bound_exclusive=arm_elapsed if first_threshold_seconds is None else None,
        censoring_reason=censor_reason,
    )
    compute_to_threshold: float | None = None
    if first_threshold_ordinal is not None:
        threshold_compute = [
            trial.compute_seconds for trial in results[:first_threshold_ordinal]
        ]
        if all(value is not None for value in threshold_compute):
            compute_to_threshold = sum(float(value) for value in threshold_compute)
    return ArmResult(
        arm=arm,
        policy=policy,
        trials=tuple(results),
        attempted_trials=attempted,
        failed_trials=failures,
        best_metric=max(successful_metrics) if successful_metrics else None,
        trials_to_threshold=trial_endpoint,
        seconds_to_threshold=time_endpoint,
        elapsed_seconds=arm_elapsed,
        compute_seconds=arm_compute,
        compute_seconds_to_threshold=compute_to_threshold,
        external_overhead_seconds=external_overhead,
        overhead_included=workflow_measurements is not None,
        human_interventions=(
            workflow_measurements.human_interventions
            if workflow_measurements is not None
            else None
        ),
        cost_usd=(
            workflow_measurements.cost_usd
            if workflow_measurements is not None
            else None
        ),
        token_usage=(
            workflow_measurements.token_usage
            if workflow_measurements is not None
            else None
        ),
        measurement_source_digest=(
            workflow_measurements.source_digest
            if workflow_measurements is not None
            else None
        ),
        stop_reason=stop_reason,
        control_digest=control_digest,
        candidate_set_digest=candidate_set_digest,
    )


def _normalize_arm_measurements(
    value: Mapping[str, ArmWorkflowMeasurements | Mapping[str, Any]] | None,
) -> dict[str, ArmWorkflowMeasurements]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ExperimentValidationError("arm_measurements must be a mapping")
    expected = {"baseline", "evidence_guided"}
    if set(value) != expected:
        raise ExperimentValidationError(
            "arm_measurements must contain exactly baseline and evidence_guided"
        )
    return {
        name: ArmWorkflowMeasurements.from_value(measurement)
        for name, measurement in value.items()
    }


def _evaluate_candidate(
    candidate: _Candidate,
    dataset: _Dataset,
    train_indices: Sequence[int],
    test_indices: Sequence[int],
) -> float:
    selected_train = [
        tuple(dataset.features[row][column] for column in candidate.feature_indices)
        for row in train_indices
    ]
    selected_test = [
        tuple(dataset.features[row][column] for column in candidate.feature_indices)
        for row in test_indices
    ]
    train_labels = [dataset.labels[row] for row in train_indices]
    test_labels = [dataset.labels[row] for row in test_indices]
    means, scales = _scaling(selected_train)
    train_scaled = [_standardize(row, means, scales) for row in selected_train]
    test_scaled = [_standardize(row, means, scales) for row in selected_test]
    correct = 0
    neighbors = min(candidate.neighbors, len(train_scaled))
    for row, expected in zip(test_scaled, test_labels, strict=True):
        distances = sorted(
            (
                (sum((left - right) ** 2 for left, right in zip(row, other, strict=True)), label)
                for other, label in zip(train_scaled, train_labels, strict=True)
            ),
            key=lambda item: (item[0], item[1]),
        )[:neighbors]
        counts = Counter(label for _, label in distances)
        prediction = min(counts, key=lambda label: (-counts[label], label))
        correct += prediction == expected
    return correct / len(test_labels)


def _scaling(rows: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    columns = list(zip(*rows, strict=True))
    means = tuple(sum(column) / len(column) for column in columns)
    scales = []
    for column, mean in zip(columns, means, strict=True):
        variance = sum((value - mean) ** 2 for value in column) / len(column)
        scales.append(math.sqrt(variance) or 1.0)
    return means, tuple(scales)


def _standardize(
    row: Sequence[float], means: Sequence[float], scales: Sequence[float]
) -> tuple[float, ...]:
    return tuple(
        (value - mean) / scale
        for value, mean, scale in zip(row, means, scales, strict=True)
    )


def _candidate_pool(feature_count: int) -> tuple[_Candidate, ...]:
    if feature_count != 4:
        raise ExperimentValidationError(
            "pinned task requires exactly four numeric predictor features"
        )
    # Both arms receive this exact set.  Domain evidence only preregisters order:
    # Iris petal measurements are expected to be more discriminative than sepal-only
    # measurements; observed evaluation scores never alter the order during a run.
    return (
        _Candidate(
            "sepal-k15",
            (0, 1),
            15,
            4,
            "Lowest-priority preregistered hypothesis: sepal-only features may be "
            "a weak comparator.",
            ("fixture-agent-hypothesis-sepal-weak",),
        ),
        _Candidate(
            "sepal-k7",
            (0, 1),
            7,
            3,
            "Lower-priority preregistered hypothesis: a smaller sepal-only "
            "neighborhood may improve fit.",
            ("fixture-agent-hypothesis-neighborhood",),
        ),
        _Candidate(
            "all-k7",
            (0, 1, 2, 3),
            7,
            2,
            "Second-priority preregistered hypothesis: all declared measurements "
            "provide a fallback.",
            ("fixture-agent-hypothesis-all-features",),
        ),
        _Candidate(
            "petal-k5",
            (2, 3),
            5,
            1,
            "First-priority agent hypothesis from feature semantics: test petal "
            "dimensions first; this is not an observed result.",
            ("fixture-agent-hypothesis-petal-first",),
        ),
    )


def _load_dataset(
    *, fixture_dir: Path, live: bool, network_timeout_seconds: float
) -> _Dataset:
    if live:
        return _load_openml(network_timeout_seconds)
    return _load_fixture(fixture_dir)


def _load_fixture(fixture_dir: Path) -> _Dataset:
    metadata_path = fixture_dir / "task_59_proxy.metadata.json"
    data_path = fixture_dir / "task_59_proxy.csv"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        raw = data_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentValidationError("fixture metadata or data is unavailable") from exc
    required = {
        "schema": "hermetic-dataset-fixture/v1",
        "mode": "synthetic-hermetic-proxy",
        "scientific_use": "tests-only",
        "openml_task_id": OPENML_TASK_ID,
        "openml_dataset_id": OPENML_DATASET_ID,
        "openml_dataset_version": OPENML_DATASET_VERSION,
        "license_spdx": "CC0-1.0",
        "requires_authentication": False,
    }
    for key, expected in required.items():
        if metadata.get(key) != expected:
            raise ExperimentValidationError(f"fixture metadata mismatch: {key}")
    for field in ("license_verification", "privacy_attestation"):
        attestation = metadata.get(field)
        if (
            not isinstance(attestation, Mapping)
            or attestation.get("status") != "VERIFIED"
            or not isinstance(attestation.get("evidence"), str)
            or not attestation["evidence"].strip()
        ):
            raise ExperimentValidationError(
                f"fixture {field} is missing, UNKNOWN, or unverified"
            )
    if metadata.get("sha256") != _sha256(raw):
        raise ExperimentValidationError("fixture data digest does not match metadata")
    if metadata.get("byte_count") != len(raw):
        raise ExperimentValidationError("fixture byte count does not match metadata")
    features, labels, names = _parse_csv(raw)
    if metadata.get("row_count") != len(labels):
        raise ExperimentValidationError("fixture row count does not match metadata")
    return _checked_dataset(features, labels, names, raw, metadata)


def _load_openml(timeout: float) -> _Dataset:
    task = _http_json(OPENML_TASK_URL, timeout)
    dataset_description = _http_json(OPENML_DATASET_METADATA_URL, timeout)
    try:
        task_body = task["task"]
        source = next(item for item in task_body["input"] if item["name"] == "source_data")
        source_data = source["data_set"]
        description = dataset_description["data_set_description"]
    except (KeyError, TypeError, StopIteration) as exc:
        raise LiveDataUnavailableError("OpenML returned an unexpected task schema") from exc
    if (
        str(task_body.get("task_id")) != str(OPENML_TASK_ID)
        or str(source_data.get("data_set_id")) != str(OPENML_DATASET_ID)
        or source_data.get("target_feature") != OPENML_TARGET
    ):
        raise LiveDataUnavailableError("OpenML task identity no longer matches the pin")
    if (
        str(description.get("id")) != str(OPENML_DATASET_ID)
        or str(description.get("version")) != str(OPENML_DATASET_VERSION)
        or description.get("default_target_attribute") != OPENML_TARGET
        or not str(description.get("licence", "")).strip()
    ):
        raise LiveDataUnavailableError("OpenML dataset identity/license no longer matches the pin")
    raw = _http_bytes(str(description.get("url") or OPENML_DATA_URL), timeout)
    declared_md5 = description.get("md5_checksum")
    if declared_md5 and hashlib.md5(raw, usedforsecurity=False).hexdigest() != declared_md5:
        raise LiveDataUnavailableError("OpenML data bytes do not match the declared MD5")
    features, labels, names = _parse_arff(raw)
    metadata = {
        "mode": "openml-live",
        "scientific_use": "bounded-live-experiment",
        "openml_task_id": OPENML_TASK_ID,
        "openml_dataset_id": OPENML_DATASET_ID,
        "openml_dataset_version": OPENML_DATASET_VERSION,
        "openml_task_url": OPENML_TASK_URL,
        "openml_dataset_metadata_url": OPENML_DATASET_METADATA_URL,
        "openml_live_data_url": str(description.get("url") or OPENML_DATA_URL),
        "license_declared_by_openml": description["licence"],
        "license_note": (
            "License is reported exactly as declared by OpenML dataset 61; "
            "operators remain responsible for downstream-use review."
        ),
        "requires_authentication": False,
        "byte_count": len(raw),
        "openml_md5_checksum": description.get("md5_checksum"),
    }
    return _checked_dataset(features, labels, names, raw, metadata)


def _checked_dataset(
    features: list[tuple[float, ...]],
    labels: list[str],
    names: list[str],
    raw: bytes,
    metadata: dict[str, Any],
) -> _Dataset:
    if not features or len(features) != len(labels):
        raise ExperimentValidationError("dataset must contain matched rows and labels")
    if len(features) > MAX_ROWS:
        raise ExperimentValidationError(f"dataset exceeds hard row cap {MAX_ROWS}")
    if not names or len(names) > MAX_FEATURES:
        raise ExperimentValidationError(f"dataset exceeds hard feature cap {MAX_FEATURES}")
    if any(len(row) != len(names) for row in features):
        raise ExperimentValidationError("dataset rows have inconsistent feature counts")
    if len(set(labels)) < 2:
        raise ExperimentValidationError("classification requires at least two classes")
    return _Dataset(
        tuple(features), tuple(labels), tuple(names), _sha256(raw), dict(metadata)
    )


def _parse_csv(raw: bytes) -> tuple[list[tuple[float, ...]], list[str], list[str]]:
    try:
        text = raw.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or reader.fieldnames[-1] != OPENML_TARGET:
            raise ExperimentValidationError("fixture target column must be class")
        names = reader.fieldnames[:-1]
        features: list[tuple[float, ...]] = []
        labels: list[str] = []
        for row in reader:
            features.append(tuple(float(row[name]) for name in names))
            label = row[OPENML_TARGET].strip()
            if not label:
                raise ExperimentValidationError("fixture contains an empty class")
            labels.append(label)
    except (UnicodeDecodeError, TypeError, ValueError, KeyError) as exc:
        raise ExperimentValidationError("fixture CSV is malformed") from exc
    return features, labels, list(names)


_ATTRIBUTE = re.compile(
    r"^@attribute\s+(?:'([^']+)'|\"([^\"]+)\"|([^\s]+))\s+(.+)$", re.IGNORECASE
)


def _parse_arff(raw: bytes) -> tuple[list[tuple[float, ...]], list[str], list[str]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise LiveDataUnavailableError("OpenML ARFF is not UTF-8") from exc
    attributes: list[tuple[str, str]] = []
    data_lines: list[str] = []
    in_data = False
    for original in lines:
        line = original.strip()
        if not line or line.startswith("%"):
            continue
        if line.lower() == "@data":
            in_data = True
            continue
        if in_data:
            data_lines.append(line)
            continue
        match = _ATTRIBUTE.match(line)
        if match:
            attributes.append(
                (next(group for group in match.groups()[:3] if group is not None), match.group(4))
            )
    if not attributes or attributes[-1][0].lower() != OPENML_TARGET:
        raise LiveDataUnavailableError("OpenML ARFF target is not the pinned class field")
    numeric = {"numeric", "real", "integer"}
    if any(kind.strip().lower() not in numeric for _, kind in attributes[:-1]):
        raise LiveDataUnavailableError("pinned loader accepts numeric predictors only")
    names = [name for name, _ in attributes[:-1]]
    features: list[tuple[float, ...]] = []
    labels: list[str] = []
    for values in csv.reader(data_lines):
        if len(values) != len(attributes) or any(value.strip() == "?" for value in values):
            raise LiveDataUnavailableError("OpenML ARFF contains missing/malformed rows")
        try:
            features.append(tuple(float(value.strip()) for value in values[:-1]))
        except ValueError as exc:
            raise LiveDataUnavailableError("OpenML ARFF contains nonnumeric predictors") from exc
        labels.append(values[-1].strip().strip("'\""))
    return features, labels, names


def _stratified_split(labels: Sequence[str], seed: int) -> tuple[list[int], list[int]]:
    groups: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(label, []).append(index)
    generator = random.Random(seed)
    train: list[int] = []
    test: list[int] = []
    for label in sorted(groups):
        indices = list(groups[label])
        if len(indices) < 2:
            raise ExperimentValidationError(f"class {label!r} has fewer than two rows")
        generator.shuffle(indices)
        test_count = max(1, round(len(indices) * 0.25))
        test.extend(indices[:test_count])
        train.extend(indices[test_count:])
    return sorted(train), sorted(test)


def _http_json(url: str, timeout: float) -> dict[str, Any]:
    raw = _http_bytes(url, timeout)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LiveDataUnavailableError(f"OpenML returned malformed JSON for {url}") from exc
    if not isinstance(value, dict):
        raise LiveDataUnavailableError(f"OpenML returned non-object JSON for {url}")
    return value


def _http_bytes(url: str, timeout: float) -> bytes:
    if not 0.0 < timeout <= 60.0:
        raise ExperimentValidationError("network timeout must be in (0, 60] seconds")
    request = urllib.request.Request(url, headers={"User-Agent": "ai-researcher/0.2"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_DATA_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise LiveDataUnavailableError(f"OpenML request failed: {url}") from exc
    if len(data) > MAX_DATA_BYTES:
        raise LiveDataUnavailableError(
            f"OpenML response exceeds hard byte cap {MAX_DATA_BYTES}"
        )
    return data


def _endpoint_rules() -> dict[str, str]:
    return {
        "attempt": (
            "Count a trial when trial-specific evaluation starts; ERROR and TIMEOUT "
            "attempts remain in the denominator and retries are new trials."
        ),
        "censoring": (
            "If threshold is not reached, value is null and lower_bound_exclusive "
            "is the number of attempted trials (or measured elapsed time)."
        ),
        "overhead": (
            "Arm elapsed time covers only in-process model evaluation and metric "
            "acceptance for both arms. It excludes evidence retrieval, agent planning, "
            "human approval, data preflight, and artifact persistence."
        ),
        "claim": (
            "Ratios are model-evaluation-only. They cannot support an overall discovery-"
            "speed claim; censoring and quality rules still apply to trial efficiency."
        ),
    }


def _scaling_analysis() -> dict[str, Any]:
    assumptions = (
        ("conservative", 0.20, 0.35, 0.45, 2),
        ("expected", 0.08, 0.17, 0.75, 4),
        ("optimistic", 0.02, 0.04, 0.94, 32),
    )
    scenarios = []
    for name, fixed, serial, parallel, workers in assumptions:
        speedup = 1.0 / (fixed + serial + parallel / workers)
        scenarios.append(
            {
                "scenario": name,
                "kind": "forecast",
                "formula": "1 / (fixed_fraction + serial_fraction + parallel_fraction / workers)",
                "fixed_fraction": fixed,
                "serial_fraction": serial,
                "parallel_fraction": parallel,
                "parallel_workers": workers,
                "projected_speedup": speedup,
                "approaches_or_exceeds_10x": speedup >= 9.5,
            }
        )
    return {
        "kind": "forecast-analysis",
        "observed_results_used_as_forecast": False,
        "scenarios": scenarios,
        "remaining_bottlenecks": [
            "source access and evidence quality",
            "serial objective and consequential approval gates",
            "provider and experiment runtime",
            "evidence reconciliation and human review",
        ],
        "parallelizable_or_automatable": [
            "independent retrieval and citation checks",
            "candidate generation and safe simulations",
            "result parsing and provenance assembly",
        ],
        "evidence_still_needed": [
            "repeated seeds and uncertainty intervals",
            "multiple OpenML and domain-relevant tasks",
            "evidence-ordering and reviewed-failure-memory ablations",
            "prospective provider-backed runs",
        ],
        "conditions_for_10x": [
            "baseline search is sufficiently costly",
            "early evidence reliably ranks useful candidates",
            "safe independent work has high parallelism",
            "sources and validations are structured and cached",
            "quality and safety are non-inferior",
        ],
    }


def _runtime_identities() -> dict[str, Any]:
    module_path = Path(__file__).resolve()
    repo_root = module_path.parents[2]
    lock_path = repo_root / "uv.lock"
    package_names = ("ai-researcher", "omnigent", "portable-orchestrator-harness")
    packages: dict[str, str] = {}
    for name in package_names:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "NOT_INSTALLED"
    environment = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": os.path.basename(sys.executable),
    }
    environment["digest"] = _digest(environment)
    return {
        "code": {
            "path": "src/ai_researcher/experiment.py",
            "sha256": _sha256(module_path.read_bytes()),
        },
        "lockfile": {
            "path": "uv.lock",
            "sha256": _sha256(lock_path.read_bytes()) if lock_path.is_file() else None,
        },
        "environment": environment,
        "packages": packages,
        "packages_digest": _digest(packages),
    }


def _write_artifact(
    directory: Path, name: str, value: Mapping[str, Any], *, kind: str
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, allow_nan=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    target = directory / name
    temporary = directory / f".{name}.tmp"
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return {
        "name": name,
        "kind": kind,
        "media_type": "application/json",
        "sha256": _sha256(data),
        "byte_count": len(data),
    }


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:240]


def _arm_metrics(arm: ArmResult) -> dict[str, Any]:
    return {
        "attempted_trials": arm.attempted_trials,
        "failed_trials": arm.failed_trials,
        "best_accuracy": arm.best_metric,
        "trials_to_threshold": asdict(arm.trials_to_threshold),
        "seconds_to_threshold": asdict(arm.seconds_to_threshold),
        "elapsed_to_threshold_seconds": arm.seconds_to_threshold.value,
        "total_elapsed_seconds": arm.elapsed_seconds,
        "compute_seconds": arm.compute_seconds,
        "compute_seconds_to_threshold": arm.compute_seconds_to_threshold,
        "external_overhead_seconds": arm.external_overhead_seconds,
        "overhead_included": arm.overhead_included,
        "human_interventions": arm.human_interventions,
        "cost_usd": arm.cost_usd,
        "token_usage": arm.token_usage,
        "measurement_source_digest": arm.measurement_source_digest,
        "measurement_availability": arm.to_dict()["measurement_availability"],
        "stop_reason": arm.stop_reason,
    }


def _dataset_identity(dataset: Mapping[str, Any]) -> dict[str, str]:
    return {
        "identifier": str(dataset["identifier"]),
        "version": str(dataset["version"]),
        "digest": str(dataset["digest"]),
    }


def _experiment_result_status(baseline: ArmResult, guided: ArmResult) -> str:
    trials = (*baseline.trials, *guided.trials)
    if not trials:
        return "CANCELLED"
    if not any(trial.status == "PASS" for trial in baseline.trials) or not any(
        trial.status == "PASS" for trial in guided.trials
    ):
        return "ERROR"
    if any(trial.status != "PASS" for trial in trials):
        return "FAIL"
    return "PASS"


def _acceleration_arm(
    arm: ArmResult, preregistration: Mapping[str, Any]
) -> dict[str, Any]:
    trial_budget = preregistration["max_trials_per_arm"]
    if arm.trials_to_threshold.censored and (
        arm.trials_to_threshold.lower_bound_exclusive != arm.attempted_trials
    ):
        raise ExperimentValidationError(
            "a censored endpoint must preserve the exact attempted-trial lower bound"
        )
    endpoint = asdict(arm.trials_to_threshold)
    return {
        "trial_budget": trial_budget,
        "trials_attempted": arm.attempted_trials,
        "trials_to_threshold": endpoint,
        "elapsed_to_threshold_seconds": arm.seconds_to_threshold.value,
        "total_elapsed_seconds": arm.elapsed_seconds,
        "compute_seconds": arm.compute_seconds,
        "best_metric": arm.best_metric,
        "interventions": arm.human_interventions,
        "cost_usd": arm.cost_usd,
        "token_usage": arm.token_usage,
        "measurement_availability": arm.to_dict()["measurement_availability"],
    }


__all__ = [
    "ArmResult",
    "ArmWorkflowMeasurements",
    "DataGovernanceAttestation",
    "Endpoint",
    "ExecutionAuthorization",
    "ExperimentConfig",
    "ExperimentOutcome",
    "ExperimentValidationError",
    "HumanObjective",
    "HumanExecutionScope",
    "LiveDataUnavailableError",
    "MAX_SECONDS_PER_ARM",
    "MAX_TRIALS_PER_ARM",
    "OPENML_TASK_ID",
    "PRIMARY_METRIC",
    "PreflightReport",
    "QUALITY_METRIC",
    "calculate_acceleration",
    "preflight",
    "run_matched_experiment",
]
