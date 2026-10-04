from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_researcher import harness_evidence
from orchestrator_harness.config import ResourceManifest, load_config
from orchestrator_harness.core import content_hash
from orchestrator_harness.epochs import lane_record_path, open_epoch, write_active_lanes
from orchestrator_harness.lanes import write_lane


def _publish_active_lane(
    harness_root: Path, lane: dict, *, workspace: Path
) -> str:
    """Publish a lane through the real on-disk Harness index contracts."""

    local_config = harness_root / "local-config"
    local_config.mkdir(parents=True)
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


def _native() -> dict:
    authority = {
        "objective_confirmation_digest": "o" * 64,
        "experiment_digest": "e" * 64,
        "approval_digest": "a" * 64,
    }
    return {
        "schema": "native-terminal-evidence/v1",
        "epoch_id": "epoch-1",
        "lane_id": "lane-1",
        "run_id": "run-1",
        "content_hash": "n" * 64,
        "task_card": {"research_authority": authority},
        "review": {"review_outcome": "PASS"},
        "acceptance": {"approval": "ACCEPTED"},
    }


def test_terminal_evidence_is_read_from_configured_native_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = _native()
    observed: dict = {}
    monkeypatch.setattr(
        harness_evidence,
        "active_harness_run",
        lambda _root, *, lane_id: ("epoch-1", {"lane_id": lane_id, "run_id": "run-1"}),
    )
    monkeypatch.setattr(
        harness_evidence,
        "load_config",
        lambda _root: SimpleNamespace(runtime_root=tmp_path / ".harness-runtime"),
    )

    def read(runtime: Path, epoch: str, lane: str, *, run_id: str) -> dict:
        observed.update(runtime=runtime, epoch=epoch, lane=lane, run_id=run_id)
        return native

    monkeypatch.setattr(harness_evidence, "read_terminal_evidence", read)
    retained = harness_evidence.verified_terminal_evidence(
        tmp_path / "harness",
        lane_id="lane-1",
        run_id="run-1",
        supplied=native,
        authority=native["task_card"]["research_authority"],
        scientific_result={"schema": "experiment-result/v1"},
    )
    assert retained == native
    assert observed == {
        "runtime": tmp_path / ".harness-runtime",
        "epoch": "epoch-1",
        "lane": "lane-1",
        "run_id": "run-1",
    }


def test_caller_supplied_json_cannot_substitute_for_native_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = _native()
    monkeypatch.setattr(
        harness_evidence,
        "active_harness_run",
        lambda _root, *, lane_id: ("epoch-1", {"lane_id": lane_id, "run_id": "run-1"}),
    )
    monkeypatch.setattr(
        harness_evidence,
        "load_config",
        lambda _root: SimpleNamespace(runtime_root=tmp_path / ".harness-runtime"),
    )
    monkeypatch.setattr(
        harness_evidence, "read_terminal_evidence", lambda *_args, **_kwargs: native
    )
    fake = {
        "lane_id": "lane-1",
        "run_id": "run-1",
        "status": "COMPLETED",
        "uri": (tmp_path / "caller.json").as_uri(),
        "digest": "0" * 64,
    }
    with pytest.raises(
        harness_evidence.HarnessEvidenceError, match="differs from the Harness-owned"
    ):
        harness_evidence.verified_terminal_evidence(
            tmp_path / "harness",
            lane_id="lane-1",
            run_id="run-1",
            supplied=fake,
            authority=native["task_card"]["research_authority"],
            scientific_result={"schema": "experiment-result/v1"},
        )


def test_direct_retrieval_rejects_wrong_task_card_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = _native()
    monkeypatch.setattr(
        harness_evidence,
        "_read_owned_terminal_evidence",
        lambda *_args, **_kwargs: native,
    )
    wrong = dict(native["task_card"]["research_authority"])
    wrong["approval_digest"] = "x" * 64
    with pytest.raises(harness_evidence.HarnessEvidenceError, match="approval_digest"):
        harness_evidence.read_verified_terminal_evidence(
            tmp_path / "harness",
            lane_id="lane-1",
            run_id="run-1",
            authority=wrong,
        )


