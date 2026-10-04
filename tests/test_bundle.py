from __future__ import annotations

import ast
import json
import runpy
import tomllib
from pathlib import Path

import pytest
import yaml

from omnigent.spec import load
from omnigent.runner.tool_dispatch import _granted_tool_names

from ai_researcher.records import ID_FIELDS


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "agents" / "research-director"
RUNTIME_CORE = BUNDLE / "tools" / "research_runtime_core.py"
RESEARCH_RUNTIME_TOOLS = {
    "start_parallel_branch",
    "finish_parallel_branch",
    "record_research_record",
    "read_research_chain",
    "get_learning_receipt",
    "preflight_confirmed_objective",
    "request_experiment_approval",
    "stage_approved_experiment",
    "launch_approved_experiment",
    "get_experiment_status",
    "get_harness_experiment_status",
    "wait_for_experiment",
    "review_experiment_completion",
    "read_experiment_terminal_evidence",
    "build_harness_result",
    "ingest_harness_experiment_result",
    "force_stop_experiment",
    "read_experiment_cancellation_evidence",
    "retire_experiment",
    "shutdown_research_harness",
    "record_experiment_result",
}
EVIDENCE_TOOLS = {
    "inspect_public_source",
    "mark_provider_execution_start",
    "mark_provider_execution_end",
    "search_public_web",
    "validate_evidence_package",
}


def test_omnigent_bundle_loads() -> None:
    spec = load(BUNDLE)
    assert spec.name == "research-director"
    assert {tool.name for tool in spec.local_tools} == RESEARCH_RUNTIME_TOOLS
    local_tools = {
        agent.name: {tool.name for tool in agent.local_tools}
        for agent in spec.sub_agents
    }
    assert local_tools["evidence-researcher"] == EVIDENCE_TOOLS
    evidence_researcher = next(
        agent for agent in spec.sub_agents if agent.name == "evidence-researcher"
    )
    assert evidence_researcher.tools.builtins == []
    assert all(
        not tools
        for name, tools in local_tools.items()
        if name != "evidence-researcher"
    )


def test_research_runtime_functions_are_in_the_live_dispatch_grant() -> None:
    spec = load(BUNDLE)
    assert RESEARCH_RUNTIME_TOOLS <= _granted_tool_names(spec, "codex")


def test_evidence_tools_are_in_the_live_dispatch_grant() -> None:
    spec = load(BUNDLE)
    evidence_researcher = next(
        agent for agent in spec.sub_agents if agent.name == "evidence-researcher"
    )
    assert EVIDENCE_TOOLS <= _granted_tool_names(
        evidence_researcher, "codex"
    )


def test_all_research_agents_use_authenticated_codex_harness() -> None:
    spec = load(BUNDLE)
    agents = [spec, *spec.sub_agents]
    assert {agent.name for agent in agents} == {
        "research-director",
        "evidence-researcher",
        "hypothesis-scientist",
        "experiment-designer",
        "safety-reviewer",
        "results-analyst",
    }
    for agent in agents:
        assert agent.executor.config["harness"] == "codex"
        assert agent.executor.model == "gpt-5.6-sol"
        assert agent.executor.reasoning_effort == "high"


@pytest.mark.parametrize("payload", ["root", "super-cache"])
def test_codex_payload_default_cannot_override_the_agent_model(payload: str) -> None:
    project_config = tomllib.loads(
        (
            ROOT
            / "harness"
            / "adapters"
            / "codex"
            / payload
            / ".codex"
            / "config.toml"
        ).read_text(encoding="utf-8")
    )
    spec = load(BUNDLE)
    assert project_config["model"] == spec.executor.model == "gpt-5.6-sol"
    assert project_config["model_reasoning_effort"] == "high"


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
            assert tools == {}
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
    source = RUNTIME_CORE.read_text(encoding="utf-8")
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
    tool = RUNTIME_CORE.read_text(encoding="utf-8")
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
    runtime = runpy.run_path(str(RUNTIME_CORE))
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
    runtime = runpy.run_path(str(RUNTIME_CORE))
    with pytest.raises(ValueError, match="Omnigent agent name"):
        runtime["start_parallel_branch"](
            "branch-invalid-agent",
            "237394e077b64231b6ac6ea73ae73892",
            "child-session",
        )
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
            / "execution_marker_core.py"
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


def test_named_public_web_search_returns_auditable_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_module = runpy.run_path(
        str(
            BUNDLE
            / "agents"
            / "evidence-researcher"
            / "tools"
            / "python"
            / "search_public_web.py"
        )
    )
    html = b"""
    <a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fopenml.org%2Ft%2F59"
       class="result-link">OpenML Task 59</a>
    <td class="result-snippet">Official task metadata for Iris.</td>
    """

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit: int) -> bytes:
            assert limit > len(html)
            return html

        def geturl(self) -> str:
            return "https://lite.duckduckgo.com/lite/?q=OpenML+task+59"

    def fake_urlopen(request, timeout: float):
        assert request.full_url.startswith("https://lite.duckduckgo.com/lite/?q=")
        assert timeout == 5.0
        return Response()

    monkeypatch.setitem(search_module["_search"].__globals__, "urlopen", fake_urlopen)
    result = search_module["_search"]("OpenML task 59", 3, 5.0)
    assert result["schema"] == "public-web-search-result/v1"
    assert result["engine"] == "DuckDuckGo Lite"
    assert result["results"] == [
        {
            "title": "OpenML Task 59",
            "url": "https://openml.org/t/59",
            "snippet": "Official task metadata for Iris.",
        }
    ]


