# AI Researcher

AI Researcher is an **Omnigent-orchestrated, human-governed** system for
reproducible agentic scientific discovery. Omnigent coordinates a structured
scientific loop; the integrated harness may execute only an exact,
human-approved computational experiment. SQLite records provenance locally,
and the active project has no MongoDB or Atlas dependency.

> **Evidence status:** the repository contains the coordination, integrity, and
> reporting implementation, including the complete bounded Harness lifecycle.
> It does **not** contain a completed live-provider/OpenML result, an attributable
> human confirmation, measured live overlap, or two clean live rehearsals.
> Runtime records and artifacts are intentionally Git-ignored. A fixture proves
> mechanics, not scientific performance. Never present fixture output as a live
> discovery or as evidence of 10x acceleration.

## Challenge thesis

The proposed, human-confirmable proxy question is:

> On one fixed OpenML tabular classification task, can provenance-gated,
> evidence-guided experiment selection reach a predeclared validation score
> with fewer model-training trials than a matched fixed search?

Experiment selection is a practical bottleneck: researchers spend scarce time
and compute deciding which test to run next, while evidence, failures, and
provenance are often disconnected. A trustworthy reduction in trials would
benefit computational scientists, small laboratories, reproducibility teams,
and research funders. The single-task proxy is **not** itself a scientific
breakthrough. Its larger potential is a validated decision layer that helps
scientists test more useful hypotheses per unit of time and compute across
scientific domains.

The creative contribution is not unrestricted autonomy. It is a digest-addressed
**learning receipt** connecting a human-owned objective, independent evidence,
compared hypotheses and experiments, safety review, exact approval, immutable
measurements, and the next decision. Independent evidence branches count as
parallel only when authoritative time intervals actually overlap. Missing
proof is shown as `UNMET` or `UNAVAILABLE`.

## Architecture and authority

```text
Human scientist
  |-- confirms objective + metric + dataset + risk tolerance + execution scope
  `-- approves the exact selected-experiment digest and explicitly launches it
            |
            v
Omnigent research director (agents/research-director/)
  |-- evidence-researcher     external claims and citations
  |-- hypothesis-scientist    falsifiable hypotheses
  |-- experiment-designer     comparison and selection recommendation
  |-- safety-reviewer         independent safety judgment
  `-- results-analyst         interpretation of immutable measurements
            |
            v
src/ai_researcher/            validation, identities, journal, approval binding
            |
            v
harness/                      bounded execution; no scientific decisions
```

Omnigent owns workflow routing. Specialists own distinct scientific judgments.
The human owns the research objective and consequential actions. The integrity
layer binds records and approvals. The harness executes; it does not choose or
interpret an experiment.

## Quickstart

