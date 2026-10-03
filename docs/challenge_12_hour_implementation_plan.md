# Agentic Scientific Discovery: 12-Hour Implementation Plan

## Purpose

This plan describes the work required to adapt the current memory-backed multi-agent
orchestrator into an Atlas-free Agentic Scientific Discovery submission for the Databricks x
Hack-Nation challenge.

The source project is:

`/Users/benjaminhuh/Documents/GitHub/MongoDB Harness/Orchestrator_Harness/product`

The governing challenge brief is:

`/Users/benjaminhuh/Documents/GitHub/Databricks AI Researcher/challenge_brief.pdf`

The hard delivery limit is 12 elapsed hours. The plan allocates:

- **7 hours 30 minutes for implementation and fixes**
- **4 hours 30 minutes for unit tests, integration tests, regression tests, and demo rehearsal**

The goal is a convincing vertical slice, not a production research platform.

## Required challenge outcome

The finished prototype must demonstrate one complete loop:

> Question -> Evidence -> Hypothesis -> Experiment -> Result -> Updated decision

It must also show:

1. Omnigent visibly orchestrating multiple specialist agents.
2. Structured handoffs between agents rather than only conversational summaries.
3. At least two candidate experiments, with one selected using expected learning,
   feasibility, cost, and risk.
4. A reproducible computational experiment.
5. A result that changes the next scientific decision.
6. Citations for factual claims and clear labeling of agent-generated hypotheses.
7. Preserved uncertainty, controls, limitations, and evidence references.
8. A human approval gate for consequential actions.
9. A measured discovery-acceleration result, even if it is less than 10x.
10. A two-minute demonstration supported by repository artifacts and run evidence.

## Hard architecture decision

Omnigent will be the only live workflow orchestrator.

The existing harness will not compete with Omnigent for scheduling, session ownership, or
agent-to-agent routing. Instead, its strongest components will become a research integrity
kernel exposed to Omnigent through local Python tools or a small MCP surface.

```text
Scientist / human approver
            |
            v
Omnigent PI / supervisor
  |-- Evidence agent
  |-- Hypothesis agent
  |-- Experiment planner
  |-- Experiment runner
  `-- Analysis and safety reviewer
            |
            v
Research integrity tools
  |-- Typed scientific records
  |-- Content hashes and provenance
  |-- SQLite research journal
  |-- Approval and safety records
  |-- Time, cost, and resource budgets
  `-- Experiment and artifact references
            |
            v
Experiment code + data + metrics + trace artifacts
```

Omnigent owns:

- Agent sessions and specialist delegation
- Agent instructions and tool access
- Live handoffs and workflow adaptation
- Sandboxing and policy enforcement
- The challenge-visible orchestration experience

The reused project kernel owns:

- Canonical scientific record validation
- Content hashes and immutable identities
- SQLite durability
- Evidence and citation references
- Human approval records
- Experiment budgets and exclusive-resource leases
- Exact links from question through updated decision

## Default scientific vertical slice

Unless another question is selected in the first 15 minutes, use this scoped AI-research
question:

> On one fixed OpenML tabular classification task, can provenance-gated, evidence-guided
> experiment selection reach a target validation score with fewer model-training trials than a
> fixed baseline search?

Why this is the default:

- It can be executed computationally within the time limit.
- OpenML provides a reproducible task and dataset identity.
- The current harness already excels at bounded computation, evidence, and reviewed outcomes.
- It creates a measurable bottleneck: the number and duration of trials needed to reach a target.
- A negative or inconclusive result can still produce a valid updated decision.

Primary measurements:

- Wall-clock time to a predeclared target score
- Number of completed model-training trials
- Best held-out score under a fixed trial budget
- Compute time and agent/tool cost
- Human interventions required
- Time from experiment completion to updated decision

The comparison must use matched data splits, seeds, metric definitions, and compute limits.
The prototype must not claim general scientific superiority from one dataset.

Candidate experiments produced by the planner:

1. **Selected experiment:** matched baseline search versus evidence-guided selection on one
   OpenML task.
