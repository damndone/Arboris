# Retrospective — v1-8-4-agent-evidence-loop

## Goal

v1.8.4 Agent Evidence Loop  Implement the bounded, evidence-backed completion loop for the existing Workbench Agent. After a user-confirmed typed operation finishes, the Agent must be able to discover that operation and read only the bounded, server-selected result tables needed to answer the user's question, with artifact identifiers and provenance in every response.  The work must also repair the current Notebook inspection-round failure and the confirmed model.rerun execution path when their existing contracts are otherwise satisfied. Figure interpretation may use only a server-owned numeric chart packet or a declared visual packet; it must refuse when neither is available.  Non-goals: raw-data browsing, arbitrary file access, automatic execution, network/package installation, a weaker containment fallback, and any exercise- or dataset-specific behavior.  Acceptance: focused regression tests prove bounded result access, operation-result discoverability, evidence citations, refusal on unavailable evidence, a repaired planning round, and a confirmed rerun. A Workbench UI test must show Agent proposal -> confirmation -> completed operation -> evidence-backed user answer.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/12 (16.7%; 16.7 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=1435000 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- #2 2026-07-28T15:05:00.000Z `operation_evidence_gap`; cause_status: `known`; cause: The Agent session records terminal operation metadata, but has no bounded, chain-scoped tool that resolves completed operation artifacts into evidence-backed result facts.; resolution: `open`; lesson: Completion metadata is not analytical evidence; expose only server-resolved, bounded result facts with durable operation and artifact references.
- #8 2026-07-28T15:44:52.000Z `public_result_aggregate_budget`; cause_status: `known`; cause: Per-container artifact projection limits did not also bound the aggregate size of a nested public result packet.; resolution: `resolved`; lesson: Public artifact views need an aggregate item, key, and string budget in addition to depth and per-container limits.

## All waste

- #9 2026-07-28T15:50:56.000Z `quick_gate_notebook_test_fallback`; cause_status: `known`; cause: The quick gate does not classify tests/test_notebook_planning_agent.py as an Agent surface, so it conservatively selected the complete backend fallback.; resolution: `accepted`; lesson: Keep quick-gate path classification aligned with the supported Agent and Notebook test naming conventions; change the protected gate script only in a dedicated control-surface line.

## Root causes and solutions

- `agent-completed-operation-evidence-boundary`: occurrences=1; cause_status: `known`; root cause: The Agent session records terminal operation metadata, but has no bounded, chain-scoped tool that resolves completed operation artifacts into evidence-backed result facts.; solution: `open`
- `public-artifact-aggregate-budget`: occurrences=1; cause_status: `known`; root cause: Per-container artifact projection limits did not also bound the aggregate size of a nested public result packet.; solution: `resolved`
- `quick-gate-agent-notebook-classification`: occurrences=1; cause_status: `known`; root cause: The quick gate does not classify tests/test_notebook_planning_agent.py as an Agent surface, so it conservatively selected the complete backend fallback.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `agent-completed-operation-evidence-boundary`: line experience occurrence(s)=1
- `public-artifact-aggregate-budget`: line experience occurrence(s)=1
- `quick-gate-agent-notebook-classification`: line experience occurrence(s)=1

## Future guidance

- Completion evidence needs both a server-owned public projection and a response-level citation requirement; either one alone is insufficient.
- Completion metadata is not analytical evidence; expose only server-resolved, bounded result facts with durable operation and artifact references.
- Keep quick-gate path classification aligned with the supported Agent and Notebook test naming conventions; change the protected gate script only in a dedicated control-surface line.
- Public artifact views need an aggregate item, key, and string budget in addition to depth and per-container limits.

## Event index

