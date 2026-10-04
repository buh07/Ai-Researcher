# Agentic Scientific Discovery: 12-Hour Implementation Plan

## Purpose and source of truth

This repository-relative plan turns AI Researcher into a complete Agentic
Scientific Discovery challenge submission. It is governed by
[`challenge_brief.pdf`](challenge_brief.pdf) and requires no external source
tree or machine-specific path.

The repository already provides the foundation:

- `agents/research-director/` contains the Omnigent research director and five
  specialist agents.
- `src/ai_researcher/` contains scientific record validation, append-only
  scientific records, mutable execution-binding projections, and the harness
  adapter.
- `harness/` contains the bounded multi-provider execution harness.
- `tests/` contains bundle and research-integration coverage.

### Current implementation baseline

This table distinguishes checked-in capability from work still required by this
plan. “Implemented” does not mean demonstrated in a live challenge run.

| Area | Current checkout | Still required for the submission |
|---|---|---|
| Omnigent bundle | `agents/research-director/` defines a director and five specialists, pins `omnigent==0.16.0`, enforces operator-only authority, and verifies provider-owned session exports for parallel evidence. | Capture a live provider-backed session with attributable identities and real overlap. |
| Scientific contracts | `src/ai_researcher/records.py` validates thirteen immutable record schemas documented in `docs/HANDOFF_CONTRACTS.md`; the learning receipt is a deterministic projection rather than a fourteenth mutable record. | Populate the contracts with real run evidence; do not count fixture records as challenge evidence. |
| Journal | `src/ai_researcher/journal.py` keeps scientific `records` and `record_links` append-only, validates cross-record identity/provenance, proves strict parallel overlap, reconstructs the receipt, and keeps `experiment_bindings` as a mutable lifecycle projection. | Retain and export the real journal/artifacts for the submission. Legacy incomplete authority remains read-only and fails closed for execution. |
| Approval/execution boundary | Operator-only objective/approval recording, passing preflight, exact objective/experiment/task-card binding, separate staging/launch, explicit provider options, and `AI_RESEARCHER_ENABLE_EXECUTION` are implemented. | Obtain real human confirmations and exercise every gate in the live path. |
| Harness | `HarnessAdapter` implements launch, status/wait, result-envelope conversion, explicit completion review, Harness-owned terminal-evidence readback, verified ingestion, force-stop, retirement, and shutdown. | Configure an external provider locally and retain one accepted bounded run; credentials/configuration remain uncommitted. |
| Scientific demonstration | Task 59/dataset 61 live retrieval, the CC0 synthetic fixture, matched baseline/guided runner, end-to-end telemetry input, acceleration/scaling analysis, receipt/reporting, `DEMO.md`, limitations, and rubric inventory are implemented and tested. | A live OpenML result, final result-driven decision/receipt, rubric evidence, and two clean live rehearsals are still externally required. |

This is an **implementation baseline**, not a claim of completed challenge
evidence. The checkout intentionally contains no human authority record,
provider credential, live Omnigent trace, measured live overlap, accepted
OpenML result, or rehearsal capture. Those items cannot be manufactured by a
test or committed fixture.

The **12-hour window is our internal delivery budget**, not the challenge's
published time limit. It allocates:

- **7 hours 30 minutes for implementation and release-blocking fixes**
- **4 hours 30 minutes for unit, integration, regression, live-run, and demo
  validation**

The target is a convincing, reproducible discovery loop—not a production
platform or a claim that a single benchmark is itself a major discovery.

## Required challenge outcome

The submission must visibly complete:

> Human-confirmed question -> cited evidence -> falsifiable hypothesis ->
> candidate experiments -> selected experiment -> independent safety review ->
> human approval -> measured result -> updated decision

It must also show:

1. Omnigent visibly coordinating multiple purposeful specialists.
2. Structured, journaled handoffs rather than only conversational summaries.
3. At least two candidate experiments, compared on expected learning,
   feasibility, cost, time, and risk before the planner recommends one.
4. At least two independent bounded evidence searches or hypothesis evaluations
   with recorded temporal overlap. Serial branches remain useful but do not
   satisfy or earn a parallel-discovery claim.
5. A reproducible computational experiment with matched controls.
6. A result that changes the next scientific decision, including a negative or
   inconclusive result.
7. Traceable support for **every factual claim**: external citations for
   literature/dataset facts, immutable run and artifact references for measured
   facts, and evidence IDs for the facts that motivate hypotheses.
8. Preserved uncertainty, controls, limitations, provenance, and source links.
9. Human ownership of the research objective and human approval of the exact
   consequential execution scope.
10. An honestly measured discovery-acceleration result, even when below 10x,
    plus an analysis of what would be required to approach 10x at scale.
11. A creative contribution that strengthens rigor: a digest-bound **learning
    receipt** connecting the objective, evidence, rejected alternatives,
    approval, result, and next experiment.
12. A two-minute demonstration backed by repository artifacts and run evidence.

## Authority model and mandatory human objective gate

The human scientist owns the scientific objective. The research director may
draft or clarify a question, but cannot silently select a fallback question,
dataset, metric, or risk posture.

Before decision-bearing evidence collection, display an objective-confirmation
packet and obtain explicit, attributable human confirmation of:

1. **Research objective**—the focused question and intended scientific use.
2. **Primary metric**—the single predeclared main comparison.
3. **Dataset**—the exact task/dataset identifier, version, and digest or
   pre-download identity.
4. **Risk tolerance**—allowed risk, prohibited actions, privacy constraints,
   and acceptable failure modes.
5. **Consequential execution scope**—maximum trials, time, compute, network,
   cost, and mutation permissions.

This is separate from experiment approval. Objective confirmation authorizes
planning against a fixed target; it does not authorize staging or execution. A
later `human-approval/v1` authorizes only the exact selected-experiment digest.
Launch remains a separate action and requires both explicit confirmation of
that digest and `AI_RESEARCHER_ENABLE_EXECUTION=1`.

If confirmation is absent after 15 minutes, the team may prepare the default
proposal below for the human, but must not activate it. No agent or timer can
confirm it on the human's behalf.

### Objective-confirmation identity and downstream binding