2. **Recorded alternative:** ablation comparing evidence-guided selection with and without
   reviewed failure memory.

The planner must retain both specifications and record why one was selected. The alternative
becomes the proposed next experiment unless the first result justifies a different decision.

## Scope boundaries

### Must ship in 12 hours

- A pinned, runnable Omnigent agent bundle
- One PI/supervisor and at least four purposeful specialist agents
- Atlas-free active runtime and configuration
- A local SQLite research journal
- Typed question, evidence, hypothesis, experiment, result, approval, and decision records
- Claim-level citation references
- One real computational experiment with a baseline
- One result-driven updated decision
- One human approval gate before experiment execution
- Time, trial-count, and cost/usage measurements
- Focused unit tests, an end-to-end fixture test, existing local regression, and a live demo run
- Demo instructions, known limitations, and submission evidence

### Explicitly out of scope

- A complete physical deletion of every historical Atlas test, document, and compatibility type
- A new vector database
- General-purpose autonomous scientific discovery
- Wet-lab execution
- More than one scientific domain
- More than one primary dataset
- A learned experiment-selection policy
- A production multi-tenant service
- A full rewrite of the current launcher/controller lifecycle
- A new web application or polished dashboard
- Broad benchmark claims or a claimed 10x improvement without matched evidence

Historical Atlas modules may remain in the tree if they are unreachable from the active product.
The submission must have no Atlas dependency, credentials, calls, or required configuration.

## Planned repository changes

### 1. Establish an Atlas-free runtime

Modify the active product so the challenge workflow cannot call Atlas.

Required changes:

- Remove `langchain-mongodb` from the active optional dependencies used by the submission.
- Make shared Atlas retrieval and shared publication disabled by default.
- Remove `atlas_memory_only` from challenge-facing network choices.
- Route procedure/history lookup to local SQLite and, only if already working, optional EverOS.
- Prevent challenge entry points from importing `atlas.py` or `atlas_adapters.py`.
- Remove Atlas credentials and environment variables from setup and demo instructions.
- Mark retained Atlas modules as legacy compatibility code excluded from the challenge runtime.
- Exclude live Atlas tests from the challenge test command.

Acceptance gate:

- The application starts in a clean environment without MongoDB packages or credentials.
- The end-to-end research loop completes with network access limited to declared research sources.
- A source scan finds no Atlas import in the new Omnigent bundle or research runtime.

### 2. Add the Omnigent agent bundle

Create a self-contained bundle, preferably under:

```text
product/omnigent/research-lab/
|-- config.yaml
|-- AGENTS.md
|-- skills/
|-- tools/
`-- agents/
    |-- evidence-agent/
    |-- hypothesis-agent/
    |-- experiment-planner/
    |-- experiment-runner/
    `-- analysis-reviewer/
```

Agent responsibilities:

- **PI/supervisor:** owns the question, budget, sequencing, human approval request, and final
  updated decision.
- **Evidence agent:** retrieves sources, creates evidence claims, and attaches citations.
- **Hypothesis agent:** creates falsifiable hypotheses and predictions from approved evidence.
- **Experiment planner:** produces at least two experiment specifications and ranks them by
  expected learning, feasibility, cost, time, and risk.
- **Experiment runner:** executes only an approved specification and publishes machine-readable
  metrics and artifacts.
- **Analysis reviewer:** verifies controls, compares results to the hypothesis, records
  uncertainty and limitations, and proposes the next decision. It must not approve its own
  unsafe action.

Omnigent configuration must:

- Pin the exact tested Omnigent version.
- Declare the sub-agents explicitly.
- Limit each agent to the tools it needs.
- Set a maximum cost or tool-call budget.
- Require human approval for the experiment execution tool.
- Deny undeclared shell, network, or mutation routes where supported.
- Record the Omnigent session and sub-agent identifiers in the research journal.

Acceptance gate:

- A live Omnigent session visibly delegates to multiple specialist agents.
- Agent outputs are persisted as typed records, not only chat messages.
- The experiment runner cannot execute before approval.

### 3. Add scientific record contracts

