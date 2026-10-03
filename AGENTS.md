# Repository operating rules

This repository contains the standalone Omnigent coordination layer for an
agentic scientific-discovery project.

- Keep Omnigent as the sole top-level research orchestrator.
- Do not import, vendor, launch, or otherwise connect the external multi-agent
  harness until the user explicitly requests that integration.
- Keep future harness integration behind a documented adapter boundary.
- Preserve the distinction between sourced facts, agent hypotheses, observed
  experimental results, and interpretations.
- Require structured handoffs with stable schema names and explicit source IDs.
- Never fabricate citations, measurements, approvals, or completed experiments.
- Require human approval before any consequential experiment is executed.
- Keep credentials and runtime artifacts out of Git.
- Pin external framework versions and validate the complete agent bundle after
  changing configuration, prompts, skills, or sub-agent names.
- Run `uv run python scripts/validate_bundle.py` and `uv run pytest` before
  reporting a coordination-layer change complete.

