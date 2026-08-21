# Work order: v1.8.9 P1 evidence-surface integration

## Objective

Implement the objective in
`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-evidence-surface-integration-objective.md`.

## Parallel lanes

### Lane A — Report data-consumer surface

Write scope:

- `frontend/src/report/ReportWorkspaceContext.tsx`
- `frontend/src/report/ReportView.tsx`
- new or adjacent Report-only typed evidence component and tests

Do not modify backend routes or Survey services. Consume the existing run
detail fields and fail closed on malformed/unknown payloads.

### Lane B — Survey run-detail surface

Write scope:

- `backend/workbench/http/runs_routes.py`
- Survey-specific backend service adapter if needed
- Survey backend tests and handoff notes

Do not modify Report frontend files. Use the existing capability-only Survey
consumer service and server-owned run resolution.

## Integration verification

Run the lane-focused suites, then the combined P1 evidence consumer suite,
selected frontend typecheck/tests, `compileall` for changed Python modules,
and `git diff --check`. Record any failure or unverified gate through formal
development-line events before closeout.