Objective confirmation must be an immutable, attributable record whose payload
contains the exact `research-question/v1` digest plus the confirmed dataset
identity/digest, primary metric, risk tolerance, and resource/network/mutation
scope. Its `objective_confirmation_digest` is the SHA-256 of canonical JSON
excluding the digest field itself.

That digest is a required authority token throughout the chain:

1. `research-question/v1` is recorded first; objective confirmation binds its
   exact `record_digest`.
2. `experiment-candidates/v1` carries the same
   `objective_confirmation_digest`, and every candidate must fit the confirmed
   dataset, metric, risk, and resource scope.
3. `human-approval/v1` binds both the selected `experiment_digest` and the same
   `objective_confirmation_digest`; experiment approval cannot silently expand
   the earlier objective scope.
4. `HarnessAdapter.prepare` validates all three bindings before staging and
   copies the objective-confirmation digest into the generated task card.
5. The immutable experiment/approval identity in the journal binding and every
   later result/decision link traces back to that digest. Launch revalidates the
   staged task-card digest and authority chain rather than trusting a caller's
   experiment ID alone.

Absent, unknown, stale, or mismatched objective digests fail closed at candidate
acceptance, approval request, staging, and launch. A candidate that exceeds any
confirmed permission or budget is **overscope** and cannot be cured by a safety
review or broader experiment approval. Any change to the question, primary
metric, dataset/version/digest, risk tolerance, or consequential scope requires
new human objective confirmation; all dependent candidates, safety review,
experiment approval, adapter preparation, and task card must then be regenerated
and re-approved. Narrowing runtime use below the confirmed maxima does not
require reconfirmation if it leaves the scientific question, metric, dataset,
and controls unchanged and is recorded explicitly.

Staleness is explicit, not based on “latest row”: a reconfirmation record names
the prior confirmation digest in `supersedes_objective_confirmation_digest`.
Once that edge is journaled, the superseded digest is invalid for any new
approval, staging, or launch. Already running work is stopped or quarantined for
human disposition; it is never silently adopted by the new objective.

## Scientific significance and breakthrough potential

### Why this bottleneck matters

In computational science, generating candidates is often easier than choosing
the next discriminating experiment while retaining enough provenance to trust
the conclusion. Unproductive trials consume compute and scientist time, while
weak links among literature, hypotheses, parameters, and results prevent teams
from learning reliably from failure.

The default vertical slice tests a narrow proxy for this bottleneck: whether
evidence-guided selection reaches a predeclared validation target with fewer
model-training trials than a fixed baseline under matched conditions. This is
a test of **information gained per experiment**, not a claim that tabular
classification is Nobel-level science.

### Who benefits

- Computational scientists selecting among costly experiments.
- Principal investigators deciding how to allocate scarce compute.
- Reviewers and collaborators reconstructing evidence and controls.
- Safety and governance teams requiring independent review and exact human
  authorization before consequential execution.

### Larger breakthrough enabled by scaling

If it survives multi-dataset and multi-domain validation, the same
provenance-gated selection loop could reduce expensive simulations, screens, or
wet-lab candidates needed to falsify weak hypotheses. The larger opportunity is
an auditable active-learning layer for science: specialists search and propose
in parallel while consequential actions remain bound to evidence, budgets,
safety review, and human intent.

The submission must label this as an enabling hypothesis and future validation
path. A result on one OpenML task supports only a scoped finding.

## Judging-rubric alignment

| Weight | Criterion | Planned evidence and acceptance signal |
|---:|---|---|
| 30% | Omnigent orchestration | A live `research-director` session delegates bounded work to multiple specialists; at least two branch intervals actually overlap; structured handoffs, session identities, and timestamps are journaled; the result causes a visible plan update. Without measured overlap, parallel-discovery evidence is marked **UNMET**, not inferred from async configuration. |
| 25% | Breakthrough potential | The demo names the experiment-selection bottleneck, beneficiaries, scientific significance, proxy-task limits, and the larger capability that multi-domain validation could unlock. |
| 20% | Discovery acceleration and learning | Matched time/trial/cost/intervention measurements, exact formulas, negative-result handling, a result-driven next experiment, and a path-to-10x analysis. |
| 15% | Scientific rigor | Predeclared metric, fixed data identity/splits/seeds, external citations for sourced facts, immutable run/artifact support for measurements, competing explanations, independent review, limitations, reproducibility, and tests. |
| 10% | Creativity and responsibility | The learning receipt, searches with verified temporal overlap and reconciliation, separate safety role, two human gates, budget enforcement, and honest claim boundary. |

The demo and submission inventory must point to a concrete artifact for every
row. Presentation polish must not displace missing evidence in a higher-weight
category.

## Architecture and authority boundaries

Omnigent is the only live scientific workflow orchestrator. The integrated
harness is a bounded execution service, not a competing scheduler or scientific
decision-maker.

```text
Human scientist
  |-- confirms objective, metric, dataset, risk, and execution scope
  `-- approves the exact selected-experiment digest
            |
            v
Omnigent research director (`agents/research-director/`)
  |-- evidence-researcher  -- up to three independent bounded searches
  |-- hypothesis-scientist
  |-- experiment-designer
  |-- safety-reviewer      -- independent of design and analysis
  `-- results-analyst      -- interprets immutable measurements
            |
            v
Research integrity layer (`src/ai_researcher/`)
  |-- typed records and SHA-256 identities
  |-- append-only scientific records and provenance links
  |-- mutable execution-binding lifecycle projection
  |-- digest-bound approvals and execution gates
  `-- translation from scientific specification to bounded task
            |
            v
Integrated execution harness (`harness/`)
  |-- staged task card, provider lane, budgets, and isolation
  `-- status, metrics, logs, and artifact references
```

Authority is deliberately split:

- **Human scientist:** owns the objective and consequential approval.
- **Research director:** owns workflow routing, sequencing, gate enforcement,
  and faithful persistence/presentation of specialist outputs. It does not
  duplicate the designer's experiment recommendation or the analyst's updated
  decision.
- **Specialists:** each own one non-overlapping determination declared below.
- **`src/ai_researcher/`:** owns record validation, stable identity, journal
  durability, approval binding, and harness translation.
- **`harness/`:** owns execution lifecycle, isolation, provider invocation,
  review evidence, and cleanup.
