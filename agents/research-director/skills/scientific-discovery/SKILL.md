---
name: scientific-discovery
description: Coordinate a bounded scientific loop from a measurable question through cited evidence, falsifiable hypotheses, competing experiments, independent safety review, human approval, and a result-driven next decision.
---

# Scientific discovery coordination

Use this skill for research questions that should produce a testable hypothesis
and a reproducible computational experiment.

## Procedure

1. Freeze one question, one measurable outcome, and one primary metric.
2. Delegate evidence collection before hypothesis generation. Require stable
   citations and surface contradictory evidence.
3. Delegate hypothesis generation using evidence IDs rather than unsourced
   background assertions.
4. Delegate experiment design. Require at least two revealing tests and record
   why one is selected.
5. Delegate independent safety and rigor review. Do not let the experiment
   designer approve its own plan.
6. Use `request_experiment_approval` to bind the exact selected experiment
   digest, present the complete approval packet, and stop.
7. After actual human approval, stage the task. Launch only after explicit
   digest confirmation and only through the integrated harness tool.
8. Persist the complete result, delegate independent analysis, and produce an
   updated scientific decision.

## Quality rules

- Prefer a small experiment that can disconfirm the hypothesis over a broad
  demonstration that cannot.
- Predeclare controls, metrics, thresholds, data identity, seeds, time, and
  cost.
- Keep observations separate from interpretations.
- Report uncertainty and negative results.
- Never treat agent consensus as scientific validation.
- Never claim discovery acceleration without a matched baseline and disclosed
  formula.
