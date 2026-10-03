# Integrated components

The `harness/` tree is maintained as part of AI Researcher. It contains:

- the portable lane and lifecycle orchestrator;
- local SQLite-backed memory and structured handoff contracts;
- provider adapters and immutable worker payload assets;
- the optional diagnostic watcher;
- the vendored EverOS local-memory implementation, including its original
  Apache-2.0 license and notice files.

Nested Git metadata, submodule configuration, machine-local runtime state, and
remote-database integrations are intentionally excluded. Future refreshes must
be reviewed as source updates and committed directly to this repository.
