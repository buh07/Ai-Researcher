# Research handoff contracts

These JSON records are the authority and evidence boundary between the human
scientist, Omnigent specialists, the append-only journal, and the execution
harness. `src/ai_researcher/records.py` is canonical. Unknown schemas, empty
required values, non-finite JSON, malformed SHA-256 values, cross-question
references, unlinked authority, and conflicting replays fail closed.

Every immutable record receives `record_digest`, the lowercase SHA-256 of its
canonical JSON (UTF-8, sorted keys, compact separators) without that field.
`objective-confirmation/v1` also exposes the same value as
`objective_confirmation_digest`. All records after objective confirmation carry
that digest as an authority token. Changing the question, metric, dataset, risk,
or scope requires a new confirmation; it does not mutate an old one.

## Support types

Keep three kinds of statements distinct:

* **External facts** belong in `evidence-package/v1`. Each claim has
  `claim_type: external-fact`, a stable URL/DOI/OpenAlex/arXiv/OpenML identifier,
  source metadata, retrieval time, exact supporting passage/field, access note,
  verification state, and uncertainty. Local measurements and agent hypotheses
  are rejected as external evidence.
* **Agent hypotheses** belong in `hypothesis-portfolio/v1`. They are explicitly
  falsifiable and their evidence IDs must resolve to linked, cited claims.
* **Observed measurements** belong in `experiment-result/v1`. Every metric maps
  through `measurement_support` to a structured artifact/log reference with a
  SHA-256 digest. `updated-decision/v1` names the result digest and exact metric
  keys it interprets; it cannot rewrite observations.

## Authority and preflight

### `research-question/v1`

```json
{
  "schema": "research-question/v1",
  "question_id": "question-1",
  "question": "A focused scientific question",
  "domain": "machine learning",
  "intended_scientific_use": "Why the answer matters",
  "measurable_outcome": "Trials needed to reach the fixed target",
  "primary_metric": "trials_to_threshold",
  "constraints": ["fixed budget"],
  "assumptions": ["fixed split"]
}
```

The question is proposed first; it is not active authority by itself.

### `objective-confirmation/v1`

```json
{
  "schema": "objective-confirmation/v1",
  "objective_confirmation_id": "objective-1",
  "question_id": "question-1",
  "question_digest": "<research-question record_digest>",
  "primary_metric": "trials_to_threshold",
  "dataset": {
    "identifier": "openml-task-59-dataset-61",
    "version": "1",
    "digest": "<sha256>",
    "source": "https://www.openml.org/t/59"
  },
  "risk_tolerance": {
    "level": "low",
    "allowed_risks": ["bounded compute overrun"],
    "prohibited_actions": ["data mutation"],
    "privacy_constraints": ["public data only"],
    "acceptable_failure_modes": ["inconclusive result"]
  },
  "execution_scope": {
    "max_trials": 8,
    "max_runtime_minutes": 30,
    "max_cost_usd": 1.0,
    "compute": "local CPU",
    "network_access": "dataset-download-only",
    "mutation_permissions": ["artifact directory only"]
  },
  "confirmed_by": "human identity",
  "confirmed_at": "2026-10-03T12:00:00Z",
  "supersedes_objective_confirmation_digest": "<optional prior digest>"
}
```

The journal requires the exact question as an ancestor and verifies the metric.
A superseding confirmation explicitly links the prior confirmation. Superseded
authority cannot authorize new downstream records.

### `feasibility-check/v1`

```json
{
  "schema": "feasibility-check/v1",
  "feasibility_check_id": "feasibility-1",
  "question_id": "question-1",
  "objective_confirmation_digest": "<objective digest>",
  "checked_by": "human or attributable operator",
  "checked_at": "2026-10-03T12:01:00Z",
  "checks": {
    "access": {"status": "PASS", "evidence": "..."},
    "identity": {"status": "PASS", "evidence": "..."},
    "license": {"status": "PASS", "evidence": "..."},
    "privacy": {"status": "PASS", "evidence": "..."},
    "api": {"status": "PASS", "evidence": "..."},
    "compute": {"status": "PASS", "evidence": "..."}
  },
  "overall_status": "PASS",
  "fallback": "Named fallback that still requires human confirmation"
}
```

