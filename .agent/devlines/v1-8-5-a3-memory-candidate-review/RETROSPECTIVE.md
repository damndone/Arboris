# Retrospective — v1-8-5-a3-memory-candidate-review

## Goal

# v1.8.5 A3 — Memory Candidate Review Objective  This is the narrowly scoped user-management completion slice for the approved v1.8.5 typed-memory design. The parent design remains the only authority for version scope.  ## Objective  Make an already server-created pending project-memory candidate visible and reviewable from **Settings → Memory**, with an explicit approve/reject choice. The user must never need a file path, an HTTP client, or a developer tool to review it. Approval remains a memory-governance action only: it never starts analysis, executes code, changes a current Draft, or bypasses later Proposal/Risk confirmation.  ## Scope  - Publish a read-only, current-project endpoint for pending candidates. The   server derives the project scope from \`project_root\`; clients never submit   scope or owner identity. - Extend the existing Memory settings API/types and panel to load the queue,   show each lesson, kind and bounded source references, and issue an explicit   approve or reject request. - Approval sends the candidate's current revision, a local reviewer identity,   the current timestamp, and a bounded review date. A stale revision or   unresolved conflict stays fail-closed and is shown as an error; it must not   silently retry or select a conflict winner. - Refresh settings, libraries and queue after a successful decision. Rejected   or approved candidates disappear from the pending queue; an approved entry   becomes visible only in its project library. - Add red-first route and frontend tests for server-derived scope, no-execute   surface, stale failure visibility, and the visible user decision flow.  ## Explicit non-scope  - No new candidate-generation trigger, LLM curator, semantic retrieval,   cross-project promotion, manual free-form memory authoring, or new automatic   execution surface. - No changes to default-target registry, memory retrieval/admission, Recipe   validation, model fitting, execution authorization, or candidate contract   schemas. - No deletion/enablement semantic change: their existing server-bound   two-step confirmations remain unchanged. Candidate review is a separate,   explicit governance decision.  ## Acceptance  Tests fail before the list/read wiring exists and pass after it. One visible Workbench acceptance must show an existing pending candidate in Settings, allow an explicit decision, and show no analysis execution. The acceptance may use a bounded local fixture to populate the existing candidate journal, but must label that setup as fixture preparation rather than an end-user candidate-generation flow.  ## Boundary  - Affected paths: \`backend/workbench/http/memory_routes.py\`,   \`frontend/src/workbench/MemorySettingsPanel.tsx\` - Allowed paths: this objective,   \`backend/workbench/http/memory_routes.py\`,   \`frontend/src/notebook/domainMemoryApi.ts\`,   \`frontend/src/notebook/domainMemoryContracts.ts\`,   \`frontend/src/notebook/DomainMemoryReviewQueue.tsx\`,   \`frontend/src/workbench/MemorySettingsPanel.tsx\`,   \`tests/test_domain_memory_local_runtime.py\`,   \`frontend/src/notebook/DomainMemoryReviewQueue.notebook.test.tsx\`,   \`frontend/src/workbench/MemorySettingsPanel.test.tsx\` - Protected paths: \`backend/workbench/domain_memory\`,   \`backend/workbench/agent\`, \`backend/workbench/engine\`, \`backend/workbench/app.py\`,   \`frontend/src/notebook/NotebookRouteView.tsx\`, \`frontend/src/notebook/NotebookSurface.tsx\`,   \`docs/superpowers/plans\` - Dependency: \`v1-8-5-a2-memory-management\`,   \`v1-8-5-b2-time-series-default-targets\` - Tests: \`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_domain_memory_local_runtime.py\`; \`npm test -- --run src/notebook/DomainMemoryReviewQueue.notebook.test.tsx src/workbench/MemorySettingsPanel.test.tsx\`; \`npx tsc --noEmit\` - Known gates: Do not stop the user-visible Vite server on port 5177; run TypeScript directly and do not pipe it; direct fixture setup is not browser acceptance and must never be described as such.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=2040000 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-01T18:59:01.000Z `tdd_red_pending_candidate_queue_not_exposed`; cause_status: `known`; cause: Before this slice, GET /domain-memory/candidates was absent and Settings did not load or render the existing candidate-review component.; resolution: `open`; lesson: A server review endpoint and a standalone React component do not create a user workflow unless the current project has a read projection and Settings owns the refresh-and-decision loop.

## All errors

- None recorded.

## All gaps