- **Results analyst:** interprets immutable results but cannot change
  measurements or approve execution.

## Consolidated actor and agent contracts

| Actor or boundary | Non-overlapping decision or authority | Actual current tools/interactions | Required inputs | Required output |
|---|---|---|---|---|
| Human scientist | Research objective, primary metric, dataset, risk tolerance, execution scope, and final consequential approval | Objective-confirmation interaction and the exact digest-bound approval/launch interactions; no direct journal or measurement mutation | Objective packet, feasibility evidence, candidate comparison, safety review, exact experiment digest | Attributable objective confirmation, approval/rejection with constraints, and explicit launch decision |
| `research-director` | Workflow routing, gate sequence, and preservation of disagreements; **no** independent objective, experiment-selection, safety, approval, or result-interpretation authority | Five declared sub-agents plus the research-runtime surface for records/receipt, trusted branch events, preflight, approval/stage/launch, status/wait/review/evidence/ingestion, result conversion, force-stop/retire/shutdown | Human-confirmed objective/scope and exact upstream records/budgets | Ordered handoffs, persisted specialist records, exact approval question/digests, lifecycle status, and faithful presentation of the analyst's `updated-decision/v1` |
| `evidence-researcher` | Whether each narrow external claim is supported and what source conflict/uncertainty remains | Built-in `web_search` plus narrow provider-execution start/end marker tools; no research-runtime, journal, experiment execution, or approval tool | `question_id`, `branch_id`, bounded evidence question, access constraints | `evidence-package/v1` with claim-level external citations, support, conflicts, and gaps |
| `hypothesis-scientist` | Falsifiable hypothesis portfolio, predictions, falsifiers, and competing explanations | No configured tools; operates only on supplied records | Fixed question and supplied evidence IDs | `hypothesis-portfolio/v1` with competing explanations and uncertainty |
| `experiment-designer` | Candidate designs, ranking, and exactly one selection recommendation under declared criteria | No configured tools; operates only on supplied records | Confirmed scope/digest, routed hypothesis, evidence, data/compute envelope | `experiment-candidates/v1` with at least two candidates, selected ID, selection rationale, and rejected-candidate rationales |
| `safety-reviewer` | Independent `APPROVAL_REQUIRED`, `REVISE`, or `REJECT` verdict and required controls | No configured tools; operates only on supplied records | Selected candidate and objective digests, confirmed risk/scope, budgets, controls | `safety-review/v1` with risks, controls, prohibited actions, limitations, and exact approval question |
| `results-analyst` | Scientific interpretation (`support`, `revise`, `reject`, or `inconclusive`) and next-experiment recommendation | No configured tools; operates only on supplied immutable records; cannot author timing | Accepted `experiment-result/v1`, Harness acceptance evidence, original hypothesis/specification, controls, evidence | `updated-decision/v1` with rationale, evidence/result references, uncertainty, and result-driven next experiment; the journal adds the timing artifact |
| Execution harness/tool boundary | No scientific decision; execution of only the authorized task and reporting of observations | No direct agent shell route; reachable through the director's declared lifecycle tools and `HarnessAdapter` | Confirmed objective digest/scope, selected-experiment digest, matching approval, safety controls, task-card digest, environment gate, explicit provider/model/options, and budgets | Mutable lifecycle projection plus reviewed immutable result, terminal evidence, metrics, logs, artifact digests, and resource use |

The harness is not a specialist agent. It executes an exact approved task and
returns measurements; it makes no scientific judgment. The same agent may not
both design an experiment and perform its independent safety review.

## Default scientific vertical slice

Subject to explicit human confirmation, propose this scoped question:

> On one fixed OpenML tabular classification task, can provenance-gated,
> evidence-guided experiment selection reach a predeclared validation score
> with fewer model-training trials than a fixed baseline search?

The implemented runner pins OpenML task 59, dataset 61, version 1, with a
content digest confirmed before a live run. The checked-in task-59-shaped CC0
synthetic proxy is tests-only and is never evidence about the live dataset.

Why it is a useful proposal:

- It is likely to fit the internal delivery and compute budgets.
- OpenML can provide a stable task/dataset identity, while a checked local
  fixture can keep tests independent of network availability.
- It creates a measurable bottleneck: trials and time to a target.
- Negative or inconclusive evidence can still guide the next investigation.
- It demonstrates an auditable pattern for later domain-relevant validation.

Proposed measurements:

- `trials_to_threshold`: completed trials to the predeclared target (**primary**)
- Held-out `accuracy` under a fixed trial budget (**secondary quality and
  non-inferiority guard**)
- Wall-clock and compute time
- Agent/tool cost or token usage where available
- Human interventions
- Time from accepted result to updated decision

Matched conditions must include dataset version, split, seeds, metric, trial
budget, and compute limits. Failed trials remain in the denominator. No general
superiority claim may be inferred from one task.

The designer must create and compare at least two candidates. Illustrative
options—not predetermined selections—include:

- Matched fixed baseline search versus evidence-guided selection.
- An ablation of evidence-guided selection with and without reviewed failure
  memory.

The planner selects only after applying the declared comparison criteria. No
alternative is presumed to be the next experiment: the immutable result and
remaining uncertainty must determine the next step.

## Parallel discovery requirement

The live run must demonstrate both independence and real temporal overlap, not
merely list async-capable agents:

1. Split evidence work into at least two bounded questions, such as
   dataset/metric validity and experiment-selection evidence.
2. Call `start_parallel_branch` before each dispatch, dispatch them without
   sharing intermediate conclusions, and call `finish_parallel_branch` only
   after the corresponding specialist returns. This single-use runtime token is
   only a local dispatch marker. Give `record_research_record` the actual
   `provider_session_id`; it independently exports that Omnigent session. Each
   evidence child must call its narrow start marker before substantive work and
   its matching end marker afterward, with at least one completed `web_search`
   call/result strictly between them and no substantive tool calls outside. Only the completed marker-result item
   timestamps in the provider export supply the authoritative interval. Request
   and response persistence, mutable session metadata, and caller timestamps never do.
3. Count branches A and B as parallel only when their half-open execution
   intervals overlap: `A.started_at < B.completed_at` **and**
   `B.started_at < A.completed_at`. Queue time or two `async: true` declarations
   are not proof of overlap.
