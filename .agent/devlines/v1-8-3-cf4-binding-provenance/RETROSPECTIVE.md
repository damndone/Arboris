# Retrospective — v1-8-3-cf4-binding-provenance

## Goal

Extend the capability-bound Notebook option chain so the immutable binding reference survives materialization, the persisted Pipeline Draft provenance, and typed Agent trace events. Add a backward-compatible OptionMaterialization@1.1 successor while preserving native/unbound OptionMaterialization@1.0 records. Revalidate the current server binding and the materialization/Draft provenance before replay or downstream use; fail closed on missing, stale, or mismatched binding references. This line is control-plane and provenance-only: it must not add process, network, or automatic execution behavior.

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

- #2 2026-07-27T06:31:00.000Z `test_red`; cause_status: `known`; cause: The provenance contract test exposed that the materialization successor type was not yet implemented.; resolution: `open`; lesson: Introduce the new persisted contract through a focused red test before changing materialization consumers.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `binding-provenance-contract-red`: occurrences=1; cause_status: `known`; root cause: The provenance contract test exposed that the materialization successor type was not yet implemented.; solution: `open`

## Added tests

- `167 passed: binding provenance materialization trace contract lock naming gate`
- `tests/test_capability_binding_provenance.py`

## New rules

- `binding-provenance-contract-red`: line experience occurrence(s)=1

## Future guidance

- A capability identity is not complete until every downstream consumer verifies the same persisted digest.
- Introduce the new persisted contract through a focused red test before changing materialization consumers.

## Event index

- #1: `f1040e27-3549-4520-91df-b2ae173c14b0` | 2026-07-27T06:25:47.029Z | STATE_CHANGE/line_started | incident=`b07503da-662a-4f7c-8a4d-e3363b52ba93` | lesson_key=`frozen-context-before-start` | event_sha256=`be9f112f59d90d612b2593636b593d54ffaebb20f048ff578dcdbccfebeb6a58`
- #2: `1fbc0a1c-5d2b-40e9-94b7-79a2d7e8c3f1` | 2026-07-27T06:31:00.000Z | FAILURE/test_red | incident=`c92dd05d-a850-4f66-9ec6-322cb6c993ba` | lesson_key=`binding-provenance-contract-red` | event_sha256=`361e2e5eaa6087423ecf6ec944076a2565c5bbe29ed79ab977ead64e10811e8c`
- #3: `67e89d01-fd1c-4a03-a0d9-4f7a2d2784b0` | 2026-07-27T06:38:00.000Z | REVIEW/provenance_review | incident=`1da843a7-7eed-4f98-9a03-f4b07d6aebf1` | lesson_key=`binding-identity-through-consumers` | event_sha256=`5a71f3eac3628d55b068d98550543a076f43d4115ba0fa882274cb2ae0c4fae7`
- #4: `4e7d9ab8-7b51-49f5-8f26-37de04ef3318` | 2026-07-27T06:39:00.000Z | GATE/target_tests | incident=`e12524ee-d55d-4d86-8f9f-7d0eb17a5fc3` | lesson_key=`provenance-gate-separate-from-host` | event_sha256=`22622a24ba903949f5aafad9a867b610b17e1a050178cff9e34fe3b3858aeac6`
- #5: `db6db1f5-5cb9-42ea-8695-249af2d045db` | 2026-07-27T06:42:00.000Z | STATE_CHANGE/implementation_complete | incident=`ba0971ef-d849-48f8-95f0-7576c0c10e0e` | lesson_key=`provenance-complete-after-replay-check` | event_sha256=`38b7ecc1ec45503f841186c1aca2d618727751fed17fbe54c671aac566733468`
