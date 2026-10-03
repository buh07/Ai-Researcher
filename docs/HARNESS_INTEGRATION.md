# Harness integration boundary

## Ownership

- Omnigent is the only scientific workflow orchestrator.
- The integrated harness owns bounded experiment execution and operational
  lifecycle only.
- A human owns consequential approval.
- The results analyst interprets immutable measurements but cannot rewrite
  them.
- SQLite is the local system of record for handoffs and identity bindings.

The only supported code boundary is `ai_researcher.harness_adapter`. Omnigent
tools must not invoke the harness CLI directly.

## Execution sequence

1. Omnigent produces and records at least two experiment candidates.
2. The independent safety reviewer returns `APPROVAL_REQUIRED`, `REVISE`, or
   `REJECT`.
3. `request_experiment_approval` hashes the exact selected specification and
   returns the approval question, required controls, and prohibited actions.
4. A human approves that exact digest using `human-approval/v1`.
5. `stage_approved_experiment` creates one immutable harness task card and one
   experiment-to-lane binding. It does not launch anything.
6. Launch requires both the exact approval digest and
   `AI_RESEARCHER_ENABLE_EXECUTION=1`.
7. The harness owns its lane, process, review, acceptance, and cleanup records.
8. A complete `experiment-result/v1` is appended to the journal before the
   results analyst receives it.

## Identity bindings

The journal binds:

- experiment ID and selected-specification digest;
- safety-review record digest;
- human-approval record digest;
- generated task-card path;
- harness lane and run identity;
- result record digest and artifact references.

Reusing an identity with different content fails closed. Missing or mismatched
approval prevents staging, and a mismatched confirmation prevents launch.

## Local setup

Copy the harness configuration examples into the ignored local directory and
set the root workspace to this repository:

```bash
mkdir -p harness/local-config
cp harness/examples/harness-config.example.json \
  harness/local-config/harness-config.json
cp harness/examples/resource-manifest.example.json \
  harness/local-config/resource-manifest.json
```

Edit `root_workspace`, then initialize the harness:

```bash
cd harness
PYTHONPATH=. ../.venv/bin/python -m orchestrator_harness.operator_launch \
  --json harness setup
```

Execution remains disabled until the operator explicitly exports:

```bash
export AI_RESEARCHER_ENABLE_EXECUTION=1
```

Credentials, local configuration, journal files, task cards, runtime state,
and experiment artifacts are ignored by Git.
