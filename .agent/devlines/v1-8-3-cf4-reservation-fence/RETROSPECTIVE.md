# Retrospective — v1-8-3-cf4-reservation-fence

## Goal

Add a typed dispatch reservation fence around the existing ExecutionControlStore. The fence must require one claimed authorization subject and the exact binding, host containment, bundle, evidence, and admission validity cursor revisions pinned by PreparedRunIntent before appending one dispatch_reservation record. It must derive the existing DispatchReservation from that single control-stream record, preserve idempotent retries after later revocation, and fail closed when any required subject is missing, stale, expired, or has the wrong status. Keep the slice pure control-plane: no authorization-journal transition, Draft, Run, process, supervisor, network, HTTP, UI, or automatic execution.

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

- #2 2026-07-27T08:36:00.000Z `tdd_red_before_reservation_fence`; cause_status: `known`; cause: The new control-fence tests failed because the typed reserve entry point has not been implemented yet.; resolution: `accepted`; lesson: Test all required control subjects and revocation ordering before exposing a reservation helper.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `reservation-fence-contract-first`: occurrences=1; cause_status: `known`; root cause: The new control-fence tests failed because the typed reserve entry point has not been implemented yet.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `reservation-fence-contract-first`: line experience occurrence(s)=1

## Future guidance

- Put revocation and reservation on the same serialized control stream before adding an executor.
- Test all required control subjects and revocation ordering before exposing a reservation helper.

## Event index

- #1: `e0d26a66-9438-426d-9f8f-3bbe8036a8f7` | 2026-07-27T05:23:35.216Z | STATE_CHANGE/line_started | incident=`ad7ccbf7-2490-4db6-b599-3c1c204b5fea` | lesson_key=`frozen-context-before-start` | event_sha256=`7d6ff46a419fb8f412861b62a84a9d27a03c36d13e4ff01d4eb6d45c05b1b265`
- #2: `cdef0123-4567-4289-abcd-ef0123456789` | 2026-07-27T08:36:00.000Z | FAILURE/tdd_red_before_reservation_fence | incident=`def01234-5678-439a-bcde-f0123456789a` | lesson_key=`reservation-fence-contract-first` | event_sha256=`51134958b9ca44907b36df474b50940eb43c782f9d4050a48a30c83e1711fc1b`
- #3: `ef012345-6789-4abc-def0-123456789abc` | 2026-07-27T08:43:00.000Z | REVIEW/reservation_fence_review_accepted | incident=`f0123456-789a-4bcd-ef01-23456789abcd` | lesson_key=`reservation-and-revocation-share-fence` | event_sha256=`00b53ce4e5af9ae4de52e37123cd1acf5f79405d161510fcf8ccc908770174ab`
- #4: `01234567-89ab-4cde-f012-3456789abcde` | 2026-07-27T08:44:00.000Z | GATE/reservation_fence_targeted_gate | incident=`12345678-9abc-4def-0123-456789abcdef` | lesson_key=`control-fence-is-not-executor-evidence` | event_sha256=`c3977ef95e6b974b259b6ec50ccee7e12c25d327be67f4fbda86b923a7cb371e`
- #5: `23456789-abcd-4ef0-1234-56789abcdef0` | 2026-07-27T08:45:00.000Z | STATE_CHANGE/reservation_fence_completed | incident=`3456789a-bcde-4f01-2345-6789abcdef01` | lesson_key=`close-reservation-fence-before-executor` | event_sha256=`0480bbdd43428e3f91dc0e311a03f71555ea46c9a97d73bc865cf51b861ab025`