def test_ordinary_lane_uses_real_lane_discovery_and_harness_owned_publication(
    tmp_path: Path,
) -> None:
    authority = {
        "objective_confirmation_digest": "o" * 64,
        "experiment_digest": "e" * 64,
        "approval_digest": "a" * 64,
    }
    card = {"schema": "project-task-card/v1", "research_authority": authority}
    card["content_hash"] = content_hash(card)
    card_path = tmp_path / "task.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    bound_authority = {**authority, "task_card_path": str(card_path)}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness_root = tmp_path / "harness"
    lane = {
        "lane_id": "lane-1",
        "run_id": "run-1",
        "task_card_hash": card["content_hash"],
        "invocation_hash": "invocation-hash-1",
        "git": {"branch": "experiment/test", "bootstrap_tip": "b" * 40},
        "worktree_path": str(tmp_path / "worktree"),
    }
    harness_result = {
        "schema": "result/v1",
        "lane_id": "lane-1",
        "run_id": "run-1",
        "outcome": "PASS",
        "scientific_result": {"schema": "experiment-result/v1"},
    }
    harness_result["content_hash"] = content_hash(harness_result)
    lane["result_validation"] = {
        "run_id": "run-1",
        "result_hash": harness_result["content_hash"],
        "invocation_hash": lane["invocation_hash"],
        "branch": lane["git"]["branch"],
        "commit": "c" * 40,
        "clean": True,
    }
    worktree = Path(lane["worktree_path"])
    worktree.mkdir()
    (worktree / "RESULT.json").write_text(
        json.dumps(harness_result), encoding="utf-8"
    )
    review = {
        "schema": "completion-review/v1",
        "lane_id": "lane-1",
        "run_id": "run-1",
        "task_card_id": "task-card-1",
        "task_card_hash": card["content_hash"],
        "invocation_hash": lane["invocation_hash"],
        "commit": "c" * 40,
        "review_outcome": "PASS",
        "result_id": "run-1",
        "result_hash": harness_result["content_hash"],
    }
    review["content_hash"] = content_hash(review)
    acceptance = {
        "schema": "orchestrator-acceptance/v1",
        "lane_id": "lane-1",
        "run_id": "run-1",
        "task_card_id": "task-card-1",
        "task_card_hash": card["content_hash"],
        "invocation_hash": lane["invocation_hash"],
        "commit": "c" * 40,
        "result_id": "run-1",
        "result_hash": harness_result["content_hash"],
        "approval": "ACCEPTED",
        "accepted_by": "ROOT",
        "review_ref": review["content_hash"],
    }
    acceptance["content_hash"] = content_hash(acceptance)
    lane["acceptance_advancement"] = acceptance
    epoch_id = _publish_active_lane(harness_root, lane, workspace=workspace)
    assert harness_evidence.active_harness_run(
        harness_root, lane_id="lane-1"
    ) == (epoch_id, {"schema": "lane/v1", **lane})
    folder = (
        workspace / ".harness-runtime" / "epochs" / epoch_id / "lanes" / "lane-1"
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "COMPLETION_REVIEW.json").write_text(json.dumps(review), encoding="utf-8")
    (folder / "ORCHESTRATOR_ACCEPTANCE.json").write_text(
        json.dumps(acceptance), encoding="utf-8"
    )
    supplied = {
        "schema": "harness-acceptance-evidence/v1",
        "epoch_id": epoch_id,
        "lane_id": "lane-1",
        "run_id": "run-1",
        "review": review,
        "acceptance": acceptance,
        "result": harness_result,
    }
    assert harness_evidence.verified_terminal_evidence(
        harness_root,
        lane_id="lane-1",
        run_id="run-1",
        supplied=supplied,
        authority=bound_authority,
        scientific_result={"schema": "experiment-result/v1"},
    ) == supplied

    # Production retrieval takes no caller copy and traverses the same real
    # configured runtime/publication path.
    assert harness_evidence.read_verified_terminal_evidence(
        harness_root,
        lane_id="lane-1",
        run_id="run-1",
        authority=bound_authority,
    ) == supplied
