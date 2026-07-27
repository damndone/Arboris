# Retrospective — v1-8-3-mem1-project-context-index

## Goal

Implement MEM1 as a rebuildable, content-addressed Project/RunFamily context index and pure context projection. Define bounded immutable index revisions that reference canonical source manifests and revision/hash cursors without copying raw datasets or unbounded artifacts; build only from caller-supplied canonical source facts; persist and reload append-only revisions with deterministic idempotency; reject stale or malformed inputs; and expose omission/truncation provenance in the projection. Declare package-local trace payload contracts only. The slice must not edit the shared Context Compiler, app startup, Notebook surface, capability ranking/admission, authorization, or dispatch paths, and memory must remain default-off and non-authoritative.

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

- #2 2026-07-27T09:05:00.000Z `tdd_red_before_project_index`; cause_status: `known`; cause: The new project context index tests failed during collection because the MEM1 contract modules do not exist yet.; resolution: `accepted`; lesson: Define the rebuildable index contract before adding persistence or context projection helpers.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `project-index-contract-first`: occurrences=1; cause_status: `known`; root cause: The new project context index tests failed during collection because the MEM1 contract modules do not exist yet.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `project-index-contract-first`: line experience occurrence(s)=1

## Future guidance

- A memory index must remain a bounded projection of canonical facts, not a second authority store.
- Define the rebuildable index contract before adding persistence or context projection helpers.

## Event index

- #1: `2e6c2a1f-a926-40d8-9e9f-0199fb487740` | 2026-07-27T05:28:21.141Z | STATE_CHANGE/line_started | incident=`715f259e-aed8-4768-866c-4a1b678df8ff` | lesson_key=`frozen-context-before-start` | event_sha256=`f99dabaa76b98faf4111ebc8ba6a41c5238efe21deb2c0d144717d0a14bd86f2`
- #2: `456789ab-cdef-4012-3456-789abcdef012` | 2026-07-27T09:05:00.000Z | FAILURE/tdd_red_before_project_index | incident=`56789abc-def0-4123-4567-89abcdef0123` | lesson_key=`project-index-contract-first` | event_sha256=`5ada4e4e573813ca228ec028fde7c5f47964c288a1e00c0d041e14fd4e0e7352`
- #3: `6789abcd-ef01-4234-5678-9abcdef01234` | 2026-07-27T09:12:00.000Z | REVIEW/project_context_index_review_accepted | incident=`789abcde-f012-4345-6789-abcdef012345` | lesson_key=`memory-index-stays-rebuildable` | event_sha256=`3f42b0e1d11740a1a0229db8ec6378d4b812bbdbe35572e75070d25fe3a9c621`
- #4: `89abcdef-0123-4456-789a-bcdef0123456` | 2026-07-27T09:13:00.000Z | GATE/project_context_index_targeted_gate | incident=`9abcdef0-1234-4567-89ab-cdef01234567` | lesson_key=`mem1-gate-is-not-domain-memory` | event_sha256=`25305beabad2065233d4328dce34b76075e20c1e2e89454ef59bdf21871dddeb`
- #5: `abcdef01-2345-4678-9abc-def012345678` | 2026-07-27T09:14:00.000Z | STATE_CHANGE/project_context_index_completed | incident=`bcdef012-3456-4789-abcd-ef0123456789` | lesson_key=`close-mem1-before-cross-project-memory` | event_sha256=`edcb5a430f661f250098093c2e2855249cf90acb28a34fe9061a9f8be07817f4`
