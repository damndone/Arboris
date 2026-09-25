# Retrospective — v1-8-9-p1-classification-evidence-budget-closure

## Goal

# Workbench v1.8.9 P1 classification evidence budget closure  Close the current candidate regression where a normal, complete typed classification packet is rejected by the server-owned provider projection catalog because its deterministic structured-size estimate is larger than the declared budget. Preserve the hard fail-closed budget guard, raw-field rejection, row bound, catalog identity, and Agent/Notebook/Report shared projection. The fix must change the explicit bounded classification contract, not bypass admission or silently drop evidence.  Required outcomes:  - the complete normal classification packet is admitted by all three central   consumers with a declared bounded budget; - oversized, raw, foreign, and malformed packets remain rejected; - the server-side ceiling and catalog declaration agree, and the projection   exposes the observed token/row counts and identity; - focused tests prove the red failure before the fix and green behavior after; - browser, provider, host full-gate, and release acceptance remain separate   NOT VERIFIED gates.  Scope: \`backend/workbench/evidence/provider_projection_adapters.py\`, \`backend/workbench/providers/builtin/classification_ml.json\`, \`tests/test_v189_classification_central_consumer.py\`, and \`tests/test_v189_classification_projection_adapter.py\` only.

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
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

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `9ad2bb6a-4a2b-4467-8397-7fbbdc01a4b1` | 2026-08-22T17:36:11.342Z | STATE_CHANGE/line_started | incident=`3523d73c-7060-4262-8c21-ca03c1a599d7` | lesson_key=`frozen-context-before-start` | event_sha256=`585485ae27e2dd8813f78b78314b080e6adb234496a3e6c872ddbce1c90803c2`
