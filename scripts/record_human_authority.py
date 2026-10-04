#!/usr/bin/env python3
"""Operator-only recording path for attributable human scientific authority.

This command is intentionally not exposed as an Omnigent tool. It records only
objective confirmation or consequential approval, with one fixed semantic
parent and producer attribution supplied by the operator.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ai_researcher.journal import ResearchJournal  # noqa: E402
from ai_researcher.records import validate_record  # noqa: E402

_ALLOWED = {"objective-confirmation/v1", "human-approval/v1"}


def record_human_authority(
    *,
    journal_path: str | Path,
    record: Mapping[str, Any],
    parent_digest: str,
    human_id: str,
    human_session_id: str,
) -> dict[str, Any]:
    """Record one human-owned authority record through a fixed semantic edge."""

    normalized = validate_record(record)
    schema = normalized["schema"]
    if schema not in _ALLOWED:
        raise ValueError(
            "operator authority path accepts only objective-confirmation/v1 or "
            "human-approval/v1"
        )
    identity_field = (
        "confirmed_by" if schema == "objective-confirmation/v1" else "approved_by"
    )
    if normalized[identity_field] != human_id:
        raise ValueError(f"{identity_field} must match the attributable human_id")
    if schema == "objective-confirmation/v1":
        supersedes = normalized.get("supersedes_objective_confirmation_digest")
        expected_parent = supersedes or normalized["question_digest"]
        if expected_parent != parent_digest:
            raise ValueError(
                "objective parent must be its exact question or superseded-objective digest"
            )
        relation = "supersedes-objective" if supersedes else "confirms-objective"
    else:
        relation = "approves-after-review"
    return ResearchJournal(journal_path).append(
        normalized,
        source="human:operator",
        links=((parent_digest, relation),),
        producer_agent_id=human_id,
        producer_session_id=human_session_id,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record human objective confirmation or experiment approval."
    )
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--parent-digest", required=True)
    parser.add_argument("--human-id", required=True)
    parser.add_argument("--human-session-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.record.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--record must contain one JSON object")
    stored = record_human_authority(
        journal_path=args.journal,
        record=payload,
        parent_digest=args.parent_digest,
        human_id=args.human_id,
        human_session_id=args.human_session_id,
    )
    print(json.dumps(stored, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
