# WO-P1 Data Consumer Projection Readers

## Scope

Implement the objective in:
`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-projection-readers-objective.md`.

## Allowed implementation surface

- `backend/workbench/services/data_consumer_projection_service.py`
- `backend/workbench/services/data_consumer_host_resolver.py`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `backend/workbench/http/runs_routes.py`
- `backend/workbench/http/data_operation_routes.py`
- `tests/test_v189_data_consumer_projection.py`
- `tests/test_v189_central_evidence_consumer_mount.py`
- this objective, work-order, and a dated handoff

## Required boundaries

- The capability issuer, project root, operation-record store, and catalog are
  server-owned.
- Consumer wrappers receive only an opaque capability and bounded selectors;
  they do not receive a path, dataframe, raw payload, or registry.
- Every available result is bound to one project, session, run, operation
  record, execution claim, output-port digest, and live catalog digest.
- Missing, foreign, stale, malformed, uncommitted, or ambiguous state is
  `UNAVAILABLE`/typed failure, never a guessed or recomputed result.

## Required tests

- New central projection tests for successful shared Agent/Notebook/Report
  reads and all fail-closed cases in the objective.
- Existing data host, central data mount, catalog coverage, and runtime
  bootstrap tests.
- Existing central evidence Report boundary tests where the environment can
  provide the required process-private authority socket.

## Known gates

Browser, real external provider, cross-process authority persistence, full host
startup, merge, tag, release, and deployment acceptance are not verified by
this work-order.
