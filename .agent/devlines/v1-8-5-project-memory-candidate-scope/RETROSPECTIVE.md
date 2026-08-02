# Retrospective — v1-8-5-project-memory-candidate-scope

## Goal

# v1.8.5 project-memory candidate scope objective  ## Objective  Close the local domain-memory mutation boundary so candidate creation and the legacy approval endpoint cannot silently operate on the global memory service or on an unselected project. In the local runtime, candidate creation must be authorized by the current project's persisted settings, and candidate approval must use the current project's candidate store. The existing review endpoint and the setting confirmation lifecycle remain unchanged.  ## Contract  - Local candidate creation requires \`project_root\`, an enabled project library,   and \`candidate_generation_enabled=true\`. - Local candidate approval requires \`project_root\` and an enabled project   library, but does not require candidate generation to remain enabled; users   must still be able to review candidates that were created before generation   was disabled. - The server, not request-body preferences or overrides, decides these local   permissions. Request-body preference fields remain accepted only for the   non-local compatibility seam. - Candidate scope must match the server-derived project scope. A request must   never choose a different scope through its JSON payload. - No analysis execution, agent execution, automatic approval, or frontend   behavior is added.  ## Verification  - Red tests demonstrate that local create/approve currently bypass the project   identity and project settings. - Green tests cover project-scoped create, create denial when generation is   disabled, approval using the selected project's store, and missing-project   fail-closed behavior. - Run only the focused memory-route tests, \`git diff --check\`, and the frontend   typecheck if source boundaries remain unchanged. Do not claim browser or full   gate evidence from this slice.  ## Boundaries  Allowed implementation paths are recorded by the formal development-line manifest. The parent v1.8.5 design, frontend, storage journal format, and execution/agent routes are protected.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=300000 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-01T22:38:00.000Z `tdd_red_project_memory_candidate_scope`; cause_status: `known`; cause: The legacy candidate create and approve routes still use the global service and do not require the server-owned project identity; focused tests failed with 400/503 instead of project-bound outcomes.; resolution: `open`; lesson: Every local memory mutation route must resolve the server-owned project scope before selecting a store or interpreting request preferences.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `legacy-memory-mutations-need-project-bound-service`: occurrences=1; cause_status: `known`; root cause: The legacy candidate create and approve routes still use the global service and do not require the server-owned project identity; focused tests failed with 400/503 instead of project-bound outcomes.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `legacy-memory-mutations-need-project-bound-service`: line experience occurrence(s)=1

## Future guidance

- Every local memory mutation route must resolve the server-owned project scope before selecting a store or interpreting request preferences.

## Event index

- #1: `4ac2c7de-fd31-4469-ab46-21b57d51814a` | 2026-08-01T22:36:04.788Z | STATE_CHANGE/line_started | incident=`ec91aeb1-2a5e-486b-aca0-9810fbe67fe1` | lesson_key=`frozen-context-before-start` | event_sha256=`fd9472e1187ca1124011444fd4fdf1586a99dc3e7b3e55f16e5471be15ea3f29`
- #2: `b7a32d4e-4fd7-44fb-b27b-46e3c4f76a21` | 2026-08-01T22:38:00.000Z | FAILURE/tdd_red_project_memory_candidate_scope | incident=`9d1c4b73-0a2c-4f44-8ea5-7af2e7b1c9d4` | lesson_key=`legacy-memory-mutations-need-project-bound-service` | event_sha256=`426d11a1efff06f79643699b8f1d49be93fbee30c7761240834cb83f832065b9`
- #3: `c3f5222b-4a70-43f0-a5a6-4a6b86c31c1d` | 2026-08-01T22:43:00.000Z | REVIEW/project_memory_candidate_scope_resolved | incident=`9d1c4b73-0a2c-4f44-8ea5-7af2e7b1c9d4` | lesson_key=`legacy-memory-mutations-need-project-bound-service` | event_sha256=`939bba34f49a8e74e37e802acc3d11db24871ff07b4888aca1e78e37299ddb0e`
- #4: `e2e9d8af-e6b7-42e6-a5a0-c2d59fa9ed32` | 2026-08-01T22:44:00.000Z | GATE/project_memory_candidate_scope_gate_passed | incident=`9d1c4b73-0a2c-4f44-8ea5-7af2e7b1c9d4` | lesson_key=`legacy-memory-mutations-need-project-bound-service` | event_sha256=`0c1556e7de09e953e0ecea9716ff751e7930d8667b1bf04bfc9df57857503457`
- #5: `f8afcbfb-a1d9-42b4-9a52-7b3e3576d4b7` | 2026-08-01T22:45:00.000Z | STATE_CHANGE/project_memory_candidate_scope_completed | incident=`9d1c4b73-0a2c-4f44-8ea5-7af2e7b1c9d4` | lesson_key=`legacy-memory-mutations-need-project-bound-service` | event_sha256=`e1e27f7546967be0f0a48fa255f2b35a8c8fe90a124a5066e67aad99b5e2a150`