4. Require completed, distinct invocation IDs and producer sessions, distinct
   nonempty cited evidence packages, and preserve every agent/session identity,
   source, gap, and disagreement.
5. Have the director preserve and route conflicts explicitly rather than averaging or
   hiding them.
6. If time allows, evaluate two hypotheses independently within the same fixed
   evidence and budget envelope.

Acceptance requires visible handoffs, at least one pair of overlapping
intervals, and a reconciliation that cites evidence from every branch. Shared
evidence, same-session branches, incomplete invocations, caller timestamps, or
queue time cannot produce `MET`. If the runtime serializes all branches, report useful
independent work but mark the parallel-discovery acceptance criterion and its
rubric evidence **UNMET**. Do not substitute a disclosure for compliance or
claim parallel speedup.

## Scope boundaries

### Must ship within the internal budget

- The pinned, runnable bundle at `agents/research-director/`
- One research director and five bounded specialists
- Human objective confirmation whose digest is bound through candidates,
  approval, adapter, task card, execution binding, and result chain
- SQLite journal and record validation in `src/ai_researcher/`
- At least two independent evidence branches and reconciliation
- One real computational experiment with a matched baseline
- One result-driven updated decision
- Trial/time/compute/cost/intervention/decision-latency measurements
- Observed acceleration plus a path-to-10x analysis
- Unit tests, a hermetic end-to-end fixture, harness regression, and live run
- Quickstart, `DEMO.md`, limitations, submission inventory, and rubric evidence

### Explicitly out of scope

- General autonomous scientific discovery or wet-lab execution
- More than one primary domain or dataset in the live demo
- A learned experiment-selection policy
- A production multi-tenant service or harness rewrite
- A new web application or polished dashboard
- Broad benchmark/causal claims or an unsupported claim of 10x improvement

## Planned repository work

### 1. First-30-minute objective and feasibility gate

Use repository-relative configuration and artifacts. Record the Git commit and
lockfile identity, then verify:

- Human confirmation of the objective, metric, exact dataset/task, risk
  tolerance, and execution scope
- Dataset availability from the declared source or checked cache
- Stable task/version identity and dataset digest
- License and access terms for retrieval, caching, processing, and any
  redistributed fixture or derived artifact
- Authentication/API availability without placing credentials in records
- Estimated download, RAM, CPU/GPU, runtime, trial count, and cost inside scope
- A license-compatible miniature fixture so tests do not depend on OpenML
- A named fallback that still requires human confirmation before use

**Exit gate:** an attributable objective-confirmation artifact and feasibility
checklist with `PASS` for access, identity, license, privacy, API, and compute.
Any `FAIL` blocks the live experiment and cannot be downgraded by an agent.

### 2. Harden the current Omnigent bundle

Work in the existing layout:

```text
agents/research-director/
|-- config.yaml
|-- AGENTS.md
|-- skills/scientific-discovery/SKILL.md
|-- tools/research_runtime_core.py
|-- tools/python/*.py
`-- agents/
    |-- evidence-researcher/
    |-- hypothesis-scientist/
    |-- experiment-designer/
    |-- safety-reviewer/
    `-- results-analyst/
```

- Preserve and report the current tested pin, `omnigent==0.16.0`.
- Keep five explicit specialists and least-privileged tools.
- Enforce tool-call and session-cost budgets in `config.yaml`.
- Require objective confirmation before decision-bearing work.
- Require exact-digest human approval and an explicit launch action.
- Deny undeclared shell, network, approval, measurement-mutation, and launch
  paths where supported.
- Journal director/specialist identities and independently verified Omnigent
  provider-session receipts with exact in-session execution-marker timing;
  assert parallelism only after interval-overlap validation.

**Exit gate:** bundle validation passes; multiple structured handoffs occur;
safety and analysis stay separate; execution is impossible without a current,
matching objective digest, experiment approval, explicit launch confirmation,
and the environment gate. A parallel claim additionally requires measured
overlap.

### 3. Use the implemented scientific record contracts

The canonical implementation is `src/ai_researcher/records.py`, documented by
`docs/HANDOFF_CONTRACTS.md`. The current schema names are:

1. `research-question/v1`
2. `objective-confirmation/v1`
3. `feasibility-check/v1`
4. `evidence-package/v1`
5. `parallel-branch/v1`
6. `branch-reconciliation/v1`
7. `hypothesis-portfolio/v1`
8. `experiment-candidates/v1`
9. `safety-review/v1`
10. `human-approval/v1`
11. `experiment-result/v1`
12. `updated-decision/v1`
13. `acceleration-summary/v1`

Use these contracts for the question/metric/constraints; human authority and
feasibility; trusted parallel work/reconciliation; cited evidence,
conflicts, and gaps; falsifiable hypotheses; multiple candidates and selection
rationale; independent safety review; exact-digest execution approval; immutable
result identity/metrics/artifacts/limitations; and result-driven next decision.

All records use canonical JSON and SHA-256 identities. Exact referenced IDs and
digests must validate. Malformed, unsupported, cross-question, stale,
overscope, or mismatched records fail closed.

### 4. Extend scientific records and execution projections

Use `src/ai_researcher/journal.py`; do not introduce a second store.

- Keep rows in `records` and `record_links` append-only scientific history,
  addressed by schema identity and content digest. Reject conflicting replays
  and preserve insertion time and producing Omnigent session/agent identity.
- Treat `experiment_bindings` accurately as a **mutable lifecycle projection**:
  `lane_id`, `run_id`, `status`, and `updated_at` may advance in place, while
  current `experiment_id`, `experiment_digest`, and `approval_digest` remain
  invariant. Extend those invariant authority fields with
  `objective_confirmation_digest` and `task_card_digest`. It is operational
  state, not an immutable scientific record.
- Support exact lookup, ordered listing, and complete-chain reconstruction.
- Retain parallel branch metadata and explicit reconciliation.
- Never treat visibility as scientific approval.
- Keep secrets, credentials, and private source content out of records.

**Exit gate:** restart preserves the chain; conflicts and missing provenance fail
atomically; lifecycle transitions cannot rewrite their immutable authority
fields; the learning receipt reconstructs the human-confirmed objective through
the result-driven next experiment.

