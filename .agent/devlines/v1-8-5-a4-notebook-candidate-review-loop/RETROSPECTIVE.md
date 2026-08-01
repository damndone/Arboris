# Retrospective — v1-8-5-a4-notebook-candidate-review-loop

## Goal

# v1.8.5 A4 — Notebook Candidate Review Loop  This is a narrow integration slice of \`docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md\`. It closes the existing A2/A3 product loop without changing the memory contract or execution authority.  ## Objective  Make the existing server-owned domain-memory candidate queue reachable from the Notebook surface: load pending candidates for the current project, render the bounded review controls already defined by \`NotebookSurface\`, and send explicit approve/reject decisions back to the current project scope. Candidate review must remain memory publication only; it must never execute an analysis or alter Notebook proposal authority.  ## Scope  - Update \`frontend/src/notebook/NotebookRouteView.tsx\` to load the current   project's candidate queue with lifecycle-safe refresh and stale-project   guards. - Pass the queue and an explicit review callback to \`NotebookSurface\`. - Use the existing \`domainMemoryApi\` and \`DomainMemoryReviewQueue\`; do not add   another candidate endpoint or a second Settings implementation. - Add focused frontend tests for queue loading, explicit review dispatch,   project switching, and fail-closed queue errors.  ## Explicit non-scope  - No new memory kinds, apply modes, verifiers, retrieval rules, or target   contracts. - No automatic approval, automatic execution, proposal mutation, or analysis   run. - No backend route change, no new persistent store, and no browser navigation   workaround.  ## Acceptance  1. A current project with a pending queue renders the existing review controls;    approval and rejection call the server-owned API with the candidate revision. 2. A queue failure is visible and fail-closed; it does not hide Settings or    create a local fallback candidate. 3. Switching projects cannot apply a former project's queue, busy state, or    review result to the new project. 4. The focused Notebook/Memory frontend tests and TypeScript check pass.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=137000 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-01T22:06:12.000Z `tdd_red_notebook_candidate_review_unwired`; cause_status: `known`; cause: NotebookSurface already exposed the candidate review props, but NotebookRouteView neither loaded the server-owned candidate queue nor passed review handlers to the surface.; resolution: `open`; lesson: A UI component and endpoint are not a capability until the route owns current-project loading, stale-request guards, and explicit action wiring.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `notebook-candidate-review-needs-route-loop`: occurrences=1; cause_status: `known`; root cause: NotebookSurface already exposed the candidate review props, but NotebookRouteView neither loaded the server-owned candidate queue nor passed review handlers to the surface.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `notebook-candidate-review-needs-route-loop`: line experience occurrence(s)=1

## Future guidance

- A UI component and endpoint are not a capability until the route owns current-project loading, stale-request guards, and explicit action wiring.
- A route-level review must keep project identity, queue freshness, and mutation revision explicit; a rendered queue alone is not enough.

## Event index

- #1: `0aa2ff99-5f06-4898-80f3-f4795104dc63` | 2026-08-01T22:04:14.298Z | STATE_CHANGE/line_started | incident=`84e8d801-915b-48fb-901e-c7611bf55fb3` | lesson_key=`frozen-context-before-start` | event_sha256=`500a502301c5baced6a77d307cb5ae261f8aef1fe998f5546c0c47931bb89d11`
- #2: `d1e44cb4-a2f1-44d4-a93f-9892d0dfc9db` | 2026-08-01T22:06:12.000Z | FAILURE/tdd_red_notebook_candidate_review_unwired | incident=`d1e44cb4-a2f1-44d4-a93f-9892d0dfc9db` | lesson_key=`notebook-candidate-review-needs-route-loop` | event_sha256=`36486aeac3d8b364c6b039979f897a0d5c805084d4bc5b216a565d8ff23f420e`
- #3: `3e1c5e67-c8f1-4c3f-9a7c-5fb507b2e2e7` | 2026-08-01T22:08:29.000Z | REVIEW/a4_notebook_candidate_review_loop_verified | incident=`d1e44cb4-a2f1-44d4-a93f-9892d0dfc9db` | lesson_key=`notebook-candidate-review-needs-route-loop` | event_sha256=`c4af6799e30b168cb39ecb453d1cefc88c6a747b5e535085f09d471ec4686918`
- #4: `9d4a0aef-1c2c-4881-9576-143fb1261d22` | 2026-08-01T22:08:29.000Z | GATE/a4_notebook_candidate_review_loop_gate_passed | incident=`9d4a0aef-1c2c-4881-9576-143fb1261d22` | lesson_key=`a4-notebook-candidate-review-loop-gate` | event_sha256=`b5e35ea20fdf96fbda22acb203406a508c14812cd13c8433500dbee0a8ea0172`
- #5: `6e968bf8-ead4-4e6a-8db6-2d87b6ce47d7` | 2026-08-01T22:08:29.000Z | STATE_CHANGE/a4_notebook_candidate_review_loop_completed | incident=`6e968bf8-ead4-4e6a-8db6-2d87b6ce47d7` | lesson_key=`close-a4-notebook-candidate-review-loop` | event_sha256=`0b9f416e8b464c04a3437dd2bdb8edbcee5ffa442ce18742debb2d56567852a6`
