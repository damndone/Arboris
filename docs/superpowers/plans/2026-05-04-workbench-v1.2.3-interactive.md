# Workbench V1.2.3 Interactive Submit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Submit into an end-to-end workbench with file preview, smart variable selection, multi-regressor support, richer model outputs, and inline results.

**Architecture:** Keep the existing `/runs` backend API and pass selected x variables as the current comma-separated form field. Add client-side preview parsing in `frontend/src/api.ts`, extract the existing detail renderer into `frontend/src/runResult.tsx`, and extend backend orchestration to write multiple model result artifacts and diagnostic figures.

**Tech Stack:** React 18, Vite, Vitest, SheetJS `xlsx`, FastAPI, pandas, statsmodels, scipy, matplotlib, pytest.

---

### Task 1: Frontend File Preview

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/api.ts`
- Test: `frontend/src/api.test.ts`

- [ ] Write failing Vitest tests for `previewFile()` parsing CSV and XLSX files, including inferred row/column counts, suggested y, and suggested x.
- [ ] Run `npm test -- src/api.test.ts` and confirm preview tests fail because `previewFile` does not exist.
- [ ] Install `xlsx` and implement `previewFile(file: File): Promise<FilePreview>` using the first worksheet for CSV/XLS/XLSX.
- [ ] Run `npm test -- src/api.test.ts` and confirm all API tests pass.

### Task 2: Submit Page Preview And Inline Results

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/runResult.tsx`
- Modify: `frontend/src/runHistory.tsx`
- Modify: `frontend/src/runDetail.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/App.test.tsx`

- [ ] Write failing React tests for accepting `.xlsx`, showing a preview table, defaulting y/x from preview suggestions, running without navigation after submit, preserving direct `/runs/:runId?project_root=...` access, and expanding history results inline.
- [ ] Run `npm test -- src/App.test.tsx` and confirm the new tests fail against V1.2.2 UI.
- [ ] Extract `RunResultView` from `runDetail.tsx`; remove the back button and route-specific rendering from the shared component.
- [ ] Update Submit to show folder browse input, file preview, radio y selection, x checkboxes, manual fallback text inputs, SSE/detail result view after submit, and no route navigation after run.
- [ ] Update History to keep the user on `/runs` and render `RunResultView` below the selected row/table.
- [ ] Keep `/runs/:runId` route and turn `runDetail.tsx` into a thin wrapper that reads `runId` from params and renders `RunResultView`.
- [ ] Run `npm test -- src/App.test.tsx` and confirm page tests pass.

### Task 3: Backend Model Routing And Figures

**Files:**
- Modify: `backend/workbench/orchestrator.py`
- Modify: `backend/workbench/visualization.py`
- Modify: `backend/workbench/narrative.py`
- Test: `tests/test_orchestrator_e2e.py`
- Test: `tests/test_visualization.py`
- Test: `tests/test_reporting_exports.py`

- [ ] Write failing pytest tests for panel routing creating `fe_1.json` plus `ols_1.json`, OLS baseline artifact id changing to `ols_1`, residual/QQ/coefficient plot artifacts, and narrative claims including magnitude plus significance wording.
- [ ] Run targeted pytest tests and confirm failures.
- [ ] Import `run_fixed_effects` and `run_time_series_diagnostics`; route panel datasets to fixed effects when an entity id exists and always run OLS baseline.
- [ ] Pass model results into `create_figures()` and `build_claims()`, export coefficient rows across all models.
- [ ] Add residuals-vs-fitted, Q-Q residual, and coefficient forest plots without adding new Python dependencies.
- [ ] Enhance `build_claims()` claim text with estimate magnitude, p-value significance band, and R-squared interpretation.
- [ ] Run targeted pytest tests and confirm they pass.

### Task 4: Full Verification

**Files:**
- All modified files.

- [ ] Run `npm test` from `frontend`.
- [ ] Run `../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests -q` from the worktree root.
- [ ] Run `git status --short` and review all changed files are scoped to V1.2.3.