The six check names are exact. `overall_status` is `PASS` only when every check
passes. Exactly one linked passing check is mandatory before candidate
acceptance, and any recorded `FAIL` for the objective blocks candidates; a later
`PASS` cannot hide it. Resolve the failure or reconfirm a fresh objective.

## Evidence, independent branches, and hypotheses

### `evidence-package/v1`

```json
{
  "schema": "evidence-package/v1",
  "evidence_package_id": "evidence-a",
  "question_id": "question-1",
  "objective_confirmation_digest": "<objective digest>",
  "claims": [{
    "evidence_id": "evidence-1",
    "claim_type": "external-fact",
    "claim": "One narrow factual claim",
    "source_type": "primary-paper-or-dataset-registry",
    "citation": {
      "title": "Source title",
      "url": "https://example.org/stable-source",
      "authors_or_organization": "Author or owner",
      "publisher_or_source": "Publisher/source",
      "retrieved_at": "2026-10-03T12:01:00Z",
      "license_or_access_note": "Access and reuse status",
      "verification_state": "verified"
    },
    "support": "Supporting passage or structured field",
    "uncertainty": "Known limitation"
  }],
  "conflicts": [],
  "coverage_gaps": []
}
```

`verification_state` is `verified`, `partially-verified`, or `unverified`.
A DOI, OpenAlex ID, arXiv ID, or OpenML ID may replace the URL.

### `parallel-branch/v1`

```json
{
  "schema": "parallel-branch/v1",
  "branch_id": "branch-a",
  "question_id": "question-1",
  "objective_confirmation_digest": "<objective digest>",
  "bounded_question": "The independent evidence question",
  "producer_agent_id": "evidence-researcher",
  "producer_session_id": "omnigent-session-id",
  "invocation_id": "conv-provider-session-id",
  "invocation_status": "COMPLETED",
  "provider_session_id": "conv-provider-session-id",
  "provider_receipt_digest": "<sha256 of verified Omnigent receipt>",
  "started_at": "2026-10-03T12:01:00Z",
  "completed_at": "2026-10-03T12:03:00Z",
  "status": "COMPLETED",
  "independent_context": true,
  "evidence_package_digest": "<linked package digest>"
}
```

Status is `COMPLETED`, `ERROR`, or `CANCELLED`. A branch record is accepted only
after the research runtime independently runs `omnigent session export` for the
claimed child session. The export must identify the evidence-researcher agent,
its parent/root session, model and harness, a positive provider token count,
terminal `idle` status, and exactly one completed
`mark_provider_execution_start` call/result followed by one completed
`mark_provider_execution_end` call/result in the same provider response. Marker
arguments/results must bind the exact branch and start-marker ID. At least two
distinct completed `inspect_public_source` calls/results must occur strictly
between the markers. Every citation URL must match an inspected requested or
final URL. Exactly one successful `validate_evidence_package` call must be the
last substantive call, and the final response must match its package digest.
`search_public_web` (or a legacy provider `web_search`) is optional discovery;
its snippets are not inspected evidence. No substantive tool call may occur
outside the markers in that response. Final response generation after the end
marker remains allowed. The positive
ordered interval is derived only from the two provider-owned completed marker-result
item timestamps. User-request, assistant-response, and mutable session-metadata
timestamps such as `created_at`/`updated_at` never define the execution interval.
The journal persists the derived receipt and digest.
The local start/finish token is only a single-use dispatch marker; its timestamps,
caller-authored fields, caller-selected files, and caller JSON cannot prove overlap.

### `branch-reconciliation/v1`

```json
{
  "schema": "branch-reconciliation/v1",
  "reconciliation_id": "reconciliation-1",
  "question_id": "question-1",
  "objective_confirmation_digest": "<objective digest>",
  "branch_digests": ["<branch-a digest>", "<branch-b digest>"],
  "agreements": [],
  "conflicts": [],
  "unresolved_questions": [],
  "reconciled_evidence_ids": ["evidence-1"],
  "parallel_status": "MET",
  "overlapping_branch_pairs": [["branch-a", "branch-b"]]
}
```