### 4a. Define the learning receipt as a deterministic projection

The learning receipt is not free-form agent prose and not a second source of
truth. `learning-receipt/v1` is a deterministic read-only projection of one
validated journal chain plus the current execution-binding snapshot.

Required projection fields:

- `schema`, `question_id`, `question_digest`, and
  `objective_confirmation_digest`
- sorted `evidence_package_digests`, `reconciliation_digest`,
  `hypothesis_portfolio_digest`, and `experiment_candidates_digest`
- `selected_experiment_id`, `experiment_digest`, `safety_review_digest`, and
  `human_approval_digest`
- `task_card_digest`, `experiment_result_digest`, `updated_decision_digest`, and
  `acceleration_summary_digest`
- sorted normalized provenance edges as
  `{parent_digest, relation, child_digest}`
- `execution_snapshot` containing only `experiment_id`, `lane_id`, `run_id`,
  `status`, `objective_confirmation_digest`, `experiment_digest`,
  `approval_digest`, and `task_card_digest`
- `receipt_digest`

Projection algorithm:

1. Start from one explicitly requested `question_id` and its confirmed question
   digest; never choose “latest.”
2. Traverse only validated `record_links` reachable from that question and
   require exactly one digest for every singular field. Missing, conflicting,
   cross-question, or unlinked records fail projection.
3. Select evidence packages explicitly linked to the question and sort all
   digest lists and provenance edges lexicographically. Do not use insertion
   order, database row order, filesystem paths, or wall-clock generation time.
4. Join the binding only when its invariant objective, experiment, approval,
   and task-card digests match the selected immutable records/artifact. Copy
   the whitelisted lifecycle fields as a snapshot; never describe that snapshot
   as append-only.
5. Compute `task_card_digest` from the exact staged task-card bytes and verify
   that the card contains the matching objective, experiment, and approval
   digests.
6. Canonically serialize the projection with sorted keys and finite JSON, omit
   `receipt_digest`, and set it to the SHA-256 of those bytes. Identical journal
   state and task-card bytes must yield an identical receipt digest.

The final submission receipt is generated only after a terminal result and
updated decision exist. An earlier receipt is a state-specific preview with a
different digest, never silently overwritten or presented as final.

### 5. Keep one narrow tool surface

The sole implementation module is
`agents/research-director/tools/research_runtime_core.py`. Grant-safe
per-function entry modules under `tools/python/` expose:

- records and receipt: `record_research_record`, `read_research_chain`, and
  `get_learning_receipt`
- branch dispatch markers: `start_parallel_branch` and `finish_parallel_branch`;
  `record_research_record` independently exports the supplied
  `provider_session_id` and accepts only provider-owned completed start/end
  marker-result item timing as parallel evidence
- gates: `preflight_confirmed_objective`, `request_experiment_approval`,
  `stage_approved_experiment`, and `launch_approved_experiment`
- execution lifecycle: `get_experiment_status`,
  `get_harness_experiment_status`, `wait_for_experiment`,
  `review_experiment_completion`, `read_experiment_terminal_evidence`,
  `build_harness_result`, `ingest_harness_experiment_result`,
  `record_experiment_result`, `force_stop_experiment`,
  `read_experiment_cancellation_evidence`, `retire_experiment`, and
  `shutdown_research_harness`

The evidence-researcher has one separate, least-privileged local module,
`execution_marker.py`, exposing only `mark_provider_execution_start` and
`mark_provider_execution_end`. It cannot read or write the journal, approve or
launch execution, or provide timing directly; the verifier trusts only the
corresponding completed call/result items in the independently exported
Omnigent session.

Human objective and approval records are deliberately unavailable to agents;
an attributable operator uses `scripts/record_human_authority.py`. Do not add a
second shell or custom MCP execution path.

Update the existing approval/stage/launch signatures or their validated payloads
so the objective-confirmation digest is mandatory. The adapter must reject an
absent/stale/mismatched digest, an overscope candidate, a task-card digest that
does not match the staged file, or a chain invalidated by reconfirmation.
Execution must require exact objective and experiment authority plus the
environment gate and explicit provider/model/options; enforce data, metric,
trial, time, compute, network, mutation, risk, and cost scope;
run matched methods; and capture task/command identity, code commit,
environment/lock, package versions, seeds, runtime, metrics, logs, and artifact
digests. Agents must not be able to rewrite returned measurements.

### 6. Enforce citations and evidence distinctions

Every factual claim must be traceable, but the correct support depends on its
type:

- **External factual claims** about literature, datasets, tools, or prior work
  require an `evidence-package/v1` claim and external citation metadata.
- **Observed measurements** are not literature claims. They require the exact
  immutable `experiment-result/v1` digest, `run_id`, metric key, and supporting
  artifact/log digest. Do not manufacture an external citation for a local run.
- **Agent-generated hypotheses** are not facts or results. Each hypothesis must
  identify its `supporting_evidence_ids`; those IDs must resolve to cited claims
  in the supplied evidence packages.
- **Interpretations** must reference the result digest and metric fields they
  interpret, and use evidence IDs only for any additional external context.

External citation metadata includes:

- Stable URL, DOI, OpenAlex ID, arXiv ID, or OpenML ID
- Title, publisher/source, and author/organization when available
- Retrieval time and supporting passage or structured field
- License/access note when relevant
- Verification state and uncertainty

Reject external facts without citations, unknown/missing source or evidence
IDs, hypotheses presented as facts, measurements lacking immutable run/artifact
support, and measurements presented as literature evidence. Results analysis
must separate observations, statistical interpretation, agent-generated
hypotheses, limitations, and unresolved uncertainty.

### 7. Implement the experiment and decision loop

Use a small stable OpenML task that passes the initial gate and downloads
quickly, with a license-compatible miniature test fixture.

- Predeclare `trials_to_threshold` as the primary endpoint, `accuracy` as the
  secondary quality/non-inferiority metric, and the accuracy threshold.
- Fix data version/digest, split, and seeds before execution.
- Compare one inexpensive baseline and one evidence-guided policy under the
  same maximum trials and compute.
