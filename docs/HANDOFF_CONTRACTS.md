# Research handoff contracts

These JSON shapes are coordination contracts. They are intentionally documented
before a persistent store or harness adapter exists so later integrations have a
stable boundary.

Every specialist must return one JSON object and no unsupported factual claim.
IDs may be provisional strings in the coordination-only phase; the future
integrity layer will replace them with content-derived identities.

## `research-question/v1`

```json
{
  "schema": "research-question/v1",
  "question_id": "question-...",
  "question": "A focused scientific question",
  "domain": "AI research",
  "measurable_outcome": "What will be measured",
  "primary_metric": "One predeclared metric",
  "constraints": ["time", "compute", "data"],
  "assumptions": ["Explicit starting assumptions"]
}
```

## `evidence-package/v1`

```json
{
  "schema": "evidence-package/v1",
  "question_id": "question-...",
  "claims": [
    {
      "evidence_id": "evidence-...",
      "claim": "A narrowly supported factual claim",
      "source_type": "primary",
      "citation": {
        "title": "Source title",
        "url": "https://example.org/source",
        "authors_or_organization": "Source owner",
        "published_at": null,
        "retrieved_at": "ISO-8601 timestamp"
      },
      "support": "Passage, table field, or dataset field supporting the claim",
      "uncertainty": "Known limitation or disagreement"
    }
  ],
  "conflicts": [],
  "coverage_gaps": []
}
```

## `hypothesis-portfolio/v1`

```json
{
  "schema": "hypothesis-portfolio/v1",
  "question_id": "question-...",
  "hypotheses": [
    {
      "hypothesis_id": "hypothesis-...",
      "statement": "Agent-generated and falsifiable statement",
      "prediction": "Observable prediction",
      "falsification_condition": "Observation that would count against it",
      "supporting_evidence_ids": ["evidence-..."],
      "competing_explanations": [],
      "uncertainty": "Current uncertainty"
    }
  ]
}
```

## `experiment-candidates/v1`

```json
{
  "schema": "experiment-candidates/v1",
  "question_id": "question-...",
  "hypothesis_id": "hypothesis-...",
  "candidates": [
    {
      "experiment_id": "experiment-...",
      "method": "Reproducible method",
      "baseline": "Matched comparison",
      "controls": [],
      "inputs": [],
      "parameters": {},
      "random_seeds": [],
      "metrics": [],
      "success_threshold": "Predeclared threshold",
      "expected_learning": "What outcomes would distinguish",
      "estimated_runtime_minutes": 0,
      "estimated_cost_usd": 0,
      "risk_level": "low"
    }
  ],
  "selected_experiment_id": "experiment-...",
  "selection_rationale": "Expected learning, feasibility, cost, time, and risk",
  "rejected_candidate_rationales": {}
}
```

At least two candidates are required.

## `safety-review/v1`

```json
{
  "schema": "safety-review/v1",
  "experiment_id": "experiment-...",
  "verdict": "APPROVAL_REQUIRED",
  "risks": [],
  "required_controls": [],
  "prohibited_actions": [],
  "approval_question": "Exact decision requested from the human",
  "review_limitations": []
}
```

The coordination layer cannot convert this record into an approval. Only the
human may approve execution.

## `experiment-result/v1`

```json
{
  "schema": "experiment-result/v1",
  "experiment_id": "experiment-...",
  "run_id": "run-...",
  "execution_source": "external-or-future-harness",
  "code_identity": "commit or artifact digest",
  "dataset_identity": "version and digest",
  "environment_identity": "lockfile or image digest",
  "parameters": {},
  "random_seeds": [],
  "metrics": {},
  "artifact_refs": [],
  "started_at": "ISO-8601 timestamp",
  "completed_at": "ISO-8601 timestamp",
  "status": "PASS",
  "limitations": []
}
```

The current coordinator consumes this record but does not produce it.

## `updated-decision/v1`

```json
{
  "schema": "updated-decision/v1",
  "question_id": "question-...",
  "hypothesis_id": "hypothesis-...",
  "experiment_id": "experiment-...",
  "run_id": "run-...",
  "decision": "support",
  "rationale": "Reasoning grounded in measured results",
  "supporting_evidence_ids": [],
  "remaining_uncertainty": [],
  "next_experiment": {},
  "human_review_required": true
}
```

Allowed decisions are `support`, `revise`, `reject`, and `inconclusive`.

