# Retrospective — wo-d-evaluation

## Goal

Keep candidate evaluation fail-closed until the frozen containment executor has a supported-host startup canary.

## Final status

CLOSED

## Metrics

- Failure frequency: 1/3 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- #2 2026-07-19T19:15:00.000Z `supported_host_canary_missing`; cause_status: `known`; cause: The frozen containment executor has approved design evidence but no supported-host startup canary.; resolution: `open`; lesson: Keep C1 fail-closed until a separately verified C2 containment host is available.

## All waste

- None recorded.

## Root causes and solutions

- `containment-c1-c2-boundary`: occurrences=1; cause_status: `known`; root cause: The frozen containment executor has approved design evidence but no supported-host startup canary.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `containment-c1-c2-boundary`: line experience occurrence(s)=1

## Future guidance

- Keep C1 fail-closed until a separately verified C2 containment host is available.

## Event index

- #1: `604abc29-0c1f-4eb2-9177-7f8c2f1cfc4e` | 2026-07-19T23:45:18.975Z | STATE_CHANGE/line_started | incident=`e5e96362-d9f1-4d75-ab14-81e32224f7b2` | lesson_key=`frozen-context-before-start` | event_sha256=`bc7cda7b0e13ac6f726c83bedc97d2f70e289472d81d5e860f984bee07516320`
- #2: `10000000-0000-4000-8000-000000000004` | 2026-07-19T19:15:00.000Z | GAP/supported_host_canary_missing | incident=`20000000-0000-4000-8000-000000000004` | lesson_key=`containment-c1-c2-boundary` | event_sha256=`8bcd91749c2a4e4a0dbefaf983bb40c110fed661f01ff2442c5049e4e6251d37`
- #3: `65bd3d3e-0f0a-4e7a-b5b1-3cbb32aa0d80` | 2026-07-20T17:44:54.000Z | STATE_CHANGE/wo_d_local_scope_accepted | incident=`41ec031b-62c6-465c-8401-f8cf7ea38810` | lesson_key=`assembled-line-state-closeout` | event_sha256=`0ff21cf42cd20799dc7441d512ba13bbe31e663145067dd89d2cc329f5052644`
