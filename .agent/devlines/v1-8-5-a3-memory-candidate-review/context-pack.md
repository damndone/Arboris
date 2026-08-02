# Frozen Context Pack

Line: `v1-8-5-a3-memory-candidate-review`
Baseline SHA: `b8da1f98da1b1b67d1b34d39ed6907fdd935447c`

## Objective
# v1.8.5 A3 — Memory Candidate Review Objective

This is the narrowly scoped user-management completion slice for the approved
v1.8.5 typed-memory design. The parent design remains the only authority for
version scope.

## Objective

Make an already server-created pending project-memory candidate visible and
reviewable from **Settings → Memory**, with an explicit approve/reject choice.
The user must never need a file path, an HTTP client, or a developer tool to
review it. Approval remains a memory-governance action only: it never starts
analysis, executes code, changes a current Draft, or bypasses later
Proposal/Risk confirmation.

## Scope

- Publish a read-only, current-project endpoint for pending candidates. The
  server derives the project scope from `project_root`; clients never submit
  scope or owner identity.
- Extend the existing Memory settings API/types and panel to load the queue,
  show each lesson, kind and bounded source references, and issue an explicit
  approve or reject request.
- Approval sends the candidate's current revision, a local reviewer identity,
  the current timestamp, and a bounded review date. A stale revision or
  unresolved conflict stays fail-closed and is shown as an error; it must not
  silently retry or select a conflict winner.
- Refresh settings, libraries and queue after a successful decision. Rejected
  or approved candidates disappear from the pending queue; an approved entry
  becomes visible only in its project library.
- Add red-first route and frontend tests for server-derived scope, no-execute
  surface, stale failure visibility, and the visible user decision flow.

## Explicit non-scope

- No new candidate-generation trigger, LLM curator, semantic retrieval,
  cross-project promotion, manual free-form memory authoring, or new automatic
  execution surface.
- No changes to default-target registry, memory retrieval/admission, Recipe
  validation, model fitting, execution authorization, or candidate contract
  schemas.
- No deletion/enablement semantic change: their existing server-bound
  two-step confirmations remain unchanged. Candidate review is a separate,
  explicit governance decision.

## Acceptance

Tests fail before the list/read wiring exists and pass after it. One visible
Workbench acceptance must show an existing pending candidate in Settings,
allow an explicit decision, and show no analysis execution. The acceptance
may use a bounded local fixture to populate the existing candidate journal,
but must label that setup as fixture preparation rather than an end-user
candidate-generation flow.

## Boundary

- Affected paths: `backend/workbench/http/memory_routes.py`,
  `frontend/src/workbench/MemorySettingsPanel.tsx`
- Allowed paths: this objective,
  `backend/workbench/http/memory_routes.py`,
  `frontend/src/notebook/domainMemoryApi.ts`,
  `frontend/src/notebook/domainMemoryContracts.ts`,
  `frontend/src/notebook/DomainMemoryReviewQueue.tsx`,
  `frontend/src/workbench/MemorySettingsPanel.tsx`,
  `tests/test_domain_memory_local_runtime.py`,
  `frontend/src/notebook/DomainMemoryReviewQueue.notebook.test.tsx`,
  `frontend/src/workbench/MemorySettingsPanel.test.tsx`
- Protected paths: `backend/workbench/domain_memory`,
  `backend/workbench/agent`, `backend/workbench/engine`, `backend/workbench/app.py`,
  `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookSurface.tsx`,
  `docs/superpowers/plans`
- Dependency: `v1-8-5-a2-memory-management`,
  `v1-8-5-b2-time-series-default-targets`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_domain_memory_local_runtime.py`; `npm test -- --run src/notebook/DomainMemoryReviewQueue.notebook.test.tsx src/workbench/MemorySettingsPanel.test.tsx`; `npx tsc --noEmit`
- Known gates: Do not stop the user-visible Vite server on port 5177; run TypeScript directly and do not pipe it; direct fixture setup is not browser acceptance and must never be described as such.

## Boundary
- Affected paths: `backend/workbench/http/memory_routes.py`, `frontend/src/workbench/MemorySettingsPanel.tsx`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.5-a3-memory-candidate-review-objective.md`, `backend/workbench/http/memory_routes.py`, `frontend/src/notebook/domainMemoryApi.ts`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/DomainMemoryReviewQueue.tsx`, `frontend/src/workbench/MemorySettingsPanel.tsx`, `tests/test_domain_memory_local_runtime.py`, `frontend/src/notebook/DomainMemoryReviewQueue.notebook.test.tsx`, `frontend/src/workbench/MemorySettingsPanel.test.tsx`
- Protected paths: `backend/workbench/domain_memory`, `backend/workbench/agent`, `backend/workbench/engine`, `backend/workbench/app.py`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookSurface.tsx`, `docs/superpowers/plans`
- Dependencies: `v1-8-5-a2-memory-management`, `v1-8-5-b2-time-series-default-targets`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_domain_memory_local_runtime.py`, `npm test -- --run src/notebook/DomainMemoryReviewQueue.notebook.test.tsx src/workbench/MemorySettingsPanel.test.tsx`, `npx tsc --noEmit`
- Known gates: `Do not stop the user-visible Vite server on port 5177.`, `Run TypeScript directly and do not pipe it.`, `Direct fixture setup is not browser acceptance and must never be described as such.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