The journal recomputes overlap using the verified Omnigent session intervals and
the half-open rule (`A.start < B.end` and `B.start < A.end`). Claimed pairs must
equal the measured pairs. When no pair
overlaps, status is `UNMET` and the pair list is empty. `MET` additionally
requires completed provider lifecycle evidence, distinct Omnigent provider
sessions and invocation IDs, distinct evidence packages with nonempty cited claims, and at least one
reconciled evidence ID from every branch. Shared, serial, failed, or incomplete
work cannot satisfy the parallel criterion.

### `hypothesis-portfolio/v1`

```json
{
  "schema": "hypothesis-portfolio/v1",
  "hypothesis_portfolio_id": "hypotheses-objective-1",
  "question_id": "question-1",
  "objective_confirmation_digest": "<objective digest>",
  "hypotheses": [{
    "hypothesis_id": "hypothesis-1",
    "statement": "Agent-generated falsifiable statement",
    "prediction": "Observable prediction",
    "falsification_condition": "Observation that counts against it",
    "supporting_evidence_ids": ["evidence-1"],
    "competing_explanations": ["Alternative mechanism"],
    "uncertainty": "Current uncertainty"
  }]
}
```

`hypothesis_portfolio_id` identifies this generated portfolio, rather than the
question. Reconfirmation therefore creates a new portfolio ID without colliding
with immutable history. Evidence IDs are globally unique within a question;
each supporting ID must resolve exactly once in the portfolio's linked ancestor
packages.

## Selection, review, and approval

### `experiment-candidates/v1`

```json
{
  "schema": "experiment-candidates/v1",
  "experiment_candidates_id": "candidates-objective-1",
  "question_id": "question-1",
  "objective_confirmation_digest": "<objective digest>",
  "hypothesis_id": "hypothesis-1",
  "primary_metric": "trials_to_threshold",
  "dataset_identity": {
    "identifier": "openml-task-59-dataset-61",
    "version": "1",
    "digest": "<sha256>"
  },
  "resource_bounds": {
    "max_trials": 8,
    "max_runtime_minutes": 30,
    "max_cost_usd": 1.0,
    "compute": "local CPU",
    "network_access": "dataset-download-only",
    "mutation_permissions": ["artifact directory only"]
  },
  "risk_tolerance": {
    "level": "low",
    "allowed_risks": ["bounded compute overrun"],
    "prohibited_actions": ["data mutation"],
    "privacy_constraints": ["public data only"],
    "acceptable_failure_modes": ["inconclusive result"]
  },
  "candidates": [{
    "experiment_id": "experiment-guided",
    "method": "Reproducible method",
    "baseline": "Matched comparison",
    "controls": ["same split"],
    "inputs": ["openml-task-59"],
    "parameters": {"max_trials_per_arm": 4, "max_seconds_per_arm": 300, "threshold": 0.9},
    "random_seeds": [7],
    "metrics": ["trials_to_threshold", "accuracy"],
    "success_threshold": "Predeclared threshold",
    "expected_learning": "What the outcomes distinguish",
    "estimated_runtime_minutes": 20,
    "estimated_cost_usd": 1.0,
    "risk_level": "low"
  }, {
    "experiment_id": "experiment-ablation",
    "method": "Matched unguided ablation",
    "baseline": "Same fixed comparison",
    "controls": ["same split"],
    "inputs": ["openml-task-59/dataset-61"],
    "parameters": {"max_trials_per_arm": 4, "max_seconds_per_arm": 300, "threshold": 0.9},
    "random_seeds": [7],
    "metrics": ["trials_to_threshold", "accuracy"],
    "success_threshold": "Trials needed to reach accuracy >= 0.9",
    "expected_learning": "Whether evidence order, rather than search alone, matters",
    "estimated_runtime_minutes": 20,
    "estimated_cost_usd": 1.0,
    "risk_level": "low"
  }],
  "selected_experiment_id": "experiment-guided",
  "selection_rationale": "Learning, feasibility, time, cost, and risk",
  "rejected_candidate_rationales": {"experiment-ablation": "Why rejected"}
}
```