def test_public_source_inspection_returns_auditable_source_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspection_module = runpy.run_path(
        str(
            BUNDLE
            / "agents"
            / "evidence-researcher"
            / "tools"
            / "python"
            / "inspect_public_source.py"
        )
    )
    html = b"""
    <html><head><title>Official Iris metadata</title></head>
    <body><script>ignore me</script><h1>Iris</h1><p>150 rows and four features.</p></body></html>
    """

    class Headers:
        def get_content_type(self) -> str:
            return "text/html"

        def get_content_charset(self) -> str:
            return "utf-8"

    class Response:
        headers = Headers()
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit: int) -> bytes:
            assert limit > len(html)
            return html

        def geturl(self) -> str:
            return "https://archive.ics.uci.edu/dataset/53/iris"

    def fake_open(request, timeout: float):
        assert request.full_url == "https://archive.ics.uci.edu/dataset/53/iris"
        assert timeout == 5.0
        return Response()

    globals_ = inspection_module["_inspect"].__globals__
    monkeypatch.setitem(globals_, "_open_public_source", fake_open)
    monkeypatch.setitem(globals_, "_assert_public_http_url", lambda value: value)
    result = inspection_module["_inspect"](
        "https://archive.ics.uci.edu/dataset/53/iris", 5.0, 1000
    )
    assert result["schema"] == "public-source-inspection/v1"
    assert result["http_status"] == 200
    assert result["title"] == "Official Iris metadata"
    assert "150 rows and four features." in result["text_excerpt"]
    assert "ignore me" not in result["text_excerpt"]
    assert len(result["body_sha256"]) == 64


def test_public_source_inspection_rejects_private_hosts() -> None:
    inspection_module = runpy.run_path(
        str(
            BUNDLE
            / "agents"
            / "evidence-researcher"
            / "tools"
            / "python"
            / "inspect_public_source.py"
        )
    )
    with pytest.raises(ValueError, match="public"):
        inspection_module["_assert_public_http_url"]("http://127.0.0.1/private")


def test_public_source_inspection_rejects_redirects_to_private_hosts() -> None:
    inspection_module = runpy.run_path(
        str(
            BUNDLE
            / "agents"
            / "evidence-researcher"
            / "tools"
            / "python"
            / "inspect_public_source.py"
        )
    )
    handler = inspection_module["_PublicRedirectHandler"]()
    request = inspection_module["Request"]("https://example.org/source")
    with pytest.raises(ValueError, match="public"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1/private",
        )


def test_evidence_package_validator_rejects_the_failed_live_package_shape() -> None:
    validator_module = runpy.run_path(
        str(
            BUNDLE
            / "agents"
            / "evidence-researcher"
            / "tools"
            / "python"
            / "validate_evidence_package.py"
        )
    )
    invalid = {
        "schema": "evidence-package/v1",
        "evidence_package_id": "package-a",
        "question_id": "question-a",
        "objective_confirmation_digest": "a" * 64,
        "claims": [
            {
                "evidence_id": "claim-a",
                "claim_type": "external-fact",
                "claim": "A narrow claim.",
                "source_type": "official-documentation",
                "citation": {
                    "title": "Source",
                    "stable_url": "https://example.org/source",
                    "authors_or_organization": "Example",
                    "publisher_or_source": "Example",
                    "retrieved_at": "2026-10-04T00:00:00Z",
                    "license_or_access_note": "Public access.",
                    "verification_state": "verified-by-direct-inspection",
                },
                "support": {"text": "not a string"},
                "uncertainty": "A limitation.",
            }
        ],
        "conflicts": [],
        "coverage_gaps": [],
    }
    with pytest.raises(ValueError, match="citation fields"):
        validator_module["_validate"](json.dumps(invalid))


def test_evidence_package_validator_returns_canonical_digest() -> None:
    validator_module = runpy.run_path(
        str(
            BUNDLE
            / "agents"
            / "evidence-researcher"
            / "tools"
            / "python"
            / "validate_evidence_package.py"
        )
    )
    package = {
        "schema": "evidence-package/v1",
        "evidence_package_id": "package-a",
        "question_id": "question-a",
        "objective_confirmation_digest": "a" * 64,
        "claims": [
            {
                "evidence_id": "claim-a",
                "claim_type": "external-fact",
                "claim": "A narrow claim.",
                "source_type": "official-documentation",
                "citation": {
                    "title": "Source",
                    "url": "https://example.org/source",
                    "authors_or_organization": "Example",
                    "publisher_or_source": "Example",
                    "retrieved_at": "2026-10-04T00:00:00Z",
                    "license_or_access_note": "Public access.",
                    "verification_state": "verified",
                },
                "support": "A directly inspected field.",
                "uncertainty": "A limitation.",
            }
        ],
        "conflicts": [],
        "coverage_gaps": [],
    }
    result = validator_module["_validate"](json.dumps(package))
    assert result["schema"] == "evidence-package-validation/v1"
    assert result["valid"] is True
    assert result["evidence_package_id"] == "package-a"
    assert result["claim_count"] == 1
    assert len(result["record_digest"]) == 64
