# Retrospective — v1-8-9-p0-legacy-route-integration-migration

## Goal

# Workbench v1.8.9 P0 legacy route integration migration  Migrate the remaining full-gate Agent analysis-loop route and workflow integration tests that still assume the pre-v1.8.9 local proposal-store and legacy response contracts. The tests must use the existing server-issued \`ProposalStoreCapabilityV1\`/compiler seam and assert the current typed result status. This line changes no production authority, compiler, model, evidence, or Report behavior.  Required outcomes:  - the two route tests create proposals through the server-owned route/compiler   capability and reach the intended tamper/confirmation assertions; - the two workflow integration tests use a server-issued proposal capability   and assert the current proposal-prepared response; - no raw store, caller-owned authority, or legacy fallback is reintroduced; - the focused route/workflow command, compileall, and \`git diff --check\` pass.

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

- #2 2026-08-21T05:43:41.291Z `legacy_contract_repro`; cause_status: `known`; cause: The focused Agent route and workflow tests still assumed pre-v1.8.9 local proposal mutation, legacy confirmation, and unbound workflow evidence host behavior.; resolution: `resolved`; lesson: Migrate compatibility tests to server-issued proposal and host evidence seams instead of restoring legacy authority fallbacks.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `typed-route-migration`: occurrences=1; cause_status: `known`; root cause: The focused Agent route and workflow tests still assumed pre-v1.8.9 local proposal mutation, legacy confirmation, and unbound workflow evidence host behavior.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `typed-route-migration`: line experience occurrence(s)=1

## Future guidance

- Migrate compatibility tests to server-issued proposal and host evidence seams instead of restoring legacy authority fallbacks.

## Event index

- #1: `dac1fee7-9de4-4181-bb29-3e500d21b31c` | 2026-08-21T05:32:48.092Z | STATE_CHANGE/line_started | incident=`2e96fe75-9e1c-4967-929a-51698b2f7851` | lesson_key=`frozen-context-before-start` | event_sha256=`20380d71237e2ffeb5888660cc22b8d0f18c6ded0b6c4e9c1391dab00b4ebc88`
- #2: `c8bf97b2-3ad6-4f8f-9da0-4b0c9f0e1c72` | 2026-08-21T05:43:41.291Z | FAILURE/legacy_contract_repro | incident=`3a3d34d9-4de7-44b9-a49d-4e5d3640d7c8` | lesson_key=`typed-route-migration` | event_sha256=`c485f18de9825e81175f8b13f3666e212e7cc5e8246fd325d4015b99800176a1`
- #3: `1c0d6e77-3e3b-4a5a-8f4f-ef246a456c55` | 2026-08-21T05:43:59.905Z | GATE/legacy_route_workflow_green | incident=`76bd9a88-9d48-48fa-b5bf-8f7fd1d60f07` | lesson_key=`scoped-line-gate` | event_sha256=`9e5589aec9d08fe0b8f3c198dbfb90c60e0b20d350834e64b351adc36721209e`
- #4: `9a8dbd39-e04d-4eef-95fb-8644c79c4bf0` | 2026-08-21T05:44:19.105Z | STATE_CHANGE/line_completed | incident=`ad9fb62a-f030-4d6a-a9f4-c7cf1bddcb0c` | lesson_key=`scoped-line-closeout` | event_sha256=`16588dc64ab003abac2dd60365ada6d306de9e6a9a7a33a95e73d18ae4ed14f0`
