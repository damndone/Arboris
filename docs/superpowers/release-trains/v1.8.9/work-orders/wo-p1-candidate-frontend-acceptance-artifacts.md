# Work order: v1.8.9 candidate frontend acceptance artifacts

## Scope

Add only the four frontend tests named by the candidate-bound foundation
runner. Keep them aligned with the existing public components and typed
evidence contracts.

## Allowed paths

- `frontend/src/lineage/LineageRouteContainer.v189.test.tsx`
- `frontend/src/notebook/NotebookRouteView.v189.test.tsx`
- `frontend/src/report/ReportView.integration-v189.test.tsx`
- `frontend/src/evaluation/v189/status.test.ts`
- this objective and work order

## Protected paths

- all frontend production components and API code
- backend, Agent, Notebook, Report runtime, provider, evidence, and release paths

## Checks

- red evidence that the runner-declared paths are missing;
- exact four-file Vitest command;
- `git diff --check`;
- formal verification and generated retrospective.
