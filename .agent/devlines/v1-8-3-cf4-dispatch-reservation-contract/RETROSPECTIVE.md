# Retrospective — v1-8-3-cf4-dispatch-reservation-contract

## Goal

Add the immutable DispatchReservation@1.0 record contract and derive it only from a PreparedRunIntent plus a durable control record snapshot. Bind authorization identity, intent digest, caller-supplied attempt/run IDs, lease epoch, executor idempotency key, control sequence, and exact subject cursors. Reject mismatched or mutable input and support strict round-trip serialization. Do not change authorization transitions, create Run directories, spawn a process, add a supervisor, network, HTTP, UI, or automatic execution.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
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

- #2 2026-07-27T08:00:00.000Z `tdd_red_before_dispatch_reservation`; cause_status: `known`; cause: The reservation contract tests failed before DispatchReservation existed as a derived immutable record.; resolution: `resolved`; lesson: Test reservation derivation and snapshot binding before adding a downstream consumer.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `reservation-contract-first`: occurrences=1; cause_status: `known`; root cause: The reservation contract tests failed before DispatchReservation existed as a derived immutable record.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `reservation-contract-first`: line experience occurrence(s)=1

## Future guidance

- Make a reservation a typed projection of one exact control record, never a fresh reconstruction from current state.
- Test reservation derivation and snapshot binding before adding a downstream consumer.

## Event index

- #1: `d3e443ba-b5dc-4ae9-9b31-9170b466341a` | 2026-07-27T05:07:10.936Z | STATE_CHANGE/line_started | incident=`b75cdf66-c484-4d29-ad9a-127b913300c2` | lesson_key=`frozen-context-before-start` | event_sha256=`bc48de931e33da8ef77ae952e59dcfe6075c1dfc9cec72169ad0b20fa7e54953`
- #2: `f9012345-6789-4567-89ab-cdef01234567` | 2026-07-27T08:00:00.000Z | FAILURE/tdd_red_before_dispatch_reservation | incident=`01234567-89ab-4678-9012-3456789abcde` | lesson_key=`reservation-contract-first` | event_sha256=`d57b958b58b6a8a606a214240279dd81043451fc9559a57d1f86600641a0816e`
- #3: `01234567-89ab-4678-9012-3456789abcde` | 2026-07-27T08:12:00.000Z | REVIEW/dispatch_reservation_contract_review_accepted | incident=`12345678-9abc-4789-0123-456789abcdef` | lesson_key=`reservation-derives-from-control-record` | event_sha256=`887fb184af8a02f75588fc1a3cd4557848914de85795a5611bcfa066ddc67b64`
- #4: `12345678-9abc-4789-0123-456789abcdef` | 2026-07-27T08:13:00.000Z | GATE/dispatch_reservation_contract_targeted_gate | incident=`23456789-abcd-4890-1234-56789abcdef0` | lesson_key=`bounded-reservation-contract-gate` | event_sha256=`a5b8f8cfe5364138d3014f9b04993f2753dfb6f3ace27d0a917dd17843ce45e4`
- #5: `23456789-abcd-4890-1234-56789abcdef0` | 2026-07-27T08:14:00.000Z | STATE_CHANGE/dispatch_reservation_contract_completed | incident=`3456789a-bcde-4901-2345-6789abcdef01` | lesson_key=`close-reservation-before-receipt-transition` | event_sha256=`ef45c11c8289077fa52e1902805d92da23fbb299f6a9adcef24cd859744dd76d`