- #1: `737cb6c5-bbde-4f65-bf11-4ee220f7cadb` | 2026-07-28T14:48:54.895Z | STATE_CHANGE/line_started | incident=`0f08a2bc-99ba-45b3-9004-4440c33e8d03` | lesson_key=`frozen-context-before-start` | event_sha256=`8b2f849880d7cc70feba0737e6642c26a125b09cbd2458089a70912ea7c88f35`
- #2: `8f905e31-4aeb-4fc3-8a97-0b4de3a4e491` | 2026-07-28T15:05:00.000Z | GAP/operation_evidence_gap | incident=`b71e5843-398c-4028-83d1-9c5e70a9ad4e` | lesson_key=`agent-completed-operation-evidence-boundary` | event_sha256=`601dfd4f8f54200944e0df8a338ff25cc419279928b0bce0dd90d593f2be0810`
- #3: `3f9f93a2-759d-49fb-9f1e-0661253fda59` | 2026-07-28T15:05:15.740Z | STATE_CHANGE/context_rescope_required | incident=`06e2491c-9626-43c4-8d89-4285e98c7057` | lesson_key=`context-pack-rescope` | event_sha256=`c754d5be9e2c83654c8fc53a4481adc588e1de1a7c3a70b9ccb360cb9d03bf84`
- #4: `fb6d2b50-06aa-4d99-9974-c48ac2661bed` | 2026-07-28T15:05:15.743Z | STATE_CHANGE/context_rescoped | incident=`532d2f55-455b-4738-a6cd-00fcca04707f` | lesson_key=`context-pack-rescope` | event_sha256=`9b78fe4371738a5b49263b3f1dac70600a480fffe3e02305d7c80cc2e7db848d`
- #5: `9d68fdfd-ae1c-4bf1-aeb4-f8912e9bd3aa` | 2026-07-28T15:19:01.000Z | GATE/chain_agent_evidence_loop | incident=`22b24a05-843d-4a0a-b1e8-b5d85abef371` | lesson_key=`chain-agent-artifact-evidence-loop` | event_sha256=`94ce05a0ee2becf0fd5acd2adbe05b9241a80ca72d94c51004b674f0d2ac6a63`
- #6: `9156f1da-dfeb-4af8-a4cc-a546fd6d0049` | 2026-07-28T15:33:03.312Z | STATE_CHANGE/context_rescope_required | incident=`e50580be-3e79-47e8-a06b-cad84c6071f0` | lesson_key=`context-pack-rescope` | event_sha256=`fd206f0f9365a92c970d35c635c5f0007b9b771219515b07f9233c65aeb3c3db`
- #7: `2497ac5f-56fa-47a9-9139-ebc795b2e34e` | 2026-07-28T15:33:03.317Z | STATE_CHANGE/context_rescoped | incident=`a65f911d-4eb5-4b71-ade9-387f4527ad54` | lesson_key=`context-pack-rescope` | event_sha256=`ee3c31c0814fda855ac74969b2630f36d000db7911db37632f1afd4d5c66012b`
- #8: `c4a915f2-35cc-4c0f-a5b2-4a1cde8fd4fd` | 2026-07-28T15:44:52.000Z | GAP/public_result_aggregate_budget | incident=`9148ea3d-c0c6-43a5-89ef-8d2a4a007df0` | lesson_key=`public-artifact-aggregate-budget` | event_sha256=`4cee3085a6bd571f59c5cdae5bb12ea29eb1a2c104d14a75fb87fac00d3ed986`
- #9: `b1a9d7f2-4f4e-44ab-bb0b-5242c2e4dd83` | 2026-07-28T15:50:56.000Z | WASTE/quick_gate_notebook_test_fallback | incident=`944b95ce-df43-49ae-88b2-79adc33a38d0` | lesson_key=`quick-gate-agent-notebook-classification` | event_sha256=`114871fd4c352071fc8cf719acb53e269854967755ec5f2a893f898371e33d30`
- #10: `dbb1458c-20c1-4f9c-9d23-8c6f7eac2eaf` | 2026-07-28T15:52:01.000Z | STATE_CHANGE/agent_evidence_loop_completed | incident=`272e3d93-2df1-4e12-85a1-1e9ec7e3afe5` | lesson_key=`completed-operation-needs-public-evidence-view` | event_sha256=`3d973b44ba7f4f429b413f9be0fb97a7a460594a3306d9c4e39f7cdcc250fef6`
- #11: `b45e4b30-6c46-418d-89e4-cf2f0a5b70f8` | 2026-07-28T15:52:50.000Z | REVIEW/operation_evidence_gap_resolved | incident=`b71e5843-398c-4028-83d1-9c5e70a9ad4e` | lesson_key=`agent-completed-operation-evidence-boundary` | event_sha256=`6070cfac92fa0896425f9a0586155a98b64a7e6dc2b097dad91c0c5589503cc4`
- #12: `a350dd44-3e06-453b-9a08-1349a8693a1f` | 2026-07-31T02:40:00.000Z | GATE/v1_8_4_release_gate | incident=`4ca4cfc6-6cb9-4c18-be2c-d4157b053fda` | lesson_key=`v1-8-4-release-gate` | event_sha256=`d599888eccb2aca3941676a65e020ea5525a6a42b373d4b6f26350c3655ac8fa`
