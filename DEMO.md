# Two-minute challenge demo

This script is terminal-first and evidence-first. Replace `<CHAIN>` with the
actual exported research-chain JSON and `<RUBRIC>` with the desired generated
rubric-map path. If no live chain exists, use the explicit fixture/unavailable
path in the final section and say so; never narrate it as a live run.

## Before the timer

From a clean checkout:

```bash
uv sync --frozen
uv run python scripts/validate_bundle.py
uv run pytest
(
  cd harness
  PYTHONPATH=. ../.venv/bin/python -m unittest discover \
    -s orchestrator_harness/tests -p 'test_*.py'
)
uv run python scripts/render_research_report.py <CHAIN> \
  --rubric-output <RUBRIC>
```

Confirm that the live chain contains actual agent/session identities, source
citations, timestamps, approvals, result/artifact digests, and limitations.
Check that any claimed parallel branches satisfy strict interval overlap. Open
the generated rubric JSON and leave the terminal report ready.

`<CHAIN>` is an exported run artifact, not a tracked sample. A clean checkout
can run all software checks and the explicit unavailable-evidence renderer, but
cannot reproduce a live provider run without human authority, external
credentials, local Harness configuration, and the separately retained runtime
artifacts.

## 0:00–0:20 — objective, significance, and human ownership

**Show:** `OBJECTIVE`.

**Say:** “Scientists lose time and compute choosing the next experiment while
evidence, failures, and provenance remain fragmented. Our human scientist owns
this objective, metric, dataset, risk tolerance, and execution scope. Omnigent
cannot silently replace them. This OpenML task is a bounded proxy for a larger
capability: testing more useful hypotheses per unit of research effort.”

Point to the attributable confirmation and feasibility checks. If they are
missing, point to `UNAVAILABLE` and stop the consequential path.

## 0:20–0:42 — genuine multi-agent orchestration

**Show:** `PARALLEL EVIDENCE` and `HYPOTHESIS`.

**Say:** “Omnigent routed independent evidence questions before reconciliation.
We count parallelism only when authoritative intervals overlap—not because a
configuration says async. Claims retain citations, conflicts, and gaps;
hypotheses remain labeled agent-generated and falsifiable.”

Show both branch intervals and the overlap calculation. `MET` additionally
requires distinct completed runtime invocation IDs, distinct producer sessions,
distinct nonempty cited evidence packages, and reconciliation of evidence from
every branch. Caller timestamps, queue time, shared evidence, incomplete work,
or merely `async: true` cannot prove parallelism. If any condition is absent,
say “parallel criterion unmet” and do not claim a speedup.

## 0:42–1:04 — experiment choice and independent safety

**Show:** `CANDIDATES`, then `SAFETY`.

**Say:** “The designer compared at least two experiments under declared
learning, feasibility, cost, time, and risk criteria. A separate safety reviewer
identified controls and prohibited actions. Neither role can approve execution.”

Show the selection and rejection rationales, not just the winning candidate.

## 1:04–1:24 — exact human approval and bounded execution

**Show:** `APPROVAL`, then `RESULT`.

**Say:** “The second human gate binds approval to the exact experiment digest.
Staging does not launch. Explicit launch plus an independent environment gate
are required. The harness executes within budget and returns measurements and
artifact identities; it makes no scientific decision.”

Point to the objective, experiment, approval, task-card, run, and artifact
digests. Show that dataset/metric, trials, wall time, cost, CPU compute,
read-only network access, artifact-only mutation, and risk constraints were
checked before staging. Never expose a credential. If the result is a fixture,
say “fixture” before discussing it.

## 1:24–1:44 — result-driven learning

**Show:** `DECISION`.

**Say:** “A separate results analyst interprets immutable measurements as
support, revise, reject, or inconclusive. The next experiment follows this
result and remaining uncertainty—it is not a preselected success story. A
negative result is still useful learning.”

Show the result reference, rationale, uncertainty, and next experiment.

## 1:44–2:00 — honest acceleration, creativity, and 10x path

