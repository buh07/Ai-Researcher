# Limitations and claim boundaries

## Current evidence status

No completed live-provider, live-Omnigent discovery loop, or OpenML experiment
result is committed to this repository. Runtime state and generated artifacts
are Git-ignored by design. Tests and fixtures can demonstrate software behavior
but cannot establish a scientific improvement, genuine provider delegation, or
10x discovery acceleration.

The repository implements the objective/preflight/approval gates, matched
runner, source-digested workflow telemetry, provider option validation, full
review/ingest/retire/shutdown lifecycle, deterministic receipt, and reporting
paths. “Implemented” is not “observed”: no attributable human objective or
approval, provider credentials, live specialist trace, real overlapping
branches, accepted OpenML result, final live receipt, or two clean rehearsals is
included in this checkout.

The terminal renderer displays caller-supplied mappings. It validates finite
JSON, fixed presentation order, and explicit rubric statuses; it does not by
itself verify journal reachability, signatures, citations, digest correctness,
artifact existence, or whether an execution was live. Those properties must be
established by the record/journal integrity layer and retained run artifacts.
The rubric map’s `expected_artifacts` are inventory targets, not evidence.

## Scientific scope

- The proposed OpenML classification task is a proxy for experiment-selection
  efficiency, not a Nobel-level discovery or proof of general scientific
  acceleration.
- One task, one split, or a small seed count cannot support broad superiority.
  Dataset selection and threshold choice may strongly affect the result.
- Evidence-guided selection can inherit publication, retrieval, model, and
  source-availability biases. Conflicts and coverage gaps must remain visible.
- A result-driven next experiment is a recommendation requiring human review,
  not authorization to continue autonomously.
- Hypotheses are agent-generated proposals, not external facts. Local
  measurements need immutable run/artifact support, not manufactured literature
  citations.

## Acceleration and 10x claims

- `trials_to_threshold` is the predeclared primary endpoint. Held-out
  `accuracy` is a secondary quality/non-inferiority check and must not be
  substituted for the primary endpoint.
- Trials to threshold is censored when the threshold is not reached. A censored
  comparison is not converted to an arbitrary finite point estimate.
- Failed, errored, and timed-out attempts count once trial-specific work starts.
  Proposed-method retrieval, planning, tool, and ingestion overhead cannot be
  excluded selectively.
- Without arm telemetry, the matched runner measures in-process model
  evaluation/result ingestion only and records `overhead_included=false`. With
  source-digested telemetry for **both** arms it includes observed retrieval,
  planning, approval, preflight, and agent/tool time in the threshold boundary
  and labels it `end-to-end-arm-workflow`. Estimated, one-sided, or missing
  telemetry is not silently treated as zero.
- The accepted `experiment-result/v1` intentionally precedes and excludes
  decision timing. After independent analysis, the journal derives latency from
  Harness's hashed acceptance boundary and its own decision-append boundary;
  the digest-addressed measurement is stored in `updated-decision/v1` and bound
  by `acceleration-summary/v1`.
- Fewer trials does not mean faster discovery when elapsed time fails to improve.
  Quality/safety regression, mismatched controls, or post-hoc thresholds block a
  positive acceleration claim.
- Conservative, expected, and optimistic scaling scenarios are forecasts. They
  must be labeled separately from observed results.
- Approaching 10x remains unvalidated. It would require repeated prospective
  measurements across datasets/domains, useful early evidence, sufficiently
  expensive baseline search, safe parallelism, automation, reliable providers,
  and no loss of scientific quality or human governance.
- Objective confirmation and consequential approval remain serial by design;
  they are not bottlenecks to remove for a headline ratio.

## Parallelism

Async configuration is not proof of parallel work. A parallel-discovery claim
requires authoritative branch start/completion times whose half-open intervals
strictly overlap. Queueing, clock ambiguity, missing timestamps, or intervals
that only touch must be reported as `UNMET`. Parallel evidence retrieval also
does not establish end-to-end speedup without a matched elapsed-time comparison.
`MET` also requires completed distinct invocation IDs and producer sessions,
distinct nonempty cited evidence packages, and reconciliation that uses
evidence from every branch. Shared evidence or caller-authored timing cannot
satisfy it.

## Data, providers, and reproducibility

- OpenML and model-provider availability, API behavior, credentials, rate
  limits, licenses, privacy terms, and dataset versions are external and can
  change. Recheck them before every consequential run.
- A provider executable and explicit model/options are required locally. Codex
  requires `reasoning_effort` and `service_tier`; Claude Code requires `effort`;
  Qwen Code accepts no provider options. Validation proves configuration shape,
  not provider availability or successful authentication.
- Cached fixtures prevent network-dependent tests but do not prove current live
  access or licensing.
- Reproduction requires Git and dependency identity, exact data digest, split,
  seeds, environment, parameters, budgets, command/task identity, logs, and
  artifact digests. Provider nondeterminism may remain even with these controls.
- Cost and token metrics may be incomplete when a provider does not expose them;
  mark them unavailable rather than estimate silently.

## Operational and security limits

- The SQLite journal and local harness target a single trusted operator, not a
  hostile multi-tenant environment, regulated deployment, or distributed
  consensus.
- The integrated harness reduces execution scope but is not a sandbox guarantee
  against every malicious dependency, provider, model output, or host compromise.
- The bounded path checks the confirmed dataset/metric, trial/time/cost limits,
  CPU compute, read-only OpenML network mode, artifact-write permission, and
  risk constraints. These string- and record-level controls do not replace OS
  isolation, billing controls, network policy, or operator monitoring.
- Secrets and private source content must not enter prompts, journal records,
  task cards, artifacts, terminal captures, or Git.
- `experiment_bindings` is a mutable lifecycle projection; it must not be
  described as append-only scientific evidence. Immutable authority digests
  remain fixed while allowed lifecycle fields advance.
- A bundle validation or test pass is not an independent security audit,
  reproducibility replication, peer review, or production-readiness claim.

## Validation still required for a challenge claim

1. Confirm the complete objective and feasibility packet as a human.
2. Capture a live multi-specialist Omnigent trace and actual interval overlap.
3. Verify every external claim and citation against its source.
4. Execute one exact approved, bounded experiment under matched controls.
5. Complete explicit wait, review/acceptance, Harness-owned terminal-evidence
   readback, result ingestion, retirement/force-stop as applicable, and shutdown.
6. Retain immutable result/log/artifact support and independent analysis.
7. Reconstruct the deterministic final learning receipt after a terminal result.
8. Recompute acceleration with censoring and end-to-end telemetry rules.
9. Repeat across seeds and tasks and quantify uncertainty.
10. Rehearse the clean-checkout demo twice without manual state repair.
11. Update the rubric map and submission checklist from real artifacts only.
