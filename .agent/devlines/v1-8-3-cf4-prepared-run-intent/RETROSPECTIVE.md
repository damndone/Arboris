# Retrospective — v1-8-3-cf4-prepared-run-intent

## Goal

Implement the immutable PreparedRunIntent@1.0 contract for the CF4 seam. The intent must content-address a validated Draft identity, exact capability binding and validity revisions, operation, run id, input fingerprint, runtime policy, namespace derivation and producer/ABI revisions. Enforce bounded path-safe caller identities, strict field sets, canonical timestamps only when needed, digest validation, immutable snapshots, and round-trip serialization. This line prepares no Run fact or directory and adds no dispatcher, process, network, HTTP, UI, or automatic execution behavior.

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

- #2 2026-07-27T07:00:00.000Z `tdd_red_before_prepared_run_intent`; cause_status: `known`; cause: The PreparedRunIntent contract tests failed before the immutable dispatch preparation module existed.; resolution: `resolved`; lesson: Test complete identity binding, strict round-trip fields, and no-side-effect preparation before adding the intent contract.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `prepared-intent-contract-first`: occurrences=1; cause_status: `known`; root cause: The PreparedRunIntent contract tests failed before the immutable dispatch preparation module existed.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `prepared-intent-contract-first`: line experience occurrence(s)=1

## Future guidance

- Keep PreparedRunIntent content-addressed and make consumers compare its pinned revisions before external work.
- Test complete identity binding, strict round-trip fields, and no-side-effect preparation before adding the intent contract.

## Event index

- #1: `94dfd4df-40cc-4f79-ad51-79d5168fb66a` | 2026-07-27T05:01:46.206Z | STATE_CHANGE/line_started | incident=`82ecc392-84ce-4db0-8ff8-1e2e07e5d635` | lesson_key=`frozen-context-before-start` | event_sha256=`e121b3731536013137694a15f26064db46694272664bcb49437c3eaca5f2c35e`
- #2: `a4b5c6d7-e8f9-4012-3456-789abcdef012` | 2026-07-27T07:00:00.000Z | FAILURE/tdd_red_before_prepared_run_intent | incident=`b5c6d7e8-f901-4123-4567-89abcdef0123` | lesson_key=`prepared-intent-contract-first` | event_sha256=`e174b914438d72b81e19b6ff36bb80398794271442ef0813ed7e8f5fe79bd276`
- #3: `b5c6d7e8-f901-4123-4567-89abcdef0123` | 2026-07-27T07:12:00.000Z | REVIEW/prepared_run_intent_review_accepted | incident=`c6d7e8f9-0123-4234-5678-9abcdef01234` | lesson_key=`prepared-intent-pinned-identity` | event_sha256=`b47bb21418c2be05f56db0459f7932adad3b7ad0e1322acd69a5294d01a92723`
- #4: `c6d7e8f9-0123-4234-5678-9abcdef01234` | 2026-07-27T07:13:00.000Z | GATE/prepared_run_intent_targeted_gate | incident=`d7e8f901-2345-4345-6789-abcdef012345` | lesson_key=`bounded-prepared-intent-gate` | event_sha256=`823540bf756dc806d4556e5aa37a57ae742c8601ebad55da70ff41e6821e76fa`
- #5: `d7e8f901-2345-4345-6789-abcdef012345` | 2026-07-27T07:14:00.000Z | STATE_CHANGE/prepared_run_intent_completed | incident=`e8f90123-4567-4456-789a-bcdef0123456` | lesson_key=`close-prepared-intent-before-reservation` | event_sha256=`1ec8c7d7647bb967a4614f6a4ede645433ed76d4583f48601347146e19906e0f`