- Retain failed, cancelled, and timed-out trials.
- Enforce each arm's wall-time limit as a real execution deadline: timed-out
  evaluator work must be terminated and reaped before control returns, rather
  than merely relabeled after a synchronous call finishes. If forced
  termination or a fatal exit prevents an exact final CPU measurement, record
  compute as unavailable and block acceleration claims rather than reporting a
  partial or zero value as measured.
- Calculate trials to threshold, best accuracy, wall/compute time,
  interventions, and cost/token use where available in the immutable result.
  Calculate source-backed decision-update latency only after acceptance and
  independent analysis.
- Require `results-analyst` to recommend `support`, `revise`, `reject`, or
  `inconclusive` without changing measurements.
- Journal the proposed updated decision and a next experiment justified by the
  actual result and remaining uncertainty—not by a preselected fallback.

A valid negative or inconclusive result is preferable to an inflated positive.

The production lifecycle continues after launch: wait for the exact lane,
convert the matched outcome to `experiment-result/v1` with source-digested arm
workflow telemetry but no future decision latency, embed it unchanged in the
Harness `RESULT.json`, explicitly review/accept or reject completion, reread
Harness-owned terminal evidence, and rehash and ingest every artifact. Preserve
the Harness acceptance timestamp/hash in the durable execution binding. Only
then may the independent analyst produce `updated-decision/v1`; at journal
insertion, trusted code adds and hashes an embedded timing artifact spanning
Harness acceptance to decision completion. Derive `acceleration-summary/v1`
from that immutable decision and bind both decision and result digests without
rewriting the result. Then retire or force-stop and explicitly shut down. A
force-stop is an alternate terminal cleanup path: it must prove exact-run
retirement and retain a hash-bound cancellation receipt, must not pretend that
cancellation is an accepted scientific result, and must not mark the run
cancelled when cleanup fails. Exact cleanup authority survives objective
supersession and covers an ambiguous durable `LAUNCHING` run, but may never be
used to adopt results or authorize new execution. Codex launch requires
`reasoning_effort` and `service_tier`, Claude Code requires `effort`, and Qwen
Code accepts an empty provider-options object. No provider has an implicit
configuration.

### 8. Measure acceleration and analyze a path to 10x

Create a machine-readable summary containing matched baseline/proposed trial
counts, time, best metric, interventions, cost/token use where available,
decision latency, the exact formula/denominator, uncertainty where supported,
and threats to validity.

Predeclare these endpoint rules before either arm runs:

- A trial counts when model fitting or the arm's trial-specific computation is
  attempted. `FAIL`, `ERROR`, and timeout attempts consume one trial and their
  actual runtime/cost; retries are new trials. A preflight rejection before
  trial-specific work is logged but not counted. Apply this rule identically.
- `trials_to_threshold` is the ordinal of the first counted trial whose
  preregistered evaluation meets the threshold. If an arm does not reach it
  within budget `B`, store `value: null`, `censored: true`, and
  `lower_bound_exclusive: B` rather than substituting `B`, infinity, or a poor
  score.
- When **both** arms reach the threshold, trial-efficiency speedup is
  `baseline_trials_to_threshold / proposed_trials_to_threshold`. Threshold-time
  speedup is `baseline_elapsed_to_threshold / proposed_elapsed_to_threshold`.
- Arm elapsed time begins when that arm's selection policy starts and includes
  retrieval/planning/agent/tool overhead, preprocessing, failed attempts,
  training, evaluation, and result ingestion through the threshold event.
  Shared one-time setup may be reported separately only when it is identical
  and excluded from both arms; proposed-method overhead may never be excluded
  selectively.
- If neither arm reaches the threshold, acceleration is `NOT_ESTIMABLE`. If the
  proposed arm reaches it and the baseline is censored, report only the lower
  bound `baseline budget / proposed trials` and the categorical outcome; do not
  report a finite x-speedup. If the proposed arm is censored, report no speedup.
- Make no positive acceleration claim when either arm is censored, the ratio is
  at most 1, controls/budgets differ, overhead is missing, a primary-quality
  non-inferiority condition fails, or the result relies on a post-hoc threshold.
  A trial-efficiency improvement with wall-clock ratio at most 1 must be labeled
  **trial efficiency only**, not faster discovery.

Report observed ratios exactly; never round a smaller gain up to 10x or turn a
censored comparison into a point estimate. Then add a scaling analysis covering:

1. **Remaining bottlenecks:** source access/quality, serial approvals, provider
   latency, runtime, reconciliation, and human review.
2. **Parallelizable/automatable work:** independent retrieval, citation checks,
   candidate generation, safe simulations, result parsing, and provenance
   assembly; objectives and consequential approvals remain human-owned.
3. **Expected scaling:** separate fixed setup cost, candidate/dataset-dependent
   work, parallel speedup ceilings, and rate/compute limits.
4. **Evidence still needed:** repeated seeds, multiple tasks, evidence/failure-
   memory ablations, domain datasets, prospective runs, and intervals.
5. **Conditions for approaching 10x:** sufficiently costly baseline search,
   useful early evidence, high safe parallelism, structured/cached sources,
   automated validation, reliable providers, and no loss in quality or safety.

Include conservative, expected, and optimistic sensitivity scenarios. Label
these forecasts separately from observed results.

The implementation accepts end-to-end workflow timing only when both arms have
structured observations for retrieval, planning, approval, preflight, and
agent/tool work plus a SHA-256 measurement-source digest. It measures candidate
compute separately with a process clock. Missing intervention, cost, or token
observations remain `null`, not zero. Missing arm overhead changes timing scope
to `model-evaluation-only` and blocks an overall discovery-speed claim.

### 9. Deliver creative, responsible demo artifacts

Use a terminal-first view rather than a new UI:

```text
Objective confirmation | Evidence branch timing | Hypotheses | Candidates
Safety review | Human approval | Result | Updated decision | Learning receipt
```

The two-minute demo must show the objective and feasibility gates, evidence
branch timestamps with verified overlap (or an explicit **UNMET** marker),
reconciliation, two candidates and comparison, separate safety review, exact
approval, bounded execution, immutable measurements, result-driven next
decision, honest acceleration/scaling, and the complete learning receipt.

Required repository artifacts:

