# Retrospective — v1-8-3-cf4-durable-binding-registry

## Goal

Implement the missing durable CapabilityBindingCatalog registry seam. Add an FD-bound append-only index that persists only capability id, immutable binding digest, and the bounded Agent planner projection; never persist executable entrypoints, raw datasets, or binding internals. Provide a DurableCapabilityBindingCatalog compatible with the existing NotebookService catalog type. Registration must validate through the existing server-owned catalog before durable append, be idempotent for the same identity, reject rebinds and malformed journals fail-closed, and restore only through a caller-supplied trusted binding loader that re-verifies the binding. Keep execution authorization and process dispatch untouched; this slice only makes the existing recommendation/service lookup restart-recoverable.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-07-27T09:55:00.000Z `tdd_red_before_binding_registry`; cause_status: `known`; cause: The durable binding registry tests failed during collection because the new registry module does not exist yet.; resolution: `accepted`; lesson: Define persistence as an identity index before adding service restoration logic.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `binding-registry-index-first`: occurrences=1; cause_status: `known`; root cause: The durable binding registry tests failed during collection because the new registry module does not exist yet.; solution: `accepted`

## Added tests

- `tests/test_capability_binding_registry.py`
- `tests/test_capability_binding_registry.py;tests/test_notebook_capability_binding.py;tests/test_capability_notebook_binding.py;tests/test_no_exercise_specific_naming.py`

## New rules

- `binding-registry-index-first`: line experience occurrence(s)=1

## Future guidance

- Define persistence as an identity index before adding service restoration logic.
- Persist references to trusted capability facts and require an authority-backed loader after restart.

## Event index

- #1: `00807a9a-1727-4b8d-8edf-024f03d0e18b` | 2026-07-27T05:55:55.947Z | STATE_CHANGE/line_started | incident=`5cc191a8-40e2-47fd-8101-0a1fd5dbc45f` | lesson_key=`frozen-context-before-start` | event_sha256=`c286d1b59501c8dbbdc5ad977401d017d16f1933e68ee77c75cd3bedd2f49eb1`
- #2: `aabcdef0-1234-4567-89ab-cdef01234567` | 2026-07-27T09:55:00.000Z | FAILURE/tdd_red_before_binding_registry | incident=`aabcdef0-1234-4567-89ab-cdef01234568` | lesson_key=`binding-registry-index-first` | event_sha256=`efafb88eee23629687b8d05089b27dc5c585c0bc411d805f5330fcebecf47c3d`
- #3: `bbcdef01-2345-4678-9abc-def012345678` | 2026-07-27T09:59:00.000Z | REVIEW/durable_binding_registry_review_accepted | incident=`bbcdef01-2345-4678-9abc-def012345679` | lesson_key=`binding-index-reference-only` | event_sha256=`d44f5b037aaf5f2821dd17816db3fbbab9b259181e761ad1e01065b74a5d76f2`
- #4: `ccdef012-3456-4789-abcd-ef0123456789` | 2026-07-27T10:01:00.000Z | GATE/durable_binding_registry_targeted_gate | incident=`ccdef012-3456-4789-abcd-ef0123456790` | lesson_key=`durable-index-is-not-startup-wiring` | event_sha256=`a645a981c60c1941941926000a746391256303985f8dd36c5f8387c6b823a4a2`
- #5: `def01234-5678-49ab-cdef-0123456789ab` | 2026-07-27T10:02:00.000Z | STATE_CHANGE/durable_binding_registry_completed | incident=`ddef0123-4567-489a-bcde-f01234567890` | lesson_key=`close-durable-index-before-startup-wire` | event_sha256=`72fd6730e6444d85eb47e8501d239549522b20d595dcc6d8d27e0e279fa4ed03`
