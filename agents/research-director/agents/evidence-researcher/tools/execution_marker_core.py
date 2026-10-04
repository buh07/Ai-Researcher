"""Narrow provider-execution boundary markers for parallel evidence work."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

from omnigent_client.tools import tool


_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_MARKER_ID = re.compile(r"[A-Za-z0-9_-]{32,128}")


def _repo_root() -> Path:
    configured = os.environ.get("AI_RESEARCHER_ROOT")
    candidates = [Path(configured)] if configured else []
    candidates.extend([Path.cwd(), *Path(__file__).resolve().parents])
    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / "src" / "ai_researcher").is_dir() and (
            root / "agents" / "research-director"
        ).is_dir():
            return root
    raise RuntimeError(
        "AI Researcher checkout not found; set AI_RESEARCHER_ROOT to the repository root"
    )


def _branch_id(value: str) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise ValueError("branch_id must be a non-empty stable identifier")
    return value


def _marker_path(marker_id: str) -> Path:
    if not isinstance(marker_id, str) or _MARKER_ID.fullmatch(marker_id) is None:
        raise ValueError("start_marker_id is invalid")
    directory = _repo_root() / "runtime" / "provider-execution-markers"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{marker_id}.json"


def _read_marker(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("unknown or damaged start_marker_id") from exc
    if not isinstance(value, dict):
        raise ValueError("start marker state is malformed")
    return value


@tool
def mark_provider_execution_start(branch_id: str) -> dict[str, str]:
    """Mark the start of substantive work inside this provider child session.

    Call exactly once, before searching or analyzing evidence. The Omnigent
    export's completed function-call result timestamp—not this tool's local
    state—is the authoritative start boundary.

    Args:
        branch_id: Exact branch identity supplied by the research director.
    """

    branch = _branch_id(branch_id)
    marker_id = secrets.token_urlsafe(32)
    path = _marker_path(marker_id)
    state = {
        "schema": "provider-execution-marker-state/v1",
        "branch_id": branch,
        "marker_id": marker_id,
        "consumed": False,
    }
    with path.open("x", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True, separators=(",", ":"))
    return {
        "schema": "provider-execution-marker/v1",
        "phase": "START",
        "branch_id": branch,
        "marker_id": marker_id,
    }


@tool
def mark_provider_execution_end(
    branch_id: str, start_marker_id: str
) -> dict[str, str]:
    """Mark the end of substantive work inside this provider child session.

    Call exactly once after all searches and analysis, immediately before the
    final evidence JSON. The completed Omnigent function-call result timestamp
    is the authoritative end boundary.

    Args:
        branch_id: Exact branch identity supplied by the research director.
        start_marker_id: Marker ID returned by mark_provider_execution_start.
    """

    branch = _branch_id(branch_id)
    path = _marker_path(start_marker_id)
    state = _read_marker(path)
    if (
        state.get("schema") != "provider-execution-marker-state/v1"
        or state.get("branch_id") != branch
        or state.get("marker_id") != start_marker_id
    ):
        raise ValueError("start marker does not bind this branch")
    if state.get("consumed") is not False:
        raise ValueError("start marker was already consumed")
    state["consumed"] = True
    temporary = path.with_suffix(f".{secrets.token_hex(8)}.tmp")
    temporary.write_text(
        json.dumps(state, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)
    return {
        "schema": "provider-execution-marker/v1",
        "phase": "END",
        "branch_id": branch,
        "marker_id": secrets.token_urlsafe(32),
        "start_marker_id": start_marker_id,
    }
