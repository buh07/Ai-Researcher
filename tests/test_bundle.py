from __future__ import annotations

import ast
import runpy
from pathlib import Path

import pytest
import yaml

from omnigent.spec import load

from ai_researcher.records import ID_FIELDS


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "agents" / "research-director"


def test_omnigent_bundle_loads() -> None:
    spec = load(BUNDLE)
    assert spec.name == "research-director"
    assert {tool.name for tool in spec.local_tools} == {"research_runtime"}
    local_tools = {
        agent.name: {tool.name for tool in agent.local_tools}
        for agent in spec.sub_agents
    }
    assert local_tools["evidence-researcher"] == {"execution_marker"}
    assert all(
        not tools
        for name, tools in local_tools.items()
        if name != "evidence-researcher"
    )


def test_expected_specialists_are_present() -> None:
    expected = {
        "evidence-researcher",
        "hypothesis-scientist",
        "experiment-designer",
        "safety-reviewer",
        "results-analyst",
    }
    configs = list((BUNDLE / "agents").glob("*/config.yaml"))
    names = {
        next(
            line.split(":", 1)[1].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("name:")
        )
        for path in configs
    }
    assert names == expected


def test_handoff_contracts_cover_complete_coordination_loop() -> None:
    contracts = (ROOT / "docs" / "HANDOFF_CONTRACTS.md").read_text(encoding="utf-8")
    assert len(ID_FIELDS) == 13
    assert {
        heading.removeprefix("### `").removesuffix("`")
        for heading in contracts.splitlines()
        if heading.startswith("### `") and heading.endswith("/v1`")
    } == set(ID_FIELDS)
    for schema in ID_FIELDS:
        assert f'"schema": "{schema}"' in contracts


def test_bundle_roles_tools_versions_permissions_and_budgets_are_exact() -> None:
    director = yaml.safe_load((BUNDLE / "config.yaml").read_text(encoding="utf-8"))
    expected_agents = {
        "evidence-researcher",
        "hypothesis-scientist",
        "experiment-designer",
        "safety-reviewer",
        "results-analyst",
    }
    assert director["spec_version"] == 1
    assert set(director["tools"]["agents"]) == expected_agents
    assert director["params"] == {
        "minimum_experiment_candidates": 2,
        "maximum_parallel_evidence_tasks": 3,
        "minimum_overlapping_evidence_tasks": 2,
        "require_human_objective_confirmation": True,
        "require_passing_feasibility_gate": True,
        "require_human_experiment_approval": True,
        "execution_enabled_by_default": False,
        "execution_environment_gate": "AI_RESEARCHER_ENABLE_EXECUTION",
    }
    policies = director["guardrails"]["policies"]
    assert policies["tool_call_budget"]["function"]["arguments"] == {"limit": 80}
    assert policies["session_cost_budget"]["function"]["arguments"] == {
        "max_cost_usd": 8.0,
        "ask_thresholds_usd": [4.0],
    }
    for path in (BUNDLE / "agents").glob("*/config.yaml"):
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert config["spec_version"] == 1
        tools = config.get("tools", {})
        if config["name"] == "evidence-researcher":
            assert tools == {"builtins": ["web_search"]}
        else:
            assert tools == {}
    prompts = {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in (BUNDLE / "agents").glob("*/AGENTS.md")
    }
    assert "Never design or execute an experiment" in prompts["evidence-researcher"]
    assert "Do not run, approve" in prompts["experiment-designer"]
    assert "You cannot approve execution" in prompts["safety-reviewer"]
    assert "Never rewrite a metric" in prompts["results-analyst"]


def test_director_documents_every_exposed_runtime_tool() -> None:
    source = (BUNDLE / "tools" / "python" / "research_runtime.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    exposed = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(item, ast.Name) and item.id == "tool" for item in node.decorator_list)
    }
    instructions = (BUNDLE / "AGENTS.md").read_text(encoding="utf-8")
    assert exposed
    assert all(f"`{name}`" in instructions for name in exposed)


def test_harness_is_integrated_through_one_adapter() -> None:
    assert (ROOT / "harness" / "orchestrator_harness").is_dir()
    adapter = (ROOT / "src" / "ai_researcher" / "harness_adapter.py").read_text(
        encoding="utf-8"
    )
    assert "orchestrator_harness.operator_launch" in adapter
    tool = (BUNDLE / "tools" / "python" / "research_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "HarnessAdapter" in tool


def test_project_has_no_mongodb_dependency() -> None:
    manifests = [
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "harness" / "orchestrator_harness" / "pyproject.toml",
    ]
    project = "\n".join(path.read_text(encoding="utf-8").lower() for path in manifests)
    assert "pymongo" not in project
    assert "langchain-mongodb" not in project


def test_project_has_no_source_repository_wiring() -> None:
    assert not (ROOT / ".gitmodules").exists()
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for base in (ROOT / "agents", ROOT / "docs", ROOT / "src")
        for path in base.rglob("*")
        if path.is_file()
    ).lower()
    forbidden = ("jason" + "peng2019", "jason" + ".peng" + ".2019")
    assert all(value not in text for value in forbidden)


def test_agent_tool_cannot_create_human_authority() -> None:
    runtime = runpy.run_path(str(BUNDLE / "tools" / "python" / "research_runtime.py"))
    reject = runtime["_ensure_agent_record_allowed"]
    for schema in ("objective-confirmation/v1", "human-approval/v1"):
        with pytest.raises(ValueError, match="agents cannot create"):
            reject({"schema": schema})


def test_local_branch_events_are_single_use_dispatch_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src" / "ai_researcher").mkdir(parents=True)
    (tmp_path / "harness" / "orchestrator_harness").mkdir(parents=True)
    monkeypatch.setenv("AI_RESEARCHER_ROOT", str(tmp_path))
    runtime = runpy.run_path(str(BUNDLE / "tools" / "python" / "research_runtime.py"))
    started = runtime["_start_branch_event"]("branch-1", "agent-1", "session-1")
    finished = runtime["_finish_branch_event"](started["invocation_token"])
    record, start_time, end_time = runtime["_consume_branch_event"](
        started["invocation_token"],
        {
            "branch_id": "branch-1",
            "started_at": "1900-01-01T00:00:00Z",
            "completed_at": "2999-01-01T00:00:00Z",
        },
        "agent-1",
        "session-1",
    )
    assert start_time == started["invocation_started_at"]
    assert end_time == finished["invocation_completed_at"]
    assert record["started_at"] == start_time
    assert record["completed_at"] == end_time


def test_evidence_provider_execution_markers_are_narrow_and_single_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "src" / "ai_researcher").mkdir(parents=True)
    (tmp_path / "agents" / "research-director").mkdir(parents=True)
    monkeypatch.setenv("AI_RESEARCHER_ROOT", str(tmp_path))
    marker_module = runpy.run_path(
        str(
            BUNDLE
            / "agents"
            / "evidence-researcher"
            / "tools"
            / "python"
            / "execution_marker.py"
        )
    )
    started = marker_module["mark_provider_execution_start"]("branch-a")
    assert started == {
        "schema": "provider-execution-marker/v1",
        "phase": "START",
        "branch_id": "branch-a",
        "marker_id": started["marker_id"],
    }
    ended = marker_module["mark_provider_execution_end"](
        "branch-a", started["marker_id"]
    )
    assert ended["phase"] == "END"
    assert ended["branch_id"] == "branch-a"
    assert ended["start_marker_id"] == started["marker_id"]
    with pytest.raises(ValueError, match="already consumed"):
        marker_module["mark_provider_execution_end"](
            "branch-a", started["marker_id"]
        )
