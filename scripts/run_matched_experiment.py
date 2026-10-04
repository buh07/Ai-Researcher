#!/usr/bin/env python3
"""Run the bounded matched experiment with an explicit human objective packet."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from ai_researcher.experiment import (
    ExecutionAuthorization,
    ExperimentConfig,
    HumanObjective,
    run_matched_experiment,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the preregistered matched classifier experiment. Fixture mode is "
            "synthetic and cannot support scientific performance claims; live mode "
            "is an explicit networked OpenML action."
        )
    )
    parser.add_argument("--mode", choices=("fixture", "live"), required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--primary-metric", required=True)
    parser.add_argument("--openml-task-id", required=True, type=int)
    parser.add_argument("--dataset-identifier", required=True)
    parser.add_argument("--openml-dataset-id", required=True, type=int)
    parser.add_argument("--openml-dataset-version", required=True, type=int)
    parser.add_argument("--dataset-digest", required=True)
    parser.add_argument("--risk-tolerance", required=True)
    parser.add_argument(
        "--execution-scope-json",
        required=True,
        help="JSON object containing all human-confirmed execution limits",
    )
    parser.add_argument(
        "--data-governance-json",
        required=True,
        help="JSON object containing verified license and privacy attestations",
    )
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--confirmed-at", required=True)
    parser.add_argument("--objective-confirmation-digest")
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--split-seed", type=int)
    parser.add_argument("--max-trials-per-arm", type=int)
    parser.add_argument("--max-seconds-per-arm", type=float)
    parser.add_argument("--estimated-cost-usd", type=float)
    parser.add_argument("--quality-noninferiority-margin", type=float)
    parser.add_argument("--network-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--journal-path", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--experiment-digest")
    parser.add_argument("--approval-digest")
    parser.add_argument("--task-card-digest")
    parser.add_argument(
        "--arm-measurements-json",
        help=(
            "Observed baseline/evidence_guided workflow telemetry with a "
            "source_digest. Omit when provider/workflow telemetry is unavailable; "
            "missing values are never treated as zero."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        execution_scope = json.loads(args.execution_scope_json)
        data_governance = json.loads(args.data_governance_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"structured objective JSON is invalid: {exc}") from exc
    objective = HumanObjective(
        objective=args.objective,
        primary_metric=args.primary_metric,
        openml_task_id=args.openml_task_id,
        dataset_identifier=args.dataset_identifier,
        openml_dataset_id=args.openml_dataset_id,
        openml_dataset_version=args.openml_dataset_version,
        dataset_digest=args.dataset_digest,
        risk_tolerance=args.risk_tolerance,
        execution_scope=execution_scope,
        data_governance=data_governance,
        confirmed_by=args.confirmed_by,
        confirmed_at=args.confirmed_at,
        objective_confirmation_digest=args.objective_confirmation_digest,
    )
    run_options = {
        "artifact_dir": args.artifact_dir,
        "live": args.mode == "live",
        "network_timeout_seconds": args.network_timeout_seconds,
    }
    if args.arm_measurements_json is not None:
        try:
            run_options["arm_measurements"] = json.loads(args.arm_measurements_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"arm measurement JSON is invalid: {exc}") from exc
    if args.mode == "live":
        config_overrides = {
            "threshold": args.threshold,
            "split_seed": args.split_seed,
            "max_trials_per_arm": args.max_trials_per_arm,
            "max_seconds_per_arm": args.max_seconds_per_arm,
            "estimated_cost_usd": args.estimated_cost_usd,
            "quality_noninferiority_margin": args.quality_noninferiority_margin,
        }
        supplied_overrides = sorted(
            name for name, value in config_overrides.items() if value is not None
        )
        if supplied_overrides:
            raise SystemExit(
                "live mode derives exact experiment parameters from the approved "
                "journal candidate; remove caller overrides: "
                + ", ".join(supplied_overrides)
            )
        live_fields = {
            "journal_path": args.journal_path,
            "experiment_id": args.experiment_id,
            "objective_confirmation_digest": args.objective_confirmation_digest,
            "experiment_digest": args.experiment_digest,
            "approval_digest": args.approval_digest,
            "task_card_digest": args.task_card_digest,
        }
        missing = sorted(name for name, value in live_fields.items() if value is None)
        if missing:
            raise SystemExit(
                "live mode requires journal-backed authority fields: "
                + ", ".join(missing)
            )
        run_options["authorization"] = ExecutionAuthorization(**live_fields)
    else:
        run_options["config"] = ExperimentConfig(
            threshold=args.threshold if args.threshold is not None else 0.90,
            split_seed=args.split_seed if args.split_seed is not None else 1729,
            max_trials_per_arm=(
                args.max_trials_per_arm
                if args.max_trials_per_arm is not None
                else 4
            ),
            max_seconds_per_arm=(
                args.max_seconds_per_arm
                if args.max_seconds_per_arm is not None
                else 30.0
            ),
            estimated_cost_usd=(
                args.estimated_cost_usd
                if args.estimated_cost_usd is not None
                else 0.0
            ),
            quality_noninferiority_margin=(
                args.quality_noninferiority_margin
                if args.quality_noninferiority_margin is not None
                else 0.02
            ),
        )
    if args.fixture_dir is not None:
        run_options["fixture_dir"] = args.fixture_dir
    outcome = run_matched_experiment(objective, **run_options)

    result = outcome.to_dict()
    encoded = (
        json.dumps(result, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, output)

    if args.mode == "fixture":
        print(
            f"wrote hermetic fixture result to {output}; "
            "fixture scores are not scientific evidence"
        )
    else:
        print(f"wrote live OpenML result to {output}; review limitations before claims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