Add a focused module rather than expanding the existing 200,000-line contract module during the
hackathon. Suggested path:

`product/src/memory_harness/research_contracts.py`

Implement these closed records:

#### `research-question/v1`

- `question_id`
- `question`
- `domain`
- `measurable_outcome`
- `primary_metric`
- `constraints`
- `created_at`
- `content_hash`

#### `evidence-claim/v1`

- `evidence_id`
- `claim`
- `claim_type`: `external_fact`, `observed_result`, or `background`
- `source_id`
- `citation`
- `retrieved_at`
- `supporting_excerpt_or_field`
- `verification_state`
- `uncertainty`
- `content_hash`

#### `hypothesis/v1`

- `hypothesis_id`
- `question_id`
- `statement`
- `prediction`
- `falsification_condition`
- `supporting_evidence_ids`
- `competing_explanations`
- `uncertainty`
- `status`
- `content_hash`

#### `experiment-spec/v1`

- `experiment_id`
- `hypothesis_id`
- `candidate_id`
- `method`
- `baseline`
- `controls`
- `dataset_id` and dataset digest/version
- `parameters`
- `random_seeds`
- `metrics`
- `success_threshold`
- `expected_learning`
- `estimated_runtime`
- `estimated_cost`
- `risk_level`
- `approval_required`
- `content_hash`

#### `experiment-result/v1`

- `run_id`
- `experiment_id`
- `code_commit`
- `environment_digest`
- `dataset_digest`
- `started_at` and `completed_at`
- `parameters`
- `metrics`
- `artifact_refs`
- `stdout_or_log_digest`
- `status`
- `limitations`
- `content_hash`

#### `human-approval/v1`

- `approval_id`
- `experiment_digest`
- `decision`: `APPROVED` or `REJECTED`
- `decided_by`
- `reason`
- `decided_at`
- `content_hash`

#### `updated-decision/v1`

- `decision_id`
- `question_id`
- `hypothesis_id`
- `experiment_result_id`
- `decision`: `support`, `revise`, `reject`, or `inconclusive`
- `rationale`
- `evidence_ids`
- `next_experiment_id`
- `remaining_uncertainty`
- `human_review_state`
- `content_hash`

Reuse the project's canonical JSON and content-hash functions. Every relationship must be checked
against the exact referenced record and digest.

Acceptance gate:

- Malformed, uncited, cross-question, stale, or digest-mismatched records fail closed.
- A complete valid chain can be reconstructed from question to updated decision.

### 4. Add a small research journal

Add a narrow append-only SQLite component, preferably:

`product/src/memory_harness/research_store.py`

Do not substantially refactor the existing `MemoryStore` during the 12-hour build. Reuse its
conventions and integrity helpers, but keep the new schema isolated enough to test quickly.

Required behavior:

- Store every typed scientific record by ID and content hash.
- Reject conflicting replays.
- Preserve insertion time and producing Omnigent session/agent identity.
- Support exact lookup and ordered listing by question.
- Expose a complete-chain read for the final report.
- Never treat visibility as scientific approval.
- Keep secrets, API keys, and raw credentials out of records.

Acceptance gate:

- Restarting the process preserves the complete chain.
- Conflicting writes and missing provenance fail without partial mutation.

### 5. Implement research tools

Expose a minimal tool surface to Omnigent:

- `record_question`
- `record_evidence_claim`
- `record_hypothesis`
- `record_experiment_candidates`
- `request_experiment_approval`
- `record_human_approval`
- `run_approved_experiment`
- `record_interpretation`
- `record_updated_decision`
- `read_research_chain`

The experiment tool must:

- Require an exact approved experiment digest.
- Use a fixed dataset version and deterministic split.
- Enforce the trial, time, and compute budget.
- Run baseline and proposed methods under matched conditions.
- Capture command, environment, package versions, seeds, runtime, metrics, and artifact digests.
- Return structured output without allowing an agent to rewrite the measured values.

Use a local Python tool before building a custom MCP server. Add MCP only if Omnigent's local tool
path cannot satisfy the live demonstration.

### 6. Add citation and evidence checks

