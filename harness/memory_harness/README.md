# Local research memory

`memory_harness` provides the local integrity layer used by AI Researcher. It
stores reviewed records in SQLite and keeps planning, context, privacy,
provenance, and snapshot operations deterministic.

The active implementation is local-first:

- SQLite is the durable system of record.
- Content hashes bind records to their exact payloads.
- Evidence, hypotheses, experiment specifications, approvals, results, and
  interpretations remain distinct records.
- Optional EverOS adapters can contribute local experience retrieval.
- Search failures are isolated and never weaken approval or provenance gates.
- Snapshot and restore operate only on explicitly selected local stores.

There is no remote database client or remote vector-search dependency in this
package. Network access belongs to explicitly declared research tools, not the
memory layer.

The package is intentionally imported by the portable orchestrator only when a
structured memory handoff is present. Ordinary harness tasks remain usable
without initializing a memory store.
