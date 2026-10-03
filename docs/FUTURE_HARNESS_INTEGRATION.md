# Future harness integration boundary

## Current state

There is no harness integration in this repository.

The Omnigent bundle does not:

- Import `memory_harness` or `orchestrator_harness`
- Invoke a harness CLI or subprocess
- Read or write a harness runtime directory
- Share a SQLite file with the harness
- Assume harness lane, branch, event, or provider identifiers
- Execute experiments

This separation is intentional while the external harness is changing.

## Future adapter responsibilities

When the harness is ready to import, add one adapter owned by this repository.
The adapter should translate only between stable research handoffs and stable
harness operations.

Expected inbound operations:

- Submit an approved `experiment-candidates/v1` selection
- Bind the exact human approval
- Request one bounded experiment run
- Read run status without mutating scientific records
- Receive an exact `experiment-result/v1`

Expected identity bindings:

- Omnigent session ID
- Research question ID
- Hypothesis ID
- Experiment ID and digest
- Human approval ID and digest
- Harness campaign/lane/run identity
- Code, data, environment, and result digests

## Authority boundary

- Omnigent remains the scientific workflow orchestrator.
- The harness owns experiment execution and operational lifecycle.
- The human owns consequential approval.
- The analysis agent interprets evidence but cannot alter measurements.
- Neither side may silently reconstruct missing identities or approvals.

## Integration acceptance criteria

The future integration is acceptable only when:

1. A missing or mismatched approval prevents launch.
2. One Omnigent experiment maps to one exact harness execution identity.
3. The harness returns measurements and artifact references without accepting
   the scientific interpretation.
4. Omnigent records the updated decision without rewriting the result.
5. Replay is idempotent and conflicting replay fails closed.
6. Both sides retain enough evidence to reconstruct the complete chain.