The evidence agent must return source metadata with every factual claim. At minimum retain:

- Stable URL, DOI, OpenAlex ID, arXiv ID, or OpenML ID
- Title and source/publisher
- Author or organization when available
- Retrieval timestamp
- Supporting passage or structured source field
- License/access note when relevant
- Verification status

Add a deterministic validator that rejects:

- Factual claims with no citation
- Unknown source IDs
- Hypotheses mislabeled as external facts
- Experiment results represented as literature evidence
- Citations whose source record is missing

The analyst must clearly separate:

- Observed measurements
- Statistical interpretation
- Agent-generated hypotheses
- Limitations and unresolved uncertainty

### 7. Implement the experiment and updated-decision loop

The chosen vertical slice should use a small, stable OpenML classification task that downloads
quickly and can also be cached as a test fixture.

Implementation requirements:

- Predeclare the primary metric and success threshold.
- Fix data split and seeds before execution.
- Use one inexpensive baseline search policy.
- Use one evidence-guided selection policy.
- Apply the same maximum number of trials to both.
- Record failed trials rather than hiding them.
- Calculate wall time, best score, trials to threshold, and intervention count.
- Require the analysis reviewer to recommend `support`, `revise`, `reject`, or `inconclusive`.
- Have the PI/supervisor persist the updated decision and name the next experiment.

The result is acceptable even when it rejects the hypothesis, provided the evidence is valid and
changes what the lab proposes next.

### 8. Add acceleration measurement and tracing

Create one summary record containing:

- Baseline wall-clock time
- Proposed-method wall-clock time
- Baseline and proposed trial counts
- Best matched-condition metric for each method
- Human intervention count
- Agent/tool cost or token usage when available
- Acceleration ratio and its exact formula
- Limitations of the comparison

Use MLflow if a working local or Databricks experiment can be configured within 15 minutes. Log:

- Parameters
- Metrics
- Artifacts
- Agent/tool traces when available
- Omnigent session identifiers

If MLflow setup is blocked after 15 minutes, retain the same information in the immutable local
research journal and JSON artifacts. Do not sacrifice the complete discovery loop to tracing
setup.

### 9. Adapt the terminal view and demo artifacts

Do not build a new UI. Adapt or supplement the current viewer to present:

```text
Question | Evidence | Hypothesis | Experiment | Result | Decision
```

The demo must make the following visible:

1. The scientific question and metric.
2. Omnigent delegating to specialist agents.
3. Cited evidence arriving.
4. Two experiment candidates and the selection rationale.
5. The human approval gate.
6. Experiment execution and measured result.
7. The updated decision and next experiment.
8. The measured acceleration comparison.

Required repository artifacts:

- `README.md` challenge quickstart
- `DEMO.md` two-minute script
- Agent bundle and policies
- Experiment code
- Machine-readable research records
- Test commands and results
- Known limitations and validation still required

## Exact 12-hour schedule