At least two candidates are required. IDs are unique, each candidate includes
the primary metric, and every rejected candidate has exactly one rationale. The
journal rejects dataset, metric, risk, compute, network, mutation, or resource
bounds outside confirmed scope. Every selected parameter set is executable:
per-arm trials and seconds and the fixed threshold are present and within the
portfolio bounds, and runtime/cost estimates remain within authority.
The candidate `dataset_identity` identifier, version, and digest must exactly
equal the confirmed dataset triplet; the result must repeat that same triplet.
`experiment_candidates_id` identifies one regenerated comparison. Its
`hypothesis_id` must resolve exactly once in a linked hypothesis portfolio, so a
new confirmation can produce a new comparison without overwriting the prior
question's immutable record.

### `safety-review/v1`

```json
{
  "schema": "safety-review/v1",
  "experiment_id": "experiment-guided",
  "experiment_digest": "<selected specification digest>",
  "objective_confirmation_digest": "<objective digest>",
  "verdict": "APPROVAL_REQUIRED",
  "risks": [],
  "required_controls": [],
  "prohibited_actions": [],
  "approval_question": "Approve this exact experiment?",
  "review_limitations": []
}
```

Allowed verdicts are `APPROVAL_REQUIRED`, `REVISE`, and `REJECT`. Safety review
and result interpretation are separate roles.

### `human-approval/v1`

```json
{
  "schema": "human-approval/v1",
  "approval_id": "approval-1",
  "experiment_id": "experiment-guided",
  "experiment_digest": "<selected specification digest>",
  "objective_confirmation_digest": "<objective digest>",
  "approved": true,
  "approved_by": "human identity",
  "approved_at": "2026-10-03T12:05:00Z",
  "scope": "execute-exact-experiment",
  "constraints": []
}
```

Approval authorizes only that objective and specification. Staging, explicit
launch confirmation, and the environment execution gate remain separate.

## Results, decisions, and acceleration

### `experiment-result/v1`

```json
{
  "schema": "experiment-result/v1",
  "question_id": "question-1",
  "experiment_id": "experiment-guided",
  "experiment_digest": "<selected specification digest>",
  "objective_confirmation_digest": "<objective digest>",
  "approval_digest": "<human-approval record_digest>",
  "task_card_digest": "<task-card sha256>",
  "run_id": "run-1",
  "execution_source": "integrated-harness",
  "primary_metric": "trials_to_threshold",
  "code_identity": "commit or artifact digest",
  "dataset_identity": {
    "identifier": "openml-task-59-dataset-61", "version": "1", "digest": "<sha256>"
  },
  "environment_identity": "lockfile or image digest",
  "parameters": {
    "approved_candidate_parameters": {"max_trials_per_arm": 4, "max_seconds_per_arm": 300, "threshold": 0.9},
    "observed_preregistration": {
      "primary_metric": "trials_to_threshold",
      "dataset_identity": {"identifier": "openml-task-59-dataset-61", "version": "1", "digest": "<sha256>"},
      "split_seed": 7, "threshold": 0.9, "max_trials_per_arm": 4,
      "max_seconds_per_arm": 300, "control_digest": "<sha256>",
      "endpoint_rules": {"attempt": "Every attempted fit counts"}
    },
    "execution_metadata": {"measurement_availability": {
      "baseline": {"workflow_overhead": "MEASURED"},
      "proposed": {"workflow_overhead": "MEASURED"}
    }}
  },
  "random_seeds": [7],
  "metrics": {
    "trials_to_threshold": {
      "baseline": {"value": 4, "censored": false, "lower_bound_exclusive": null},
      "proposed": {"value": 2, "censored": false, "lower_bound_exclusive": null}
    },
    "accuracy": {"baseline": 0.90, "proposed": 0.91},
    "elapsed_to_threshold_seconds": {"baseline": 40, "proposed": 20},
    "total_elapsed_seconds": {"baseline": 40, "proposed": 20},
    "compute_seconds": {"baseline": 30, "proposed": 15},
    "interventions": {"baseline": 1, "proposed": 1},
    "cost_usd": {"baseline": null, "proposed": null},
    "token_usage": {"baseline": null, "proposed": null},
    "baseline": {"attempted_trials": 4},
    "evidence_guided": {"attempted_trials": 2}
  },
  "artifact_refs": [{"uri": "artifact://run/metrics.json", "kind": "metrics", "digest": "<sha256>"}],
  "measurement_support": {
    "trials_to_threshold": "<artifact sha256>", "accuracy": "<artifact sha256>",
    "elapsed_to_threshold_seconds": "<artifact sha256>", "total_elapsed_seconds": "<artifact sha256>",
    "compute_seconds": "<artifact sha256>", "interventions": "<artifact sha256>",
    "cost_usd": "<artifact sha256>", "token_usage": "<artifact sha256>",
    "baseline": "<artifact sha256>",
    "evidence_guided": "<artifact sha256>"
  },
  "started_at": "2026-10-03T12:06:00Z",
  "completed_at": "2026-10-03T12:10:00Z",
  "status": "PASS",
  "limitations": []
}
```

