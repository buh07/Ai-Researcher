# AI Researcher

An Omnigent-based top-level coordinator for evidence-driven, reproducible
scientific discovery.

This repository currently contains only the coordination layer. It deliberately
does **not** import or connect to the existing multi-agent harness. That harness
will be integrated later through the boundary described in
[`docs/FUTURE_HARNESS_INTEGRATION.md`](docs/FUTURE_HARNESS_INTEGRATION.md).

## What is included

- Omnigent 0.16.0 pinned as the orchestration framework
- One top-level `research-director` agent
- Five bounded specialist agents:
  - `evidence-researcher`
  - `hypothesis-scientist`
  - `experiment-designer`
  - `safety-reviewer`
  - `results-analyst`
- A scientific-discovery coordination skill
- Structured handoff contracts
- Session cost and tool-call guardrails
- Bundle validation and boundary tests

## Current workflow

```text
Question
  -> cited evidence package
  -> falsifiable hypothesis portfolio
  -> two or more experiment candidates
  -> safety review
  -> human approval request
  -> external/future experiment execution
  -> supplied result package
  -> independent analysis
  -> updated scientific decision
```

The coordinator must stop at the approval/execution boundary today. It may
analyze results supplied by a human, but it has no experiment runner and no
harness connection yet.

## Setup

Prerequisites:

- Python 3.12
- `uv`
- Credentials for an Omnigent-supported model provider

Install the pinned environment:

```bash
uv sync
```

Configure Omnigent for the model provider available on the machine:

```bash
uv run omnigent setup
```

Validate the complete agent image:

```bash
uv run python scripts/validate_bundle.py
uv run pytest
```

Launch the coordinator:

```bash
uv run omnigent run agents/research-director
```

Or start it with a bounded initial question:

```bash
uv run omnigent run agents/research-director \
  -p "Investigate whether evidence-guided experiment selection can reduce the number of trials needed on a fixed OpenML classification task. Stop before execution and return the approval packet."
```

## Coordination guarantees

The research director is instructed to:

1. Fix the question, measurable outcome, and constraints.
2. Delegate evidence collection before forming conclusions.
3. Keep sourced facts separate from generated hypotheses.
4. Require falsifiable predictions and competing explanations.
5. Obtain at least two experiment candidates.
6. Compare candidates by expected learning, feasibility, cost, time, and risk.
7. Send the selected experiment to an independent safety reviewer.
8. Stop for explicit human approval before execution.
9. Never claim an experiment ran unless an external result package is supplied.
10. Use a result to produce an updated decision and next experiment.

## Repository layout

```text
agents/research-director/
  config.yaml
  AGENTS.md
  skills/scientific-discovery/SKILL.md
  agents/
    evidence-researcher/
    hypothesis-scientist/
    experiment-designer/
    safety-reviewer/
    results-analyst/
docs/
  HANDOFF_CONTRACTS.md
  FUTURE_HARNESS_INTEGRATION.md
scripts/
  validate_bundle.py
tests/
  test_bundle.py
```

## Deliberate non-features

- No MongoDB or Atlas dependency
- No imported harness code
- No harness subprocess or CLI invocation
- No shared harness runtime state
- No experiment execution tool
- No database or long-term research memory yet
- No deployment configuration

These omissions keep the coordination layer stable while the external harness
continues to change.

