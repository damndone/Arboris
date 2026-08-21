# WO-P1 Data Host Resolver

## Scope

Implement the server-owned durable data host resolver described by:
`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-host-resolver-objective.md`.

## Required boundaries

- Inputs are typed opaque identities only.
- The server owns the project root, catalog, operation-record authority, and
  output/evidence rehydration.
- No rows, frames, paths, arbitrary code, or client-created typed ports cross
  the Agent/Notebook/Report provider boundary.
- The resolver returns `UNAVAILABLE`/typed errors for missing, stale,
  ambiguous, or malformed durable state.

## Required tests

- New focused tests for scope, identity, ambiguity, malformed durable output,
  raw input rejection, and successful server rehydration.
- Existing `tests/test_v189_data_host_port.py` and
  `tests/test_v189_consumer_catalog_contract.py`.
- Existing `tests/test_v189_agent_notebook_runtime_bootstrap.py`.

## Known gates

Browser, real external provider, cross-process persistence, full host startup,
merge, tag, release, and deployment acceptance are not verified by this
work-order.
