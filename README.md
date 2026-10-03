# AI Researcher

AI Researcher is an Omnigent-orchestrated system for evidence-driven,
reproducible scientific discovery. Omnigent coordinates the scientific loop;
the integrated harness executes only exact, human-approved computational
experiments.

The active runtime is local-first. Scientific handoffs and execution bindings
are stored in SQLite, and the project has no MongoDB or Atlas dependency.

## Architecture

```text
Human scientist
  -> Omnigent research director
       -> evidence researcher
       -> hypothesis scientist
       -> experiment designer
       -> independent safety reviewer
       -> results analyst
  -> digest-bound human approval
  -> research adapter + SQLite journal
  -> bounded harness lane
  -> immutable result
  -> updated scientific decision
```

Authority is deliberately split:

- Omnigent owns research sequencing, specialist delegation, and scientific
  decisions.
- The human owns consequential approval.
- `ai_researcher.harness_adapter` owns translation and identity binding.
- The harness owns execution lifecycle, process isolation, review evidence,
  and cleanup.
- The results analyst interprets measurements without changing them.

## Included components

- Omnigent 0.16.0 and the `research-director` agent bundle
- Five bounded scientific specialists
- Local Omnigent tools for journal, approval, staging, launch, status, and
  result ingestion
- Immutable scientific handoff validation
- SQLite research journal
- Portable multi-provider execution harness
- Local memory, provenance, task-card, approval, and lifecycle contracts
- Vendored EverOS local-memory source with its license and notice retained
- Tool-call and session-cost guardrails

## Scientific workflow

```text
Question
  -> cited evidence
  -> falsifiable hypotheses
  -> at least two candidate experiments
  -> independent safety review
  -> selected-specification digest
  -> human approval
  -> staged harness task
  -> explicit launch confirmation
  -> reproducible result
  -> independent analysis
  -> updated decision and next experiment
```

Staging does not launch. Launch requires the exact approval digest and the
independent `AI_RESEARCHER_ENABLE_EXECUTION=1` environment gate.

## Setup

Prerequisites:

- Python 3.12
- `uv`
- Credentials for an Omnigent-supported model provider
- A configured provider CLI for live harness execution

Install the pinned environment:

```bash
uv sync
uv run omnigent setup
```

Validate the agent and integration layer:

```bash
uv run python scripts/validate_bundle.py
uv run pytest
```

Run the focused imported-harness checks:

```bash
cd harness
PYTHONPATH=. ../.venv/bin/python -m unittest \
  orchestrator_harness.tests.test_package_metadata \
  orchestrator_harness.tests.test_task_card_contract \
  orchestrator_harness.tests.test_memory_handoff
```

Launch the research director:

```bash
uv run omnigent run agents/research-director
```

Example prompt:

```text
Investigate whether evidence-guided experiment selection can reduce the number
of trials needed on a fixed OpenML classification task. Prepare a cited,
digest-bound approval packet and stop for my decision before staging or launch.
```

## Enabling execution

Local harness configuration and execution are optional. Follow
[`docs/HARNESS_INTEGRATION.md`](docs/HARNESS_INTEGRATION.md) to create ignored
local configuration and initialize the runtime.

The coordinator can always plan, review, journal, and stage an approved task.
It cannot launch until the operator explicitly sets:

```bash
export AI_RESEARCHER_ENABLE_EXECUTION=1
```

## Repository layout

```text
agents/research-director/       Omnigent PI and specialists
  tools/python/                 journal and harness tools
src/ai_researcher/              records, SQLite journal, adapter
harness/                        integrated portable execution harness
docs/HANDOFF_CONTRACTS.md       scientific record schemas
docs/HARNESS_INTEGRATION.md     authority and execution boundary
scripts/validate_bundle.py      agent-image validation
tests/                          project integration tests
```

Runtime state, credentials, local harness configuration, staged task cards,
and experiment artifacts are intentionally excluded from Git.