- `README.md` challenge quickstart and `DEMO.md` script
- Agent definitions, contracts, and policies
- Experiment source plus dataset identity/license record
- Machine-readable research chain and learning receipt
- Reproducible commands, test/run evidence, rubric evidence matrix, limitations,
  and validation still required

## Internal delivery schedule

| Window | Work | Change | Test | Exit gate |
|---|---|---:|---:|---|
| 00:00-00:30 | Record identities; confirm objective/metric/data/risk/scope; verify data/API access, license/privacy, digest, cache, and compute/cost. | 0:15 | 0:15 | Attributable confirmation and every feasibility check pass. |
| 00:30-01:30 | Harden agent contracts, objective gate, parallel instructions, permissions, and budgets. | 0:45 | 0:15 | Bundle validates; human ownership/role independence hold; overlap is measured or the rubric item is marked unmet. |
| 01:30-03:00 | Extend records, journal events, and tools for gates, parallel branches, reconciliation, and receipt. | 1:15 | 0:15 | Schema tests and multi-branch reconstruction pass. |
| 03:00-04:30 | Complete citation, cross-record, digest, scope, approval, and immutable-result checks. | 1:00 | 0:30 | Invalid inputs and measurement mutation fail closed. |
| 04:30-06:30 | Implement matched runner, metrics, independent analysis, and updated decision. | 1:30 | 0:30 | Deterministic fixture records a result-driven next experiment. |
| 06:30-07:30 | Add acceleration, path-to-10x scenarios, and rubric mapping. | 0:45 | 0:15 | Formulas reproduce; observations and forecasts are separate. |
| 07:30-09:00 | Integrate live OpenML run and local artifact capture. | 1:00 | 0:30 | One bounded real run produces immutable metrics/provenance. |
| 09:00-10:00 | Write quickstart, demo, limitations, receipt view, and inventory. | 0:45 | 0:15 | A clean checkout can follow the demo path. |
| 10:00-11:15 | Run project/bundle checks, focused harness regression, and live Omnigent loop. | 0:00 | 1:15 | Checks pass; skips/unavailable integrations are disclosed. |
| 11:15-12:00 | Fix release blockers, rerun checks, rehearse twice, capture evidence. | 0:15 | 0:30 | Both rehearsals finish without manual state repair. |
| **Total** |  | **7:30** | **4:30** | **12:00 internal maximum** |

## Test plan

### Baseline

- Record Git commit and `uv.lock` identity.
- Run `uv run python scripts/validate_bundle.py` and `uv run pytest`.
- Run the complete imported Harness suite from `harness/` with `TMPDIR`, `TEMP`,
  and `TMP` bound to one `mktemp -d /tmp/ai-researcher-harness-tests.XXXXXX`
  node-local directory and `PYTHONPATH=. ../.venv/bin/python -m unittest
  discover -s orchestrator_harness/tests -p 'test_*.py'`. Clean the temporary
  directory afterward. This avoids shared-NFS delayed-delete cleanup races
  without changing the test selection.
- Record durations for the final regression budget.

### Unit coverage

- Current schemas and any new explicit journal events
- Canonical JSON, digests, cross-record references, and conflicting replay
- Human objective ownership, all five required fields, digest propagation, and
  absent/stale/mismatch/overscope/reconfirmation cases
- Data identity/access/license/privacy/API/compute gates
- External citations, hypothesis evidence-ID resolution, immutable
  run/artifact support for measurements, and type-confusion rejection
- Experiment digest, approval scope, execution gate, and budgets
- Provider-specific required launch options; status/wait, explicit completion
  review, Harness-owned evidence readback, result conversion/ingestion,
  force-stop, retirement, and exact-confirmation shutdown
- Result-before-analysis ordering, result immutability, journal-authored
  decision timing, acceptance-hash provenance, and updated-decision binding
- Parallel branch identity/timing/conflict/reconciliation and strict interval
  overlap detection (including boundary-touch and serialized negative cases)
- Acceleration formulas, censoring, overhead inclusion, failed-trial counting,
  separate wall/CPU timing, source-backed decision latency, unavailable
  cost/token/intervention handling, no-positive-speedup cases, and
  observed-versus-forecast separation
- Deterministic learning-receipt projection, canonical digest stability,
  task-card byte digest, and missing/conflicting-chain rejection
- Append-only scientific-record invariants versus permitted mutable execution-
  projection transitions
- SQLite atomicity, replay, and restart

Target: new unit tests complete in under two minutes.

### Hermetic integration fixture

1. Store the proposed `research-question/v1` and its digest.
2. Pass cached data/access/license/compute checks.
3. Record attributable human objective confirmation bound to that exact question
   digest.
4. Store two independent cited evidence packages and reconcile them.
5. Generate `hypothesis-portfolio/v1`.
6. Compare at least two candidates carrying that objective digest and select
   with rationale.
7. Obtain independent `safety-review/v1`.
8. Bind actual human approval to the exact objective and experiment digests.
9. Run a deterministic miniature experiment within scope.
10. Accept and ingest the immutable result without decision timing.
11. Independently analyze it, derive the next experiment, and journal the
    decision with a journal-authored timing artifact bound to Harness acceptance.
12. Store result-and-decision-bound acceleration/scaling records and deterministically project the
    learning receipt and its digest.
13. Reopen SQLite and reconstruct the chain.

Tests must not require a live OpenML connection.

### Omnigent and harness integration

- Validate the pinned bundle and declared specialists.
- Confirm agents cannot invoke undeclared agents or tools.
- Confirm at least one pair of independent evidence invocation intervals
  overlaps. Async configuration without overlap must fail this criterion.
- Confirm `safety-reviewer` and `results-analyst` are separate.
- Block execution on absent/stale/mismatched objective confirmation, overscope
  candidates, objective changes without reconfirmation, exact-approval failure,
  task-card digest mismatch, missing launch confirmation, or environment gate.
- Confirm staging never launches and analysts cannot change accepted results.
- Complete one live multi-agent discovery loop.

### Final acceptance

Run the documented path twice from fresh runtime state. Verify both human gates,
objective-digest propagation, feasibility, at least one pair of temporally
overlapping branches, appropriate support for every factual claim, two compared
candidates, independent safety review, matched execution, immutable result,
result-driven next experiment, deterministic receipt reconstruction, correct
censoring/overhead rules, observed-versus-forecast separation, rubric evidence,
and clean shutdown. The second run must require no hand-edited state.

