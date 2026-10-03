# Repository operating rules

This repository contains the integrated Omnigent coordination and bounded
experiment-execution layers for an agentic scientific-discovery project.

- Keep Omnigent as the sole top-level research orchestrator.
- Keep all Omnigent-to-harness traffic behind `ai_researcher.harness_adapter`.
- Omnigent owns scientific sequencing; the harness owns only bounded execution
  lifecycle and may not make scientific or approval decisions.
- Preserve the distinction between sourced facts, agent hypotheses, observed
  experimental results, and interpretations.
- Require structured handoffs with stable schema names and explicit source IDs.
- Never fabricate citations, measurements, approvals, or completed experiments.
- Require human approval before any consequential experiment is executed.
- Require the exact approved experiment digest at both staging and launch.
- Keep credentials and runtime artifacts out of Git.
- Pin external framework versions and validate the complete agent bundle after
  changing configuration, prompts, skills, or sub-agent names.
- Run `uv run python scripts/validate_bundle.py`, `uv run pytest`, and the
  focused harness suite documented in the README before reporting an
  integration change complete.