- #3 2026-08-01T19:17:20.000Z `candidate_readiness_transition_not_wired`; cause_status: `known`; cause: CuratorRuntime creates proposed candidates, while explicit user approval only accepts needs_review candidates and no server-owned readiness transition currently connects the two states.; resolution: `open`; lesson: A candidate queue must expose its lifecycle state honestly and must not present a proposed item as ready for approval.

## All waste

- None recorded.

## Root causes and solutions

- `candidate-governance-needs-server-queue-and-settings-owner`: occurrences=1; cause_status: `known`; root cause: Before this slice, GET /domain-memory/candidates was absent and Settings did not load or render the existing candidate-review component.; solution: `open`
- `candidate-readiness-transition-required`: occurrences=1; cause_status: `known`; root cause: CuratorRuntime creates proposed candidates, while explicit user approval only accepts needs_review candidates and no server-owned readiness transition currently connects the two states.; solution: `open`

## Added tests

- `pytest domain-memory focused suite: 47 passed; frontend candidate-review suite: 13 passed; TypeScript passed`
- `pytest tests/test_domain_memory_local_runtime.py -k pending_candidate_route: 405 Method Not Allowed; npm test -- --run src/workbench/MemorySettingsPanel.test.tsx: pending candidate text absent`

## New rules

- `candidate-governance-needs-server-queue-and-settings-owner`: line experience occurrence(s)=1
- `candidate-readiness-transition-required`: line experience occurrence(s)=1

## Future guidance

- A candidate queue must expose its lifecycle state honestly and must not present a proposed item as ready for approval.
- A server review endpoint and a standalone React component do not create a user workflow unless the current project has a read projection and Settings owns the refresh-and-decision loop.
- Async settings workflows must test delayed success, delayed failure, and delayed data for a former project before relying on request generation alone.

## Event index

- #1: `ac09c503-1b14-4eb3-8aa4-e13a22fa8f25` | 2026-08-01T18:54:27.887Z | STATE_CHANGE/line_started | incident=`c4523e7c-cb1c-499f-9056-1f971bfcf6bc` | lesson_key=`frozen-context-before-start` | event_sha256=`c2fd0d59048a30935346727d8167f50d33a3b5bfdd0887d348957b5b86c8a6cf`
- #2: `62fc4ac6-ff99-4043-9ed8-592b7db9aa5e` | 2026-08-01T18:59:01.000Z | FAILURE/tdd_red_pending_candidate_queue_not_exposed | incident=`f9a2c5c5-5467-4a23-bd4d-68ae43dc2f06` | lesson_key=`candidate-governance-needs-server-queue-and-settings-owner` | event_sha256=`b982076dcff1eb76f0ad78870afdd6d0b160c808a088da8c3ba3f08cf02d9535`
- #3: `5a5e9d43-dc56-40cf-9ebb-a0d644cb793e` | 2026-08-01T19:17:20.000Z | GAP/candidate_readiness_transition_not_wired | incident=`c0e51cf6-e90a-43fe-982e-22d062ff1b99` | lesson_key=`candidate-readiness-transition-required` | event_sha256=`5be629856ca661d58943a0e51b93fc63eaf7b497631ba6ef61b6f9b642db9b14`
- #4: `e5a2baf8-d5e9-450d-9d70-e9ff087f07d4` | 2026-08-01T19:33:01.000Z | GATE/a3_candidate_review_gate_passed | incident=`f9a2c5c5-5467-4a23-bd4d-68ae43dc2f06` | lesson_key=`candidate-governance-needs-server-queue-and-settings-owner` | event_sha256=`8b3d71e95ebbad44ef48606db59fd07a23363042dcba4aec2401033212811c61`
- #5: `aa167159-287b-4e2a-8daa-672e050a0c2a` | 2026-08-01T19:33:01.000Z | STATE_CHANGE/a3_candidate_review_completed | incident=`96c067a9-8b67-48e5-9b22-1ae4a016a40a` | lesson_key=`close-settings-review-at-verified-boundary` | event_sha256=`bd31b008c4e921ddfe44fdee8a076764cbcd79385d8a068dc66bfd8a0ae28db1`
- #6: `00d950f9-e5b7-4e43-b79e-efc1c0e5422d` | 2026-08-01T19:33:01.000Z | REVIEW/a3_independent_review_approved | incident=`7ee4a541-d6dd-452f-9bef-df0c4b9d0b20` | lesson_key=`review-project-scoped-async-state` | event_sha256=`dd2639cfc307d3cc1ed617a8752125df78e9c2c3f7e00d6790c2a627333ddc3b`