Status is `PASS`, `FAIL`, `ERROR`, or `CANCELLED`. Metric keys and support keys
must match exactly; support digests must resolve to `artifact_refs`. Journal-ready
results require the full two-arm endpoint, quality, wall/compute time, and
cost/intervention/token availability. Decision latency is forbidden here
because this record must be accepted before independent analysis begins.
`compute_seconds` is nullable only when its matching arm availability is
`UNAVAILABLE`, such as a killed timeout or fatal evaluator exit that cannot
return an exact final process-clock measurement. A partial CPU sample must not
be stored as an exact measurement.
`approved_candidate_parameters` must equal the immutable
selected candidate and the observed preregistration must match its metric,
dataset, seed, threshold, trials, seconds, and declared order parameters.

### `updated-decision/v1`

```json
{
  "schema": "updated-decision/v1",
  "question_id": "question-1",
  "objective_confirmation_digest": "<objective digest>",
  "hypothesis_id": "hypothesis-1",
  "experiment_id": "experiment-guided",
  "run_id": "run-1",
  "result_digest": "<experiment-result record_digest>",
  "decision": "inconclusive",
  "rationale": "Interpretation grounded in measured results",
  "interpreted_metrics": ["trials_to_threshold"],
  "supporting_evidence_ids": [],
  "remaining_uncertainty": ["More seeds needed"],
  "next_experiment": {"question": "What should be discriminated next?", "rationale": "Driven by the result"},
  "human_review_required": true,
  "decision_timing": {
    "schema": "decision-timing-measurement/v1",
    "result_digest": "<experiment-result record_digest>",
    "run_id": "run-1",
    "harness_acceptance_digest": "<Harness acceptance content hash>",
    "result_accepted_at": "2026-10-03T12:10:00Z",
    "decision_completed_at": "2026-10-03T12:10:05Z",
    "latency_seconds": 5
  },
  "decision_timing_source_digest": "<sha256 of canonical decision_timing>"
}
```

Allowed decisions are `support`, `revise`, `reject`, and `inconclusive`. The
analyst submits the scientific fields only. On append, the journal reads the
accepted Harness boundary from the durable binding, adds the embedded timing
artifact using its own completion clock, and hashes it. Caller-authored timing
is rejected. This keeps the schema count at thirteen while making timing
evidence immutable and digest-addressed.

### `acceleration-summary/v1`

The summary binds `question_id`, `objective_confirmation_digest`,
`experiment_id`, `result_digest`, and `primary_metric`. It requires
`threshold_predeclared: true`, `matched_conditions: true`, a declared
`trial_count_rule` and `formula`, non-empty threats to validity, and exactly two
arms:

