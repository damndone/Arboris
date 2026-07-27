# Retrospective — v1-8-3-cf4-durable-control-stream

## Goal

Make the generic execution-control fence durable without adding a dispatch consumer. Persist subject cursor publications and compare-and-append records in one append-only JSONL journal protected by an inter-process file lock. Reload and validate the journal before every state-changing operation, retain monotonic control sequence and idempotency semantics across process restarts, reject malformed or conflicting records, and preserve atomic multi-subject compare behavior. Do not implement PreparedRunIntent, Run creation, process spawn, supervisor, network, HTTP, UI, or any new automatic execution surface.

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

- #2 2026-07-27T06:00:00.000Z `tdd_red_before_durable_control_stream`; cause_status: `known`; cause: The durable-store tests failed before the JSONL-backed control stream and replay validation existed.; resolution: `resolved`; lesson: Test rehydration, replay, malformed journal rejection, side-effect-free reads, and process-level locking before adding durable control storage.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `durable-control-contract-first`: occurrences=1; cause_status: `known`; root cause: The durable-store tests failed before the JSONL-backed control stream and replay validation existed.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `durable-control-contract-first`: line experience occurrence(s)=1

## Future guidance

- Keep persistence as an append-only control stream and revalidate it before every consumer operation.
- Test rehydration, replay, malformed journal rejection, side-effect-free reads, and process-level locking before adding durable control storage.

## Event index

- #1: `9515f6aa-1890-4d5b-8e63-f3a81576e707` | 2026-07-27T04:54:47.231Z | STATE_CHANGE/line_started | incident=`9a7e3ad3-7ca2-47af-be21-4a975438f99a` | lesson_key=`frozen-context-before-start` | event_sha256=`25bd500dca4d09d28a325b72fa9e1961dcea8e80be4f3ee748772daeca4c0494`
- #2: `5f607182-934a-4012-3456-789abcdef012` | 2026-07-27T06:00:00.000Z | FAILURE/tdd_red_before_durable_control_stream | incident=`60718293-a4b5-4123-4567-89abcdef0123` | lesson_key=`durable-control-contract-first` | event_sha256=`86195a782308bb34fbdb957aebb0fdddcb0ecfc153cc7d54ed75e87dc6519333`
- #3: `60718293-a4b5-4123-4567-89abcdef0123` | 2026-07-27T06:12:00.000Z | REVIEW/durable_control_stream_review_accepted | incident=`718293a4-b5c6-4234-5678-9abcdef01234` | lesson_key=`durable-control-revalidate-before-consume` | event_sha256=`df6557781639215aab06a51f06cad651a91c941b9b21341b3444e97f56bdb393`
- #4: `718293a4-b5c6-4234-5678-9abcdef01234` | 2026-07-27T06:13:00.000Z | GATE/durable_control_stream_targeted_gate | incident=`8293a4b5-c6d7-4345-6789-abcdef012345` | lesson_key=`bounded-durable-control-gate` | event_sha256=`bf5e9693321976427939e4368d44f9fbb805135963f28a0cab1693f2724a55e8`
- #5: `8293a4b5-c6d7-4345-6789-abcdef012345` | 2026-07-27T06:14:00.000Z | STATE_CHANGE/durable_control_stream_completed | incident=`93a4b5c6-d7e8-4456-789a-bcdef0123456` | lesson_key=`close-durable-control-before-dispatch` | event_sha256=`b76b276d792696af01a8603c4e33ea91ce0a7c2ab684bf74f177fa0cf50c6f8d`