## Acceptance status: implementation versus live evidence

The repository implementation now covers the contracts, authority/preflight
gates, trusted parallel proof, matched fixture/live experiment API,
end-to-end-telemetry inputs, primary/quality endpoint separation, provider
option validation, full Harness lifecycle, immutable result/acceleration
consistency, learning receipt, report, and tests specified above. A clean
checkout can validate those software paths with the commands in the test plan.

The **challenge-evidence definition of done below is not yet satisfied by this
repository alone**. It requires a real human, provider credentials, live
Omnigent/OpenML execution, exported ignored artifacts, and two rehearsals. No
fixture, mock, unit test, empty renderer input, or documentation checkbox may
stand in for that evidence.

## Challenge-evidence definition of done

- A human confirms objective, metric, dataset, risk tolerance, and scope.
- Data/API availability, license/privacy, identity, and compute feasibility pass.
- Omnigent visibly orchestrates structured independent discovery branches, and
  at least two authoritative execution intervals overlap; otherwise the
  parallel criterion is explicitly unmet.
- Every external fact is cited, every hypothesis resolves its evidence IDs, and
  every measured fact resolves an immutable run/result/artifact reference;
  conflicts and gaps remain visible.
- Safety review and result analysis are performed by separate specialists.
- At least two candidates are fairly compared; no selection or next experiment
  is predetermined.
- The objective-confirmation digest binds question, candidates, approval,
  adapter, task card, execution binding, and result chain; absent/stale/
  mismatched/overscope states fail closed and changed objectives require
  reconfirmation.
- Exact experiment approval, task-card integrity, explicit launch, and
  environment gates fail closed.
- The experiment is reproducible from code, data, environment, parameters,
  seeds, controls, and artifacts.
- Immutable results drive the decision and next experiment, with uncertainty
  and limitations explicit.
- Acceleration uses matched disclosed formulas, inclusive overhead and failed
  trials, explicit censoring, and conservative no-positive-claim rules; scaling
  analysis covers bottlenecks, parallelism, required evidence, and boundaries.
- Significance and the enabling breakthrough are stated within the evidence.
- Creativity is demonstrated by real parallel discovery and the deterministic,
  digest-addressed learning receipt, not weaker controls.
- Project and complete Harness tests pass; one live run and two rehearsals
  complete.
- The repository contains quickstart/demo, experiment, records/results, rubric
  matrix, measured improvement, next experiment, and limitations.

## Stop/go rules

- **00:15:** absent human confirmation, prepare but do not activate a proposal.
- **00:30:** any feasibility failure blocks the run; switch to a named fallback
  only after human confirmation.
- **01:30:** if no branch intervals actually overlap, preserve the serial work
  but mark the parallel-discovery criterion/rubric evidence **UNMET**; do not
  infer parallelism from async configuration or claim parallel speedup.
- **03:00:** extend local Python tools; do not start custom MCP work.
- **06:00:** freeze schemas except for release-blocking integrity defects.
- **08:15:** keep immutable local journal/JSON traces; do not add a tracing
  service.
- **09:00:** no new agents, primary datasets, or experiment types.
- **10:00:** feature freeze; fix only acceptance or demo blockers.
- **11:15:** stop refactoring.

Never cut human ownership, Omnigent orchestration, measured-overlap evidence for
any parallel claim, type-appropriate factual support, independent review, exact
approval, matched execution, result-driven decisions, reproducibility, honest
acceleration, or limitations.
Cut viewer styling, optional extra hypotheses, extra datasets, tracing, custom
MCP, or nonessential artifact formats first.

## Primary risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Objective gate becomes a prompt default | Scientific intent is agent-owned | Require attributable confirmation of all five fields and block on absence. |
| Dataset/API/license failure during demo | Run or artifact sharing fails | Complete the first-30-minute gate; cache a licensed fixture; predeclare only a human-confirmed fallback. |
| Omnigent/schema drift | Bundle does not start | Pin the verified version and validate before feature work. |
| Parallelism is cosmetic | Orchestration score suffers | Require authoritative interval overlap; serialized branches are useful evidence but leave the parallel criterion explicitly unmet. |
| Designer reviews its own work | Independence is lost | Keep `safety-reviewer` and `results-analyst` distinct and deny cross-role tools. |
| Handoff violates schema | Loop stalls | Validate each handoff and allow one bounded correction. |
| Experiment is nondeterministic | Result cannot be reproduced | Fix data/split/seeds/environment/versions/budgets. |
| Approval is cosmetic | Responsibility fails | Enforce digest/scope in code plus explicit launch and environment gates. |
| Acceleration/breakthrough is inflated | Credibility fails | Use matched formulas, sensitivity scenarios, and single-task limits. |
| Regression consumes demo time | No accepted evidence | Measure early, test continuously, reserve 75 minutes. |

## Submission package

- Repository URL plus exact Git and dependency identity
- Agent bundle, consolidated contracts, permissions, and budgets
- Human objective confirmation and feasibility checklist
- Schemas, journal description, and complete learning receipt
- Experiment source, data/task identity/digest/license, and command
- Parallel cited evidence packages, authoritative timestamps, validated overlap,
  and reconciliation (or an explicit **UNMET** rubric entry)
- Hypotheses; compared candidates; selection/rejection rationales; safety review
- Exact-digest human approval, result, artifacts, updated decision, next experiment
- Acceleration calculation and conservative/expected/optimistic scaling scenarios
- Rubric-to-artifact matrix, tests/live-run evidence, limitations, and future work
- Two-minute `DEMO.md` script

## Work after the challenge

- Replicate across datasets, seeds, and scientific domains with intervals.
- Compare prospectively against expert-selected experiments.
- Test reviewed-failure-memory and evidence-source ablations.
- Add governed shared storage and artifact lineage only when needed.
- Expand domain-specific safety policies and human review protocols.
- Benchmark models, providers, and agent topologies.
- Validate path-to-10x assumptions with measured scaling studies.
- Build a dashboard only after the scientific workflow and claims are stable.
