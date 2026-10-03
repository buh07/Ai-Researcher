from __future__ import annotations

from pathlib import Path

from omnigent.spec import load


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "agents" / "research-director"


def test_omnigent_bundle_loads() -> None:
    spec = load(BUNDLE)
    assert spec.name == "research-director"
    assert {tool.name for tool in spec.local_tools} == {"research_runtime"}


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
    for schema in (
        "research-question/v1",
        "evidence-package/v1",
        "hypothesis-portfolio/v1",
        "experiment-candidates/v1",
        "safety-review/v1",
        "human-approval/v1",
        "experiment-result/v1",
        "updated-decision/v1",
    ):
        assert schema in contracts


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