| Window | Work | Change time | Test time | Exit gate |
|---|---|---:|---:|---|
| 00:00-00:30 | Freeze the question, metric, dataset, current Git commit, Omnigent route, and dependency versions. Run baseline imports and focused tests. | 0:15 | 0:15 | One written question, one primary metric, one dataset, clean baseline. |
| 00:30-01:30 | Disable Atlas in active dependencies/configuration and add the Atlas-free local runtime seam. | 0:45 | 0:15 | Product imports and local memory path work without MongoDB packages or credentials. |
| 01:30-03:00 | Create and pin the Omnigent PI/specialist agent bundle, local tools, permissions, and budget policy. | 1:15 | 0:15 | Omnigent starts and performs one supervisor-to-specialist fixture handoff. |
| 03:00-04:30 | Implement scientific record contracts and the append-only research journal. | 1:00 | 0:30 | Unit tests prove valid chains, conflict rejection, digest validation, and restart durability. |
| 04:30-06:00 | Implement typed handoff tools, citation validation, and the human experiment-approval gate. | 1:00 | 0:30 | Missing citation and missing approval tests fail closed; approved fixture proceeds. |
| 06:00-08:00 | Implement baseline/proposed experiment runner, metrics capture, interpretation, and updated decision. | 1:30 | 0:30 | Deterministic fixture completes the full loop and records a next decision. |
| 08:00-09:00 | Add acceleration summary and MLflow tracing if immediately available; otherwise finalize local trace artifacts. | 0:45 | 0:15 | Timing, trial count, result metrics, and exact acceleration formula are reproducible. |
| 09:00-10:00 | Adapt the viewer/status output and write quickstart, demo script, limitations, and submission inventory. | 0:45 | 0:15 | A clean checkout can follow the documented demo path. |
| 10:00-11:15 | Run new unit/integration tests, existing local memory suite, harness regression, Atlas-free import scan, and live Omnigent end-to-end run. | 0:00 | 1:15 | Required tests pass; skips and unavailable integrations are reported honestly. |
| 11:15-12:00 | Fix only release-blocking defects, rerun affected tests, rehearse the two-minute demo, and capture final evidence. | 0:15 | 0:30 | Demo completes twice from a fresh runtime with retained evidence and no manual file repair. |
| **Total** |  | **7:30** | **4:30** | **12:00 maximum** |

## Test plan

### Baseline before implementation

- Confirm the source repositories are clean and record their commits.
- Run the existing focused memory/coherent-path test.
- Run a basic import of `memory_harness` without optional dependencies.
- Record the current local suite duration so the final regression budget is realistic.

### New unit tests

Add tests for:

- Every scientific record constructor and validator
- Canonical serialization and content hashes
- Missing and conflicting record references
- Citation requirement enforcement
- Fact versus hypothesis labeling
- Experiment approval binding
- Budget and trial-limit enforcement
- Result immutability
- Updated-decision provenance
- SQLite replay, restart, and conflict behavior
- Atlas-free imports and defaults

Target: all new unit tests finish in under two minutes.

### New integration tests

Add one hermetic discovery-loop fixture:

1. Create a research question.
2. Record cited fixture evidence.
3. Generate and validate a hypothesis.
4. Produce two experiment candidates.
5. Select one and record approval.
6. Run a deterministic small experiment fixture.
7. Record analysis and uncertainty.
8. Persist an updated decision.
9. Reopen SQLite and reconstruct the exact chain.

Use a cached miniature dataset for this test. Do not make unit or integration success depend on a
live OpenML connection.

### Omnigent integration tests

- Validate that the pinned bundle loads.
- Confirm the PI can call each declared specialist and no undeclared specialist.
- Confirm tool allowlists prevent unrelated mutation.
- Confirm the runner is blocked before human approval.
- Confirm the approved experiment returns structured output.
- Confirm sub-agent/session identifiers are retained in the research journal.
- Complete one live multi-agent discovery loop.

### Existing regression tests

Run:

- The existing product local test suite
- The embedded harness test suite
- Focused configuration, privacy, preparation, outcome, and snapshot tests
- No live Atlas test suite

If time forces a regression cut, preserve tests covering contracts, store, privacy, dispatch,
review, and lifecycle before lower-risk documentation or visualizer tests.

### Final acceptance test

From a fresh runtime:

1. Start Omnigent.
2. Submit the fixed scientific question.
3. Observe at least two specialist handoffs.
4. Inspect cited evidence records.
5. Observe two experiment candidates.
6. Approve the selected experiment.
7. Run the experiment.
8. Inspect metrics and controls.
9. Observe the updated decision.
10. Reconstruct the complete chain from SQLite.
11. Display measured acceleration and limitations.
12. Shut down cleanly.

Run this final path twice. The second run must not require hand-editing state.

## Definition of done

The 12-hour project is complete only when all of the following are true:

- Omnigent is the visible live orchestrator.
- Multiple specialist agents exchange structured outputs.
- The active runtime has no Atlas dependency or call.
- The research question and primary metric were declared before the experiment.
- At least two possible experiments were recorded.
- The selected experiment has a retained selection rationale and human approval.
- The experiment is reproducible from recorded code, data, environment, parameters, and seeds.
- Every factual claim used in a decision has a citation record.
- The result is linked to an interpretation and updated decision.
- Uncertainty, controls, limitations, and remaining validation are explicit.
- The acceleration metric uses a disclosed formula and matched comparison.
- New unit/integration tests and critical existing regression tests pass.
- One live Omnigent run and two clean demo rehearsals complete.
- The repository contains the agent specifications, policies, experiment code, results, test
  evidence, measured improvement, and next experiment.

## Stop/go rules

To protect the deadline:

- **At 00:15:** if no domain decision exists, use the default OpenML question.
- **At 01:30:** if managed Databricks Omnigent is not immediately available, use open-source
  Omnigent. The brief permits either route.
- **At 03:00:** if custom MCP work is incomplete, use local Python tools.
- **At 06:00:** freeze schemas. No nonessential schema expansion after this point.
- **At 08:15:** if MLflow is not working, use the local immutable metrics/trace records.
- **At 09:00:** no new agents, datasets, or experiment types.
- **At 10:00:** feature freeze. Only test failures and demo blockers may be changed.
- **At 11:15:** stop refactoring. Fix only defects that prevent the acceptance run.

Never cut:

- Omnigent orchestration
- Multiple purposeful agents
- The complete discovery loop
- Citations and evidence
- Human approval
- Result-driven updated decision
- Reproducibility
- Measured acceleration

Cut first if behind:

- Viewer styling
- MLflow integration beyond minimum run logging
- EverOS writes
- Additional datasets
- Custom MCP implementation
- Additional agent roles
- Historical Atlas code deletion

## Primary risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Omnigent version or schema drift | Agent bundle does not start | Pin the first verified version; test a minimal bundle before building features. |
| Two orchestrators own lifecycle | Conflicting state and weak challenge compliance | Omnigent owns orchestration; existing harness components are tools and validators only. |
| Atlas references are too widespread to remove | Schedule overrun | Remove Atlas from the active dependency/runtime path; defer historical cleanup. |
| OpenML or source API is unavailable | Live experiment cannot start | Cache a named dataset and retain its original OpenML ID and digest. |
| Agent output does not match schemas | Loop stalls | Validate after every handoff and allow one bounded correction turn. |
| Experiment is nondeterministic | Result cannot be reproduced | Fix seeds, split, versions, environment, and compute limits. |
| Large data or artifacts dirty Git worktrees | Existing review gate rejects results | Keep code/specifications in Git; store artifact references and hashes outside Git. |
| Safety approval becomes cosmetic | Responsibility score suffers | Enforce approval in the experiment tool, not only in the prompt. |
| Acceleration claim is inflated | Scientific rigor suffers | Use matched conditions, exact formulas, and disclose single-task limitations. |
| Full regression takes too long | No demo time remains | Measure suite duration at start; run focused tests continuously and reserve 75 minutes for regression. |

## Submission package

The final submission should contain:

- Repository URL and exact commit
- Omnigent agent bundle and policies
- Research-record schemas
- Atlas-free storage/runtime documentation
- Experiment source code
- Dataset identity and digest
- Reproducible run command
- Cited evidence records
- Hypotheses and both candidate experiments
- Human approval record
- Experiment result and artifacts
- Updated decision and next experiment
- Acceleration calculation
- Test results and run evidence
- Known limitations and required future validation
- Two-minute demo script

## Work immediately after the challenge

These items are valuable but intentionally excluded from the 12-hour critical path:

- Physically remove all legacy Atlas modules, tests, and documentation.
- Rename Atlas-specific public configuration fields with compatibility migration.
- Consolidate the duplicate `src/memory_harness` and `harness/memory_harness` trees.
- Add multiple datasets and repeated trials with confidence intervals.
- Add a durable shared backend such as Lakebase/PostgreSQL when multi-user writes are needed.
- Add a governed artifact catalog and dataset lineage integration.
- Expand safety policies by scientific domain.
- Benchmark multiple models and agent topologies.
- Turn reviewed research trajectories into evaluation datasets.
- Add a production dashboard and long-running monitoring.

