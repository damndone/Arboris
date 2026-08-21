# Retrospective — v1-8-9-p1-survey-bootstrap-test-contract

## Goal

# Workbench v1.8.9 P1 Survey bootstrap test contract  Update the stale Survey capability bootstrap assertion after the P0 statistical stage import-cycle repair. The clean-process capability probe must reflect the current executable registry while retaining a typed blocked result for genuine bootstrap failures.  Required outcomes:  - the test asserts the current available status and admitted survey families; - the test does not restore or duplicate the old import-cycle workaround; - no Survey estimator, authority, consumer, or provider behavior changes.

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

- #2 2026-08-21T06:17:21.922Z `stale_bootstrap_assertion`; cause_status: `known`; cause: The focused clean-process Survey capability probe returned the repaired available registry, while the test still expected the obsolete import-cycle blocked state.; resolution: `resolved`; lesson: When a central bootstrap defect is repaired, migrate the consumer assertion to the executable capability contract while retaining fail-closed behavior for real failures.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `bootstrap-contract-after-cycle-fix`: occurrences=1; cause_status: `known`; root cause: The focused clean-process Survey capability probe returned the repaired available registry, while the test still expected the obsolete import-cycle blocked state.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `bootstrap-contract-after-cycle-fix`: line experience occurrence(s)=1

## Future guidance

- When a central bootstrap defect is repaired, migrate the consumer assertion to the executable capability contract while retaining fail-closed behavior for real failures.

## Event index

- #1: `1d26dcc8-b5a9-47a4-8128-2203e41b6023` | 2026-08-21T06:09:01.704Z | STATE_CHANGE/line_started | incident=`9b9dab47-4ba3-451a-bf3f-74aa7942bd5e` | lesson_key=`frozen-context-before-start` | event_sha256=`817da96632dfdf39a579220f9eb06b3a6831073e6d341c6fae4437a865071115`
- #2: `2a3b4c5d-6e7f-4890-ab12-cd34ef567890` | 2026-08-21T06:17:21.922Z | FAILURE/stale_bootstrap_assertion | incident=`3b4c5d6e-7f80-4901-bc23-de45f6789012` | lesson_key=`bootstrap-contract-after-cycle-fix` | event_sha256=`5ee11716526459323a217463362055cda7418745df7328f2d2884e4aa64b4a30`
- #3: `4c5d6e7f-8091-4a23-bc45-de6789012345` | 2026-08-21T06:18:00.337Z | GATE/survey_bootstrap_focused_gate | incident=`5d6e7f80-9123-4a34-bc56-ef7890123456` | lesson_key=`bounded-green-not-product-release` | event_sha256=`3ab60972b62a6fb5be496a9a63744a9068e6466f1e28ce831ffbf069c655c77f`
- #4: `6e7f8091-2345-4a56-bc67-f89012345678` | 2026-08-21T06:18:14.407Z | STATE_CHANGE/line_completed | incident=`7f809123-4567-4a67-bc78-f90123456789` | lesson_key=`scoped-line-explicit-closeout` | event_sha256=`412d4e6ce9e6f05fb20613f184491f330aa420a218a113a0f88964ac969ef27e`
