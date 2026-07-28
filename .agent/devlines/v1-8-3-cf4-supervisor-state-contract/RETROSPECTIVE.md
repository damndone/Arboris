# Retrospective — v1-8-3-cf4-supervisor-state-contract

## Goal

Implement the CF4 durable-supervisor state contract for one reserved capability attempt. Add only a strict, content-addressed execution-attempt record and an independent AttemptQuiescenceProof/reconciliation contract. The slice must bind reservation identity, executor idempotency key, lease epoch, and process/job handle identity; reject stale epochs and replay mismatches; make unknown dispatch terminal until an independently issued quiescence proof is present; and remain execution-free (no spawn, subprocess, network, host filesystem, VM, or automatic execution). Add focused tests for exact schemas, round trips, state transitions, fencing, replay, proof outcomes, and the absence of execution APIs. Do not modify authorization, dispatch, Notebook, Agent, or containment seams in this line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-07-27T09:40:00.000Z `tdd_red_before_supervisor_contract`; cause_status: `known`; cause: The new supervisor contract tests failed during collection because the execution-attempt contract module does not exist yet.; resolution: `accepted`; lesson: Define the immutable attempt and quiescence proof schema before adding any supervisor integration.

## All errors

- #3 2026-07-27T09:42:00.000Z `supervisor_test_fixture_skipped_state`; cause_status: `known`; cause: One focused test fixture attempted to jump from reserved to spawn_acknowledged and failed against the intentionally strict transition graph.; resolution: `resolved`; lesson: Test state machines through every declared edge instead of constructing a later state directly.
- #4 2026-07-27T09:44:00.000Z `frozen_gate_references_missing_test`; cause_status: `known`; cause: The frozen target command names tests/test_capability_authorization_contract.py, but the repository test is tests/test_capability_execution_authorization.py.; resolution: `accepted`; lesson: Verify frozen test paths exist before claiming a formal gate and record any equivalent coverage explicitly.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `supervisor-contract-first`: occurrences=1; cause_status: `known`; root cause: The new supervisor contract tests failed during collection because the execution-attempt contract module does not exist yet.; solution: `accepted`
- `supervisor-test-state-edges`: occurrences=1; cause_status: `known`; root cause: One focused test fixture attempted to jump from reserved to spawn_acknowledged and failed against the intentionally strict transition graph.; solution: `resolved`
- `verify-frozen-test-paths`: occurrences=1; cause_status: `known`; root cause: The frozen target command names tests/test_capability_authorization_contract.py, but the repository test is tests/test_capability_execution_authorization.py.; solution: `accepted`

## Added tests

- `tests/test_capability_supervisor_contract.py`
- `tests/test_capability_supervisor_contract.py;tests/test_capability_dispatch_contract.py;tests/test_capability_execution_authorization.py;tests/test_no_exercise_specific_naming.py`

## New rules

- `supervisor-contract-first`: line experience occurrence(s)=1
- `supervisor-test-state-edges`: line experience occurrence(s)=1
- `verify-frozen-test-paths`: line experience occurrence(s)=1

## Future guidance

- Define the immutable attempt and quiescence proof schema before adding any supervisor integration.
- Keep supervisor identity and quiescence evidence separate from process-start code until a trusted host adapter is available.
- Test state machines through every declared edge instead of constructing a later state directly.
- Verify frozen test paths exist before claiming a formal gate and record any equivalent coverage explicitly.

## Event index

- #1: `fa5aaee0-ef6f-4234-a0d4-a6443e36dc33` | 2026-07-27T05:45:51.023Z | STATE_CHANGE/line_started | incident=`07ca738b-89b8-434f-9e8d-fec7b88e3a35` | lesson_key=`frozen-context-before-start` | event_sha256=`40e29b78fc0c011b681ff007d7ff65652b92317ae1689ff00d94860e703e4cba`
- #2: `4456789a-bcde-4f01-2345-6789abcdef01` | 2026-07-27T09:40:00.000Z | FAILURE/tdd_red_before_supervisor_contract | incident=`4456789a-bcde-4f01-2345-6789abcdef02` | lesson_key=`supervisor-contract-first` | event_sha256=`45b23c5c750653fc1415e2778b99f1de3a0a42aa52aa3f0ca437c45ecff3e180`
- #3: `556789ab-cdef-4012-3456-789abcdef012` | 2026-07-27T09:42:00.000Z | ERROR/supervisor_test_fixture_skipped_state | incident=`556789ab-cdef-4012-3456-789abcdef013` | lesson_key=`supervisor-test-state-edges` | event_sha256=`3edcd3533624f93adcd2b1c2194a9c1d2a6d187fd796297428bf3477c6685d83`
- #4: `66789abc-def0-4123-4567-89abcdef0123` | 2026-07-27T09:44:00.000Z | ERROR/frozen_gate_references_missing_test | incident=`66789abc-def0-4123-4567-89abcdef0124` | lesson_key=`verify-frozen-test-paths` | event_sha256=`f1b41890063c14a6596cff7d61491c3df93981550ecebd1536936575c5353943`
- #5: `7789abcd-ef01-4234-5678-9abcdef01234` | 2026-07-27T09:47:00.000Z | REVIEW/supervisor_contract_review_accepted | incident=`7789abcd-ef01-4234-5678-9abcdef01235` | lesson_key=`supervisor-contract-stays-execution-free` | event_sha256=`fc47f93009a8ffe6fc34ca2d3607b89e3d22cb206dde32f92fd44dcb58af573f`
- #6: `889abcde-f012-4345-6789-abcdef012345` | 2026-07-27T09:49:00.000Z | GATE/supervisor_state_contract_targeted_gate | incident=`889abcde-f012-4345-6789-abcdef012346` | lesson_key=`supervisor-targeted-gate` | event_sha256=`ad76ebf1f5dc30c8f961fdbf1e113552b7fc78481acc6d9236391e7513ff6be4`
- #7: `99abcdef-0123-4456-789a-bcdef0123456` | 2026-07-27T09:50:00.000Z | STATE_CHANGE/supervisor_state_contract_completed | incident=`99abcdef-0123-4456-789a-bcdef0123457` | lesson_key=`close-supervisor-contract-before-host-adapter` | event_sha256=`510b7bbb2f503661db9274dd39aad0f3232029cc7e09c054244100df36084d00`
