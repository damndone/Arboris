# Retrospective — v1-8-3-cf4-custom-preflight

## Goal

Add a generic CF4 custom-capability dispatch preflight contract. It must join one PreparedRunIntent, one CapabilityResolutionBinding, one AdapterContract, and one exact ImplementationRevision; validate operation and consumer admission with explicit consumer support; emit a content-addressed plan that still requires user confirmation and a later DispatchReservation; and expose no runner, process, network, filesystem, or automatic execution method. Reject stale or mismatched identity joins before any external side effect.

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

- #2 2026-07-27T09:22:00.000Z `tdd_red_before_custom_preflight`; cause_status: `known`; cause: The new preflight tests failed during collection because the generic custom dispatch module does not exist yet.; resolution: `accepted`; lesson: Make the generic preflight join explicit before adding any executor or Notebook wiring.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `custom-preflight-contract-first`: occurrences=1; cause_status: `known`; root cause: The new preflight tests failed during collection because the generic custom dispatch module does not exist yet.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `custom-preflight-contract-first`: line experience occurrence(s)=1

## Future guidance

- Expose a preflight plan before any execution consumer, and keep unsupported consumer semantics visible.
- Make the generic preflight join explicit before adding any executor or Notebook wiring.

## Event index

- #1: `a1652d7b-d638-4d58-aeb3-4a470e587616` | 2026-07-27T05:38:56.294Z | STATE_CHANGE/line_started | incident=`f81f3be1-a0a9-405c-8049-3dc77b81d0f2` | lesson_key=`frozen-context-before-start` | event_sha256=`9ca6eee67cdd92aa09627f32ca08b460f4c65704ab58a6886aef171710ffd54a`
- #2: `cdef0123-4567-489a-bcde-f0123456789a` | 2026-07-27T09:22:00.000Z | FAILURE/tdd_red_before_custom_preflight | incident=`def01234-5678-49ab-cdef-0123456789ab` | lesson_key=`custom-preflight-contract-first` | event_sha256=`050ccce33e9b9e7fbd351e164013f71eb9e05a653e1e43f12db638e8e5a99ce3`
- #3: `ef012345-6789-4abc-def0-123456789abd` | 2026-07-27T09:30:00.000Z | REVIEW/custom_preflight_review_accepted | incident=`f0123456-789a-4bcd-ef01-23456789abce` | lesson_key=`preflight-does-not-become-runner` | event_sha256=`862d5324c70bd70097a73db7d75184390043df64dcec8f6c74d739734b903eb5`
- #4: `01234567-89ab-4cde-f012-3456789abcef` | 2026-07-27T09:31:00.000Z | GATE/custom_preflight_targeted_gate | incident=`22345678-9abc-4def-0123-456789abcdef` | lesson_key=`bounded-custom-preflight-gate` | event_sha256=`2f3a9b3d4eb3c0eba50eeb20170c6cc76e47f33f48b0522c66bc92ee8604b3df`
- #5: `33456789-abcd-4ef0-1234-56789abcdef0` | 2026-07-27T09:32:00.000Z | STATE_CHANGE/custom_preflight_completed | incident=`33456789-abcd-4ef0-1234-56789abcdef1` | lesson_key=`close-preflight-before-execution` | event_sha256=`c87120d61cf5cfedda769f8677618194cb646c60139bfbe28759d2f22282b7c6`
