from __future__ import annotations

from pathlib import Path

from omnigent.spec import load


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "agents" / "research-director"


def test_omnigent_bundle_loads() -> None:
    spec = load(BUNDLE)
    assert spec.name == "research-director"


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
        "experiment-result/v1",
        "updated-decision/v1",
    ):
        assert schema in contracts


def test_bundle_has_no_harness_dependency_or_runtime_call() -> None:
    forbidden = (
        "import memory_harness",
        "from memory_harness",
        "import orchestrator_harness",
        "from orchestrator_harness",
        "operator_launch",
    )
    inspected = [ROOT / "pyproject.toml", *BUNDLE.rglob("*.yaml")]
    for path in inspected:
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), path


def test_project_has_no_mongodb_dependency() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "mongodb" not in project
    assert "pymongo" not in project
    assert "langchain-mongodb" not in project

