# Challenge submission checklist

This inventory prevents configuration, fixtures, and intended paths from being
misrepresented as completed evidence. Check an item only after inspecting the
referenced artifact. Generated runtime artifacts under `artifacts/`, `results/`,
and `runtime/` are intentionally ignored and must be exported separately for a
submission bundle.

Status key: `[x]` repository artifact present; `[ ]` not established here. A
present implementation artifact is not proof of a live scientific outcome.

## Reproducible repository

- [x] Repository overview, authority boundaries, quickstart, and exact commands:
  `README.md`
- [x] Pinned Python project metadata: `pyproject.toml` and `uv.lock`
- [x] Omnigent bundle validator: `scripts/validate_bundle.py`
- [x] Deterministic report/rubric renderer:
  `scripts/render_research_report.py` and `src/ai_researcher/reporting.py`
- [x] All thirteen immutable record contracts plus deterministic learning
  receipt projection: `src/ai_researcher/records.py` and
  `src/ai_researcher/journal.py`
- [x] Fixture/live matched runner with `trials_to_threshold` primary and
  `accuracy` quality guard: `src/ai_researcher/experiment.py`
- [x] Unit/integration test sources: `tests/`
- [x] Two-minute operator script: `DEMO.md`
- [x] Claim boundaries and pending validation: `docs/LIMITATIONS.md`
- [x] Captured final check output, durations, Git commit, lock digest, and skips:
  external bundle `Ai-Researcher-submission-evidence/checks/` for commit
  `8a814084041a3a3051bcb751552474c8242f623b`
- [ ] Two clean rehearsals from fresh runtime state without manual repair

Clean-checkout software checks (do not substitute these for live evidence):

```bash
uv sync --frozen
uv run python scripts/validate_bundle.py
uv run pytest
TMPROOT=$(mktemp -d /tmp/ai-researcher-harness-tests.XXXXXX)
(
  trap 'rm -rf "$TMPROOT"' EXIT
  cd harness
  TMPDIR="$TMPROOT" TEMP="$TMPROOT" TMP="$TMPROOT" \
    PYTHONPATH=. ../.venv/bin/python -m unittest discover \
      -s orchestrator_harness/tests -p 'test_*.py'
)
```

Use the node-local temporary directory exactly as shown. Shared NFS temporary
storage can report a delayed-delete `Directory not empty`/`.nfs*` error during
`TemporaryDirectory` cleanup even when every product assertion passed. The
node-local path removes that filesystem race without skipping or changing a
test.

## Objective and feasibility

- [ ] Attributable human confirmation of objective, primary metric, dataset,
  risk tolerance, and consequential execution scope
- [ ] Question and objective-confirmation digests propagated through the chain
- [ ] Data/API availability check and stable dataset version/digest
- [ ] License, access, redistribution, privacy, and cache decision
- [ ] Compute, time, cost, network, and trial budgets
- [ ] Named human-confirmed fallback, if the primary data source fails

## Omnigent orchestration — 30%

- [x] Director and five distinct specialist definitions:
  `agents/research-director/`
- [x] Structured handoff contracts: `docs/HANDOFF_CONTRACTS.md`
- [ ] Live director session identity plus specialist invocation identities
- [ ] Two independent evidence branches with authoritative start/end timestamps
- [ ] Strictly overlapping intervals, or rubric status explicitly `UNMET`
- [ ] Preserved branch sources, conflicts, gaps, and reconciliation
- [ ] Visible result-driven update to the plan
- [ ] Final machine-readable research chain and learning receipt

Suggested generated artifacts:
`artifacts/research-chain.json`, `artifacts/learning-receipt.json`, and an
appropriately redacted live session trace.

## Breakthrough potential — 25%

- [x] Proxy-question significance, beneficiaries, bottleneck, and enabling
  breakthrough narrative: `README.md`
- [x] Explicit single-task and generalization limits: `docs/LIMITATIONS.md`
- [ ] Cited domain evidence supporting the importance of the bottleneck
- [ ] Live evidence explaining how the result changes the larger research path
- [ ] Credible multi-domain prospective validation plan in the final receipt

The proposed experiment is an enabling validation, not a completed breakthrough.

## Discovery acceleration and learning — 20%

- [ ] Predeclared endpoint, threshold, trial-counting, overhead, and censor rules
  preserved in the run chain
- [ ] Matched baseline/proposed data, split, seeds, budgets, and compute
- [ ] Trial, wall/compute time, quality, intervention, cost/token, and
  decision-latency measurements where available
- [ ] Source-digested retrieval, planning, approval, preflight, and agent/tool
  telemetry for **both** arms before any end-to-end speed claim