```json
{
  "schema": "acceleration-summary/v1",
  "acceleration_summary_id": "acceleration-run-1",
  "question_id": "question-1",
  "objective_confirmation_digest": "<objective digest>",
  "experiment_id": "experiment-guided",
  "result_digest": "<experiment-result record_digest>",
  "updated_decision_digest": "<updated-decision record_digest>",
  "primary_metric": "trials_to_threshold",
  "dataset_identity": {"identifier": "openml-task-59-dataset-61", "version": "1", "digest": "<sha256>"},
  "threshold_predeclared": true,
  "matched_conditions": true,
  "overhead_included": true,
  "timing_scope": "end-to-end-arm-workflow",
  "overall_discovery_speed_claim": false,
  "decision_latency_seconds": 5,
  "decision_timing_source_digest": "<sha256>",
  "matched_controls_digest": "<sha256>",
  "endpoint_rules": {"attempt": "Every attempted fit counts"},
  "arms": {
    "baseline": {
      "trial_budget": 4, "trials_attempted": 4,
      "trials_to_threshold": {"value": null, "censored": true, "lower_bound_exclusive": 4},
      "elapsed_to_threshold_seconds": null,
      "total_elapsed_seconds": 30,
      "compute_seconds": 20, "best_metric": 0.89,
      "interventions": 1, "cost_usd": null, "token_usage": null,
      "measurement_availability": {
        "workflow_overhead": "MEASURED", "compute_seconds": "MEASURED",
        "human_interventions": "MEASURED", "cost_usd": "UNAVAILABLE", "token_usage": "UNAVAILABLE"
      }
    },
    "proposed": {
      "trial_budget": 4, "trials_attempted": 3,
      "trials_to_threshold": {"value": 3, "censored": false, "lower_bound_exclusive": null},
      "elapsed_to_threshold_seconds": 25,
      "total_elapsed_seconds": 25,
      "compute_seconds": 15, "best_metric": 0.91,
      "interventions": 1, "cost_usd": null, "token_usage": null,
      "measurement_availability": {
        "workflow_overhead": "MEASURED", "compute_seconds": "MEASURED",
        "human_interventions": "MEASURED", "cost_usd": "UNAVAILABLE", "token_usage": "UNAVAILABLE"
      }
    }
  },
  "trial_count_rule": "Count every attempted trial, including errors and retries.",
  "formula": "baseline trials / proposed trials only when both are uncensored",
  "outcome": "LOWER_BOUND_ONLY",
  "observed_trial_speedup": null,
  "trial_speedup_lower_bound": 1.3333333333333333,
  "observed_time_speedup": null,
  "quality_non_inferiority": {
    "margin": 0.01,
    "higher_is_better": true,
    "passed": true
  },
  "claim_blockers": ["baseline_censored", "time_speedup_not_estimable"],
  "threats_to_validity": ["Single task"],
  "scaling_analysis": {
    "remaining_bottlenecks": ["human approval latency"],
    "parallelizable_or_automatable": ["independent retrieval"],
    "evidence_still_needed": ["multiple tasks and seeds"],
    "conditions_for_approaching_10x": ["costly baseline search and safe parallel work"],
    "boundaries": ["No broad causal claim"],
    "scenarios": {
      "conservative": {"assumptions": ["limited concurrency"], "projected_speedup": 1.1, "boundaries": ["forecast, not observation"]},
      "expected": {"assumptions": ["cached sources"], "projected_speedup": 2.0, "boundaries": ["forecast, not observation"]},
      "optimistic": {"assumptions": ["high safe parallelism"], "projected_speedup": 10.0, "boundaries": ["requires prospective validation"]}
    }
  }
}
```

A finite trial or time speedup is permitted only when both arms reach threshold
and is recomputed as `baseline / proposed`; time speedup uses the exact
`elapsed_to_threshold_seconds` endpoints, while `total_elapsed_seconds` records
the full arm runtime. A censored arm carries `null` for the endpoint and finite
speedups and uses the exact attempted-trial lower bound. Early censoring is
valid only for `wall-time-budget-exhausted`; ordinary trial-budget censoring
must exhaust the declared trial budget. When only the baseline is censored,
`trial_speedup_lower_bound` is exactly its attempted-trial lower bound divided
by the proposed endpoint. `quality_non_inferiority.passed` is recomputed
from the two best metrics, direction, and margin. `claim_blockers` must exactly
equal the applicable censoring, non-improvement, time, and quality blockers.
`POSITIVE` therefore requires uncensored trial and time ratios above one and
quality non-inferiority. It additionally requires `overhead_included: true`.
When overhead is absent, `claim_blockers` includes `overhead_missing` and a
positive discovery-speed claim is invalid. `TRIAL_EFFICIENCY_ONLY` is used when
trial efficiency improves but inclusive wall-clock speed or overhead support is
insufficient.
If either arm's exact compute is unavailable, `claim_blockers` additionally
contains `compute_unavailable` and an overall positive claim is prohibited.

## Journal provenance and semantic links

