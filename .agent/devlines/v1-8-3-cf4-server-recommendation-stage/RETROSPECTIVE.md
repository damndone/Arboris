# Retrospective — v1-8-3-cf4-server-recommendation-stage

## Goal

Replace the production Agent-to-Notebook recommendation handoff with a server-owned feasibility stage. The Agent may supply candidate drafts and bounded evidence, but the Workbench service must revalidate every candidate, persist a typed FeasibilityDecision covering the complete cohort, and derive RecommendationDecisionV11 from that persisted source before constructing any capability-bound V1.2 option. Ignore Agent blocked_reason as authority. If multiple candidates are all structurally feasible and no independent comparison exists, preserve an insufficient_evidence outcome rather than choosing a winner. Wire the existing Notebook proposal route to this stage; manual legacy draft behavior remains unchanged and no execution surface is added.

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

- #2 2026-07-27T06:16:00.000Z `test_red`; cause_status: `known`; cause: The focused server recommendation tests exposed a missing service method before implementation.; resolution: `open`; lesson: Run the focused contract tests before claiming the server recommendation stage is wired.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `server-recommendation-red`: occurrences=1; cause_status: `known`; root cause: The focused server recommendation tests exposed a missing service method before implementation.; solution: `open`

## Added tests

- `57 passed: server recommendation route recommendation guard naming gate`
- `tests/test_capability_server_recommendation.py`

## New rules

- `server-recommendation-red`: line experience occurrence(s)=1

## Future guidance

- Keep Agent claims separate from Workbench facts and bind each trusted fact to a complete cohort and evidence pack.
- Run the focused contract tests before claiming the server recommendation stage is wired.

## Event index

- #1: `31f6be45-6746-4eaa-a8e5-34cd3f13596c` | 2026-07-27T06:09:49.330Z | STATE_CHANGE/line_started | incident=`97451fe3-ff3e-4dd4-a285-bb954cd90702` | lesson_key=`frozen-context-before-start` | event_sha256=`9b2497d129289a6acf273f5fc6f9713b7f493b61723a34a01e826531ae865db6`
- #2: `e8ea4e7e-41b1-4f92-9a83-4a26a4a1587a` | 2026-07-27T06:16:00.000Z | FAILURE/test_red | incident=`6fb970b3-0106-4c60-9f94-e3e76cc0fe18` | lesson_key=`server-recommendation-red` | event_sha256=`ef43fec7dbe742c63f2182f3e036bf5925d31187c33cdfacc013bfcde3b7a940`
- #3: `d19a74e6-0ab2-4eb4-a07f-d7dd0b4d2d8f` | 2026-07-27T06:21:00.000Z | REVIEW/server_stage_review | incident=`bc0bab7c-37f4-4b5f-bd8d-1e876bf4d13a` | lesson_key=`server-facts-cohort-evidence` | event_sha256=`b2a574eef36da5ad8478ff5a2f3584531e10d2f1b1f44c5387d77e4b6ca21838`
- #4: `a6cefcce-0dce-4e8b-a302-f6b9e24212f0` | 2026-07-27T06:22:00.000Z | GATE/target_tests | incident=`2de5cc6b-5c91-42d0-8523-4f08a73d1669` | lesson_key=`focused-gate-separate-from-host` | event_sha256=`32344d62b1d4b72c5624ac6a9c1a71ec764da8a6258e6186f4a1a98c1e433bcc`
- #5: `a8df4f3d-a86d-4fa2-a2d6-0f8bbf539734` | 2026-07-27T06:24:00.000Z | STATE_CHANGE/implementation_complete | incident=`1dd2f606-a887-4b06-9e10-8a744207d6b3` | lesson_key=`close-after-target-evidence` | event_sha256=`b508ff62deb6fd0419060d61504608c94a423a41775cc62613b93ac5ffe6c803`
