# Retrospective — v1-8-9-p1-capability-bootstrap-order

## Goal

# v1.8.9 P1 — capability registry bootstrap order  Make the live capability/workflow contract projection deterministic at import time. \`imputation.mice\` is registered by the runtime \`ImputationStage\`, so the first capability projection can omit it before the stage module is imported; later calls see it and disagree with the initial contract.  The fix must keep registry ownership modular and avoid importing optional execution packs merely to publish metadata. The same live declaration must drive the capability inventory, workflow-step vocabulary, and runtime adapter.  Acceptance: a clean-process import exposes \`imputation.mice\` as a composable reachable workflow capability, the denominator and reachability guard remain derived, the existing capability suites pass, and optional pack bootstrap behavior is unchanged. Browser, Provider, host resolver, and release gates remain explicit known gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T06:46:20.346Z `tdd_capability_bootstrap_red`; cause_status: `known`; cause: The clean-process regression exposed that the MICE declaration was absent until ImputationStage imported.; resolution: `resolved`; lesson: A clean-process regression must fail before a declaration bootstrap fix is admitted.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `tdd-red-before-implementation`: occurrences=1; cause_status: `known`; root cause: The clean-process regression exposed that the MICE declaration was absent until ImputationStage imported.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `tdd-red-before-implementation`: line experience occurrence(s)=1

## Future guidance

- A clean-process regression must fail before a declaration bootstrap fix is admitted.

## Event index

- #1: `087d385d-fc84-4449-aa9e-74b0fe53ac59` | 2026-08-21T06:31:53.109Z | STATE_CHANGE/line_started | incident=`85514b73-e7de-47c7-82c7-89f552e12c32` | lesson_key=`frozen-context-before-start` | event_sha256=`77bf1423bece07c7e0c7bc135e075a61a7b6c5e4536a07b8f48f45be3d6dc6e3`
- #2: `5a0dd4a7-1b0b-4e95-9d03-4eab1e9d94c1` | 2026-08-21T06:46:20.346Z | FAILURE/tdd_capability_bootstrap_red | incident=`a55a4c3f-3e28-4a5f-9ee7-fbfe08782708` | lesson_key=`tdd-red-before-implementation` | event_sha256=`8b0b8ecd4f0ff261a510d1ad199b350ec7b244c23b72617ac814c9b2654980fb`
- #3: `7bdc1fc2-6dc3-4c05-9d36-7df8b65561d8` | 2026-08-21T06:48:31.523Z | GATE/capability_bootstrap_scoped_gate | incident=`fbc9a8cf-66b6-4b20-b8d2-3ce43ce1f6e8` | lesson_key=`scoped-capability-bootstrap-gate` | event_sha256=`6549cdff4aab9a845e6ccaf5191f854b5c74679ef48f8bbd274f0410a0a96554`
- #4: `a7a5dcf8-9373-4bcb-9f12-780f5f6edbd4` | 2026-08-21T06:48:59.816Z | STATE_CHANGE/line_completed | incident=`3d27af4a-86f6-4ed7-83fd-0af1ae2d2c77` | lesson_key=`close-after-scoped-gate` | event_sha256=`a54d823f21208dec8b3f37d12d11d6562c71ab2d2459f78f497f8fcec3c66193`