`ResearchJournal.append` records immutable source, insertion time,
`producer_session_id`, and `producer_agent_id`. Parallel branches additionally
persist the verified Omnigent provider-session ID, immutable receipt digest and
receipt, plus its provider-owned `invocation_started_at` and
`invocation_completed_at` marker-result interval. Reconciliation computes overlap
from that journal metadata, never from request/response persistence, local wrapper,
or agent-authored timing fields. Each
non-question record must have explicit incoming `(parent_digest, relation)`
links. The journal verifies
that the claimed objective occurs in its ancestor chain, question IDs agree,
evidence IDs are globally unique per question and resolve only through exact
linked ancestors, branch overlap is real, selection is within feasibility
and scope, dataset triplets remain exact, and review/approval/result/decision
digests match. An acceleration summary must bind the exact selected experiment,
result digest, and predeclared primary metric present in that result.

`list_questions()` returns insertion-ordered questions.
`reconstruct_chain(question_id)` returns digest-sorted immutable records,
lexicographically sorted semantic edges, and producer provenance. Exact lookup
never means “latest.”

`experiment_bindings` is deliberately different: it is a mutable operational
projection. Only `lane_id`, `run_id`, `status`, and `updated_at` may change. Its
`experiment_id`, `experiment_digest`, `approval_digest`,
`objective_confirmation_digest`, `task_card_digest`, and task-card path are
immutable. Lifecycle transitions are monotonic; terminal states cannot reopen,
and non-null lane/run IDs cannot change. The digest is recomputed from exact
task-card bytes. The parsed JSON must contain an exact top-level
`research_authority` mapping with only `objective_confirmation_digest`,
`experiment_digest`, and `approval_digest`; incidental digest text is not
authority. Additive SQLite
migration keeps old journals readable; new authority fields are never inferred
from an unrelated “latest” row. Every new or advanced binding must explicitly
supply non-null objective-confirmation and task-card digests. A legacy row with
either authority column missing is read-only and fails closed until a separate,
audited migration is implemented; the ordinary binding path never backfills it.

### Persisted pre-authority `/v1` compatibility boundary

Early `0.2` journals used the same eight `/v1` schema names before objective
authority and the portfolio record IDs above existed. Those immutable payloads
are supported through a **read-only legacy profile**:

* `get`, `find`, and `reconstruct_chain` validate and return representative old
  question, evidence, hypothesis, candidate, safety, approval, result, and
  decision payloads without rewriting their bytes or digests;
* reconstruction lists their digests in `legacy_record_digests`, making the
  compatibility path visible to callers;
* partially upgraded payloads are not treated as legacy, preventing malformed
  current records from falling back to weaker validation; and
* `append`, objective confirmation, approval, binding, learning-receipt
  projection, staging, and execution continue to use only the strict current
  contract. A legacy chain must be restarted with a fresh question/objective
  confirmation and newly generated records before it can authorize work.

Thus “migration-safe” means additive SQLite columns and faithful read access,
not silent scientific-schema upgrading. There is intentionally no automatic
conversion or authority blessing for historical content.

## Deterministic `learning-receipt/v1`

`ResearchJournal.learning_receipt(question_id, final=False)` is a read-only
projection, not a journal record or agent-authored summary. It contains:

* question ID/digest and objective-confirmation digest;
* sorted evidence-package digests;
* reconciliation, hypothesis, candidate, safety, approval, result, decision,
  and acceleration-summary digests;
* selected experiment ID and selected-specification digest;
* exact task-card digest;
* sorted `{parent_digest, relation, child_digest}` provenance edges;
* a whitelisted execution snapshot (`experiment_id`, `lane_id`, `run_id`,
  `status`, and the four authority digests); and
* `receipt_digest`, SHA-256 of canonical receipt JSON without that field.

Preview receipts use `null` for stages not reached. Projection automatically
selects the sole unsuperseded objective. If multiple unsuperseded confirmations
exist, the caller must supply `objective_confirmation_digest`; a superseded
digest is never silently selected. `final=True` requires the complete singular
chain, a terminal execution binding, and an identical non-null `run_id` and
experiment identity in the result and binding. Result/binding status must also
agree (`PASS`/`FAIL` → `COMPLETED`, `ERROR` → `ERROR`, and `CANCELLED` →
`CANCELLED`). Multiple singular records,
missing links, mismatched authority or dataset identity, modified task bytes,
cross-question records, and damaged stored payloads fail projection. Identical
journal state and task bytes produce byte-for-byte identical receipts.
