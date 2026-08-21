# Frozen Context Pack

Line: `v1-8-9-p1-candidate-frontend-acceptance-artifacts`
Baseline SHA: `c0a590920fd399aad41466483d3cd777a8a08edf`

## Objective
# Workbench v1.8.9 candidate frontend acceptance artifacts objective

Restore the four typed frontend acceptance tests required by the immutable
v1.8.9 foundation runner. These tests are acceptance fixtures, not a second
frontend runtime: they must exercise the existing Lineage data-operation,
Notebook planning, Report evidence, and evaluation-status contracts already
present in the candidate.

Required outcomes:

- the four runner-declared paths exist in the candidate;
- each test uses the current public component/contract surface;
- Lineage proves preview-before-confirm and source identity binding;
- Notebook proves plan-only state does not expose an executable confirmation;
- Report proves typed evidence renders and unknown raw payloads become
  unavailable without leaking their contents;
- evaluation status proves incomplete evidence is rejected rather than
  synthesized;
- the exact four-file Vitest command passes and `git diff --check` passes.

This line does not change product behavior, acceptance runner policy,
provider authority, statistical estimators, browser automation, or release
state.

## Boundary
- Affected paths: `frontend/src/lineage/LineageRouteContainer.v189.test.tsx`, `frontend/src/notebook/NotebookRouteView.v189.test.tsx`, `frontend/src/report/ReportView.integration-v189.test.tsx`, `frontend/src/evaluation/v189/status.test.ts`
- Allowed paths: `frontend/src/lineage/LineageRouteContainer.v189.test.tsx`, `frontend/src/notebook/NotebookRouteView.v189.test.tsx`, `frontend/src/report/ReportView.integration-v189.test.tsx`, `frontend/src/evaluation/v189/status.test.ts`, `docs/superpowers/objectives/2026-08-21-v1.8.9-candidate-frontend-acceptance-artifacts-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-candidate-frontend-acceptance-artifacts.md`
- Protected paths: `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/reportEvidence.ts`, `backend`
- Dependencies: none
- Tests: `frontend/node_modules/.bin/vitest run src/lineage/LineageRouteContainer.v189.test.tsx src/notebook/NotebookRouteView.v189.test.tsx src/report/ReportView.integration-v189.test.tsx src/evaluation/v189/status.test.ts`, `git diff --check`
- Known gates: `browser automation is separate from component-level candidate acceptance`, `real provider, supervisor, cross-process, full repository and release remain NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
