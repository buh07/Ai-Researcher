# Harness integration: authoritative live execution

This project treats Omnigent planning, human authority, and Harness execution as separate trust boundaries. A fixture run is a hermetic test only; it is never provider or scientific evidence.

## Required gates

1. Record the research question and operator-confirmed objective with `scripts/record_human_authority.py`.
2. Run `preflight_confirmed_objective`. For a live OpenML run this performs the read-only pinned task/dataset check before any experiment approval. The objective's exact `risk_tolerance.level`, dataset identity and governance attestation are checked.
3. Journal independently produced evidence branches, reconciliation, hypotheses, competing experiment candidates, and the independent safety review.
4. Display `request_experiment_approval`; record a separate `human-approval/v1` through the operator-only script.
5. `stage_approved_experiment` writes an immutable task card. Staging does not launch.
6. A human must reconfirm the exact approval digest and explicitly enable execution before `launch_approved_experiment`.

Set `AI_RESEARCHER_ENABLE_EXECUTION=1` only for the consequential command window. The public launch requires an explicit provider options object:

| Provider | Required options | Optional options |
|---|---|---|
| `codex` | `reasoning_effort`, `service_tier` | `launcher` (`codex` or `ollama`) |
| `claude-code` | `effort` | none |
| `qwen-code` | none (`{}`) | none |

The adapter delegates validation to the shipped provider binding before bootstrap. Unknown, missing, duplicated, or blank preferences fail before Harness state is mutated.

## Run, review, and ingestion lifecycle

The production path is one durable `HarnessAdapter` authority chain, even though individual tool calls may reconstruct an adapter over the same SQLite journal:

1. `launch_approved_experiment` bootstraps one exact lane, obtains its Harness `run_id`, and durably advances `STAGED -> LAUNCHING` **before** the provider worker can start. The worker accepts only this exact `LAUNCHING`/`LAUNCHED` authority. After Harness confirms the same run identity the adapter advances to `LAUNCHED`. An ambiguous launch or final-persistence failure triggers exact-lane force-stop and advances to `CANCELLED` only after `FORCE_STOP_OK` **and** a retired lane record for that exact `run_id`; if cleanup cannot be proven, `LAUNCHING` remains visible for operator recovery and is never rolled back to `STAGED`.
2. `get_harness_experiment_status` reads the authoritative active lane; `wait_for_experiment` blocks read-only for that lane's review boundary.
3. The launched worker runs the approved matched experiment. `build_harness_result` converts the exact validated `experiment-result/v1` into a `result/v1` envelope. This pre-analysis result deliberately contains no decision latency. The worker writes that returned object unchanged to its worktree root as `RESULT.json`. The converter does **not** write another worktree or approve its own result.
4. A distinct ROOT/operator reviews the result and calls `review_experiment_completion` with an explicit outcome, acceptance decision, review summary, evidence list, and the original approval digest. Nothing auto-accepts. Scientific acceptance requires a `PASS` review; `FAIL` and `BLOCKED` outcomes can only be rejected and cannot enter the scientific journal. An inconclusive `UNKNOWN` review must be repeated rather than converted into an acceptance decision.
5. `read_experiment_terminal_evidence` rereads the review, acceptance, task-card authority and reviewed result from the configured Harness runtime. Caller-created JSON cannot substitute for this evidence.
6. `ingest_harness_experiment_result` extracts the exact `RESULT.json.scientific_result`, verifies all immutable authority, dataset, seed, parameter, metric and artifact links, appends it to the research journal, and preserves Harness's accepted `decided_at` boundary and acceptance content hash in the durable execution binding.
7. Only after that accepted result exists does the results analyst submit `updated-decision/v1`. The journal supplies an embedded `decision-timing-measurement/v1` artifact from the preserved Harness acceptance boundary and its own completion clock, hashes that artifact, and rejects caller-authored timing. `as_acceleration_summary` consumes the immutable updated decision and binds its digest, timing-artifact digest, and result digest. It never rewrites the result. `get_learning_receipt(final=true)` fails closed unless all three records are present and mutually consistent.
8. `retire_experiment` derives the acceptance reference from Harness-owned storage. `force_stop_experiment` is for a stuck live lane. Both require exact approval-digest confirmation and the execution environment gate. A force-stop is considered complete only when Harness returns `FORCE_STOP_OK` and its authoritative lane record proves that the exact `run_id` is retired. The tool persists and returns a hash-bound `harness-force-stop-evidence/v1` cancellation receipt, which `read_experiment_cancellation_evidence` can revalidate after the lane leaves the active index; failed cleanup never advances the journal to `CANCELLED`. This is terminal cleanup evidence, not a reviewed scientific result, and it cannot be ingested as one.
9. `shutdown_research_harness` requires the literal phrase `SHUTDOWN RESEARCH HARNESS`; it is never invoked automatically.

## Failure and safety behavior

- Wrong confirmation, stale objective, changed task bytes, changed run identity, invalid provider configuration, absent review evidence, rejected review, or mismatched scientific result all fail closed.
- Per-arm model evaluation runs in a dedicated killable process. Exhausting the remaining arm wall-time budget terminates/kills and joins that process before the trial is recorded as `TIMEOUT`, so evaluator work cannot leak into a later trial or arm. Because a killed or fatally exited process cannot deliver its final process-clock measurement, its trial and arm `compute_seconds` are `null`, availability is `UNAVAILABLE`, and `compute_unavailable` blocks acceleration claims; partial CPU samples are never mislabeled as exact measurements.
- A successful force-stop is already the lane's retirement path. Its cancellation receipt remains readable after the active lane is removed; no second acceptance-based retirement is required or permitted.
- Cleanup authority survives objective supersession for the exact already-bound lane/run only. `force_stop_experiment` accepts the ambiguous durable `LAUNCHING` state as well as `LAUNCHED`/`RUNNING`, while status adoption, result review/ingestion, and new execution continue to reject stale authority and do not accept `LAUNCHING`.
- Status/wait/evidence reads are non-consequential. Launch, completion acceptance, force-stop, retire, and shutdown have explicit gates.
- A rejected completion is not ingested and may not be retired as accepted evidence.
- The task card binds objective, experiment, approval and selected candidate bytes. The Harness review hash binds the `RESULT.json` bytes that include `scientific_result`.
- Artifact URIs are rehashed locally and may not escape their declared artifact directory.

## Test isolation

Project tests never create or overwrite `harness/local-config/harness-config.json`. Temporary runtime/configuration fixtures live entirely under pytest temporary directories. The integrated Harness tests should be runnable repeatedly without leaving `.agent-workspace` or local configuration artifacts in the source checkout.