Prerequisites are Python 3.12, [`uv`](https://docs.astral.sh/uv/), credentials
for an Omnigent-supported model for a live agent run, and a configured provider
CLI only if bounded harness execution is requested.

```bash
git clone https://github.com/buh07/Ai-Researcher.git
cd Ai-Researcher
uv sync
uv run python scripts/validate_bundle.py
uv run pytest
```

Run the complete imported-harness unit suite from its own package root:

```bash
TMPROOT=$(mktemp -d /tmp/ai-researcher-harness-tests.XXXXXX)
(
  trap 'rm -rf "$TMPROOT"' EXIT
  cd harness
  TMPDIR="$TMPROOT" TEMP="$TMPROOT" TMP="$TMPROOT" \
    PYTHONPATH=. ../.venv/bin/python -m unittest discover \
      -s orchestrator_harness/tests -p 'test_*.py'
)
```

No test writes `harness/local-config/harness-config.json`; local provider
configuration is operator-owned and ignored. Capture the exact Git commit,
`uv.lock` digest, commands, durations, and skips separately for a submission.
The node-local temporary directory avoids NFS delayed-delete races during test
cleanup; it does not change the code or test selection.

### Hermetic experiment smoke test

The matched runner requires all five human-owned scope fields. This command
uses the checked-in synthetic fixture and writes only to `/tmp`:

```bash
uv run python scripts/run_matched_experiment.py \
  --mode fixture \
  --objective "Test a bounded evidence-guided selection proxy" \
  --primary-metric trials_to_threshold \
  --openml-task-id 59 \
  --dataset-identifier synthetic-proxy-openml-task-59-v1 \
  --openml-dataset-id 61 \
  --openml-dataset-version 1 \
  --dataset-digest e47234e8ba0a4c512a49e895747d8f51f9d8e9d4d75f405070e9d279589063a4 \
  --risk-tolerance "low; local CPU only" \
  --execution-scope-json \
    '{"max_trials":8,"max_runtime_minutes":2,"max_cost_usd":0,"compute":"local CPU","network_access":"none","mutation_permissions":["artifact directory only"]}' \
  --data-governance-json \
    '{"license_status":"VERIFIED","license_evidence":"Original synthetic fixture under CC0-1.0.","privacy_status":"VERIFIED","privacy_evidence":"Synthetic flower measurements contain no people.","verified_by":"fixture maintainer","verified_at":"2026-10-03T00:00:00Z"}' \
  --confirmed-by "$USER" \
  --confirmed-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --artifact-dir /tmp/ai-researcher-fixture-artifacts \
  --output /tmp/ai-researcher-fixture-result.json
```

This proves runner and metric mechanics only. It is not a live OpenML result or
scientific evidence. Live mode is separately fail-closed: it requires
`AI_RESEARCHER_ENABLE_EXECUTION=1`, the journal path, and exact objective,
experiment, approval, and task-card digests matching a `LAUNCHED` binding.
`trials_to_threshold` is the primary endpoint; held-out `accuracy` is the
secondary quality/non-inferiority metric. They are not interchangeable.

### Deterministic terminal report

Render a supplied research-chain or `learning-receipt/v1` JSON object. This
command never fills missing sections or infers that expected artifacts exist.

```bash
uv run python scripts/render_research_report.py \
  artifacts/research-chain.json \
  --rubric-output artifacts/rubric-artifact-map.json
```

The fixed view is:

```text
Objective | Parallel evidence | Hypothesis | Candidates | Safety | Approval
Result | Decision | Acceleration / 10x path
```

For a safe smoke test with deliberately unavailable evidence:

```bash
printf '%s\n' '{}' > /tmp/ai-researcher-empty-chain.json
uv run python scripts/render_research_report.py \
  /tmp/ai-researcher-empty-chain.json \
  --rubric-output /tmp/ai-researcher-rubric.json
```

Rubric status is never guessed. A chain may supply `rubric_evidence` entries
with one of `MET`, `PARTIAL`, `UNMET`, or `UNAVAILABLE` and concrete artifact
paths. The generated `rubric-artifact-map/v1` separately lists expected paths;
those inventory targets do not prove completion.

## Live Omnigent path, human gates, and provider launch

Set up Omnigent, then launch the current bundle:

```bash
uv run omnigent setup
uv run omnigent run agents/research-director
```

A suitable opening request is:

```text
Propose a bounded investigation of evidence-guided experiment selection. Stop
and ask me to confirm the exact research objective, primary metric, dataset,
risk tolerance, and consequential execution scope before treating the
objective as active. Verify data/API access, license/privacy, identity, and
compute feasibility. Prepare cited evidence, at least two experiment
candidates, and an independent safety review. Stop again for exact-digest human
approval before staging, and never launch without my explicit decision.
```

The two non-substitutable human gates are:

1. **Objective confirmation:** an attributable human confirms objective,
   primary metric, dataset, risk tolerance, and execution scope. Any material
   change requires reconfirmation. The agent-facing tool refuses this record;
   an operator records it with `scripts/record_human_authority.py` and the exact
   question or superseded-objective parent digest.
2. **Consequential execution:** after independent safety review, a human
   approves the exact objective/experiment digest pair through the same
   operator-only script. Staging still does not launch. Launch requires the
   human to repeat that approval digest, the independently set environment
   gate, and explicit provider/model/options.

The operator-only authority command has one fixed shape; the record JSON must
conform to [`docs/HANDOFF_CONTRACTS.md`](docs/HANDOFF_CONTRACTS.md):

```bash
uv run python scripts/record_human_authority.py \
  --journal runtime/research-journal.sqlite3 \
  --record /path/to/objective-confirmation-or-approval.json \
  --parent-digest <exact-question-or-review-parent-digest> \
  --human-id <attributable-human-id> \
  --human-session-id <attributable-confirmation-session-id>
```

`launch_approved_experiment` validates provider options before mutating Harness
state. Pass an explicit JSON object:

| Provider | Required `provider_options_json` |
|---|---|
| `codex` | `{"reasoning_effort":"high","service_tier":"priority"}` (`launcher` may additionally be `codex` or `ollama`) |
| `claude-code` | `{"effort":"high"}` |
| `qwen-code` | `{}` |

There is no silent provider default. Provider credentials and executables are
external prerequisites, and the model identifier is always explicit.

Follow [`docs/HARNESS_INTEGRATION.md`](docs/HARNESS_INTEGRATION.md) to create
ignored local configuration. Enable execution only after both gates and local
inspection:

```bash
export AI_RESEARCHER_ENABLE_EXECUTION=1
```

Do not put provider credentials, private source content, local configuration,
or runtime artifacts in Git.

### Complete bounded execution lifecycle

The director's `research_runtime` bundle implements the full lifecycle without
an alternate shell path:

1. `stage_approved_experiment` creates and hashes the bounded task card.
2. `launch_approved_experiment` bootstraps and launches the exact staged lane.
3. `get_harness_experiment_status` and `wait_for_experiment` inspect/wait for
   the exact lane and run identity.
4. The launched worker runs the approved live matched experiment, includes
   source-digested arm telemetry, calls `ExperimentOutcome.as_experiment_result`
   **without** a not-yet-existent decision latency, then uses
   `build_harness_result` and writes the returned object unchanged as its
   `RESULT.json`.
5. `review_experiment_completion` records a separate explicit ROOT review and
   acceptance/rejection. Scientific acceptance requires `PASS`; `FAIL` and
   `BLOCKED` can only be rejected, and an inconclusive `UNKNOWN` review must be
   repeated. No result is auto-accepted or force-accepted.
6. `read_experiment_terminal_evidence` rereads Harness-owned evidence and
   `ingest_harness_experiment_result` revalidates authority, the exact reviewed
   `scientific_result`, and every local artifact digest before journaling it.
   Ingestion also preserves the immutable Harness acceptance timestamp/hash.
7. Only then does the independent results analyst produce
   `updated-decision/v1`. The journal—not the analyst—adds a digest-addressed
   timing artifact from the stored acceptance boundary to journal insertion.
   `ExperimentOutcome.as_acceleration_summary` accepts that immutable decision,
   derives decision latency from it, and binds both the result and decision
   digests. The accepted result is never rewritten.
8. `retire_experiment` retires an accepted lane using its acceptance record;
   `force_stop_experiment` handles and retires a stuck/cancelled run, and
   `read_experiment_cancellation_evidence` revalidates its durable cleanup
   receipt. Exact-run cleanup remains available for an ambiguous `LAUNCHING`
   run and after objective supersession, without restoring execution or result
   authority. Finally,
   `shutdown_research_harness` requires the exact phrase
   `SHUTDOWN RESEARCH HARNESS`.

For live runner conversion, `scripts/run_matched_experiment.py --mode live`
requires `--journal-path`, `--experiment-id`, and the four exact authority
digests; caller overrides of approved threshold, seed, trial/time budget, cost,
or margin are rejected. Its `--arm-measurements-json` value must contain
`baseline` and `evidence_guided` observations. Each arm supplies measured
`retrieval_seconds`, `planning_seconds`, `approval_seconds`,
`preflight_seconds`, `agent_tool_seconds`, optional observed interventions/cost/
tokens, and a SHA-256 `source_digest`. Missing telemetry remains unavailable,
never zero. Generated trial logs and the matched-result summary are written to
the approved artifact directory and are rehashed during result ingestion.

## What counts as acceleration

The primary endpoint is predeclared `trials_to_threshold` under matched data,
splits, seeds, budgets, and compute. Failed or timed-out attempts count. Held-out
`accuracy` is the quality/non-inferiority guard, not the primary endpoint. When
both arms have source-digested workflow telemetry, elapsed time includes
retrieval, planning, approval, preflight, agent/tool work, model evaluation, and
result ingestion and is labeled `end-to-end-arm-workflow`. If either arm lacks
that telemetry, the runner labels timing `model-evaluation-only`, records
`overhead_included=false`, and prohibits an overall discovery-speed claim.
Censored arms do not become invented finite ratios, and a trial-efficiency gain
is not called faster discovery when elapsed-time speedup is at most 1.
Killed timeouts and fatal evaluator exits report compute as unavailable rather
than zero or a partial measurement; `compute_unavailable` blocks acceleration
claims.

An observed ratio on one task must be reported exactly and separately from a
path-to-10x forecast. Approaching 10x would require a costly baseline bottleneck,
useful early evidence, safe parallel retrieval and validation, structured and
cached sources, reliable providers, automation of provenance/result parsing,
and no loss of quality or safety. It still requires repeated seeds, multiple
tasks, ablations, prospective domain runs, and uncertainty estimates. Human
objective ownership and consequential approval remain intentionally serial.

## Real, fixture, and unavailable evidence

| Evidence type | What it can establish | What it cannot establish |
|---|---|---|
| Unit/hermetic fixture | Validation, all current contracts, digest, journal, gate, formula, lifecycle, and rendering behavior | Live Omnigent delegation, provider execution, OpenML access, or scientific improvement |
| Live agent trace | Actual specialist delegation and, with timestamps, overlap | Experiment quality or acceleration without matched results |
| Live bounded experiment | Measurements for the exact approved task | General superiority or a 10x claim from one dataset |
| Forecast/sensitivity scenario | Conditions worth testing | Observed acceleration |

See [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) for the full claim boundary and
[`docs/SUBMISSION_CHECKLIST.md`](docs/SUBMISSION_CHECKLIST.md) for the evidence
inventory. The two-minute operator script is in [`DEMO.md`](DEMO.md).

## Repository layout

```text
agents/research-director/           Omnigent director and five specialists
  tools/python/research_runtime.py  narrow journal/approval/execution tools
src/ai_researcher/                  records, SQLite journal, adapter, reporting
harness/                            integrated portable execution harness
scripts/validate_bundle.py          current agent-bundle validation
scripts/run_matched_experiment.py   explicit fixture/live matched runner
scripts/render_research_report.py   deterministic receipt/rubric renderer
scripts/record_human_authority.py   operator-only objective/approval writer
docs/HANDOFF_CONTRACTS.md           scientific record contracts
docs/HARNESS_INTEGRATION.md         authority and execution boundary
docs/LIMITATIONS.md                 evidence and claim limits
docs/SUBMISSION_CHECKLIST.md        rubric-aligned submission inventory
tests/                              project unit and integration checks
```

Runtime state, credentials, local harness configuration, staged task cards,
OpenML caches, and experiment artifacts are intentionally excluded from Git.