- [ ] Reproducible formula and denominator with no forbidden positive claim
- [ ] Immutable result causes the recorded next decision/experiment
- [ ] Conservative, expected, and optimistic path-to-10x scenarios clearly
  separated from observations
- [ ] Repeated seeds/tasks or an explicit statement that they remain future work

Suggested generated artifact: `artifacts/acceleration-summary.json`.

## Scientific rigor — 15%

- [x] Scientific record and digest implementation: `src/ai_researcher/`
- [x] Separate experiment designer, safety reviewer, and results analyst
- [x] Exact-approval/bounded-execution architecture:
  `docs/HARNESS_INTEGRATION.md`
- [x] Explicit provider-option validation and completion-review/readback/
  ingestion/force-stop/retire/shutdown APIs:
  `src/ai_researcher/harness_adapter.py`
- [ ] Every external fact resolves to verified citation metadata
- [ ] Every hypothesis resolves its supporting evidence IDs
- [ ] At least two fairly compared candidates and rejection rationale
- [ ] Predeclared metric, controls, data identity, seeds, and success threshold
- [ ] Exact-digest human approval and explicit launch evidence
- [ ] Immutable result, logs/artifact digests, limitations, and uncertainty
- [ ] Independent result interpretation without measurement mutation

Suggested generated artifact: `artifacts/experiment-result.json` plus referenced
logs and digests.

## Creativity and responsibility — 10%

- [x] Digest-addressed learning-receipt design and deterministic terminal view
- [x] Human ownership and two-gate demo narrative
- [x] Independent safety role and explicit claim boundaries
- [ ] Final learning receipt reconstructed from a complete validated chain
- [ ] Exact objective/experiment/approval/task-card digest binding in live run
- [ ] Enforced dataset/metric/trial/time/cost/compute/network/mutation/risk
  evidence and clean Harness shutdown
- [ ] Actual parallel discovery evidence, or honest `UNMET` status

## Submission inventory

- [ ] Public repository URL and exact submission commit
- [ ] Agent definitions, policies, tools, and consolidated input/output contracts
- [ ] Human objective confirmation and feasibility record
- [ ] Experiment source plus dataset identity, digest, license, and access note
- [ ] Evidence packages, hypotheses, candidate comparison, and safety review
- [ ] Exact approval, task-card digest, result, artifacts, and updated decision
- [ ] Learning receipt and research-chain JSON
- [ ] Acceleration summary and path-to-10x sensitivity scenarios
- [ ] Generated `rubric-artifact-map/v1` whose evidence paths all exist
- [ ] Test, live-run, regression, and rehearsal evidence
- [x] Limitations and future validation: `docs/LIMITATIONS.md`
- [x] Two-minute script: `DEMO.md`

Generate the terminal view and rubric map only after exporting the real chain:

```bash
uv run python scripts/render_research_report.py \
  artifacts/research-chain.json \
  --rubric-output artifacts/rubric-artifact-map.json
```

Review every `status` and `evidence_artifacts` entry manually. The renderer does
not infer completion, verify that a listed file exists, or turn an expected path
into evidence.

## Live lifecycle evidence required

Do not check the live-run items merely because their APIs or tests exist. A
complete retained run must contain, in order:

1. Operator-authored objective confirmation and a passing feasibility record.
2. Distinct, completed evidence invocations and reconciliation. `MET` requires
   authoritative strict interval overlap, distinct producer sessions,
   invocation IDs and cited packages, plus evidence from every branch.
3. Compared candidates, independent safety review, operator-authored approval,
   staged task-card digest, and separate digest-confirmed launch.
4. Explicit provider/model/options: Codex `reasoning_effort` + `service_tier`,
   Claude Code `effort`, or an empty Qwen Code option object.
5. A converted pre-analysis `experiment-result/v1` whose primary metric is
   `trials_to_threshold`, whose `accuracy` field supplies the quality guard, and
   whose end-to-end telemetry is either measured for both arms or honestly
   unavailable.
6. Worker-written Harness `RESULT.json`, explicit completion review/acceptance,
   Harness-owned terminal-evidence readback, verified artifact ingestion,
   result-driven decision with a journal-authored, acceptance-bound timing
   artifact, result-and-decision-bound acceleration summary, and final receipt.
7. Acceptance-backed retirement (or explicit force-stop for cancellation) and
   exact-confirmation Harness shutdown.

The live artifact bundle is external to Git. Export the reconstructed chain and
final receipt, then render the rubric map with the command above. Keep absent
artifacts `UNAVAILABLE`/unchecked.