**Show:** `ACCELERATION / 10X PATH`, then `<RUBRIC>`.

**Say:** “Our primary endpoint is trials to the preregistered threshold;
accuracy is the quality guard. We report matched trial and elapsed-time ratios
exactly, including failed attempts. An end-to-end claim requires source-digested
measurements of retrieval, planning, approval, preflight, agent/tool work,
evaluation, and ingestion for both arms. If those measurements are absent the
runner labels timing model-evaluation-only and blocks the claim. Censoring
produces a bound or not estimable—not an invented number. Observed evidence is
separate from our 10x path: repeat across tasks and seeds, automate safe
retrieval and validation, and preserve both human gates. Our creative artifact
is this deterministic learning receipt: an auditable chain from objective to
the next decision.”

Finish on the rubric-to-artifact map. Any absent live evidence must remain
`UNAVAILABLE` or `UNMET`.

## Operator lifecycle and artifact handoff

The live demo must show the actual sequence, not stop at launch:

1. The operator records the objective and later approval with
   `scripts/record_human_authority.py`; agents cannot write either authority.
2. The director calls `stage_approved_experiment`, then after a separate human
   confirmation calls `launch_approved_experiment` with a provider, model, and
   explicit provider options (`codex`: `reasoning_effort` + `service_tier`;
   `claude-code`: `effort`; `qwen-code`: `{}`).
3. The worker runs the exact approved matched experiment. The outcome is
   converted with `ExperimentOutcome.as_experiment_result`, including
   source-digested arm workflow telemetry but not a future decision latency. The director's
   `build_harness_result` returns the exact Harness `result/v1` envelope; the
   worker writes it unchanged as `RESULT.json`.
4. The director waits, explicitly reviews and accepts/rejects completion,
   rereads Harness-owned terminal evidence, and calls
   `ingest_harness_experiment_result`. Ingestion verifies the embedded
   scientific result and rehashes every `artifact:` reference relative to the
   supplied artifact base directory.
5. Only after accepted-result ingestion does the independent analyst produce
   `updated-decision/v1`. The journal adds an embedded, digest-addressed timing
   artifact using Harness's immutable `decided_at`/content hash and the journal
   completion boundary; the analyst cannot supply those measurements.
   `as_acceleration_summary` then binds the immutable result and decision and
   copies the verified latency/source digest without changing the result.
6. After analysis, decision, and acceleration records are journaled, call
   `get_learning_receipt(question_id, final=true)`, export the reconstructed
   chain and receipt into the submission artifact bundle, and render them:

```bash
uv run python scripts/render_research_report.py \
  artifacts/research-chain.json \
  --rubric-output artifacts/rubric-artifact-map.json
```

7. Retire accepted work with `retire_experiment`, or explicitly
   `force_stop_experiment` on timeout/cancellation, then call
   `shutdown_research_harness` with the exact confirmation phrase
   `SHUTDOWN RESEARCH HARNESS`.

These are Omnigent tools except for the explicitly named operator script and
renderer. Do not bypass them with direct Harness shell commands.

## Fixture/unavailable fallback

This fallback demonstrates only deterministic display and honest missing-data
handling:

```bash
printf '%s\n' '{}' > /tmp/ai-researcher-empty-chain.json
uv run python scripts/render_research_report.py \
  /tmp/ai-researcher-empty-chain.json \
  --rubric-output /tmp/ai-researcher-rubric.json
cat /tmp/ai-researcher-rubric.json
```

State verbatim: **“This is a renderer smoke test. It is not a live Omnigent
trace, a completed experiment, or acceleration evidence.”**

## Rehearsal acceptance

Run the documented live path twice from fresh runtime state. A rehearsal passes
only when it needs no hand-edited state and shows both human gates, data/license
feasibility, real overlap or explicit `UNMET`, cited evidence, two candidates,
independent safety, bounded execution, immutable result provenance,
result-driven next action, honest acceleration/censoring, limitations, and the
rubric map. Record actual commands, Git/dependency identity, duration, and any
skips in the submission inventory.
