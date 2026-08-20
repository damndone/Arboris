# Survey remediation-2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Agent result and diagnostics projections omit absent persisted Survey/optional fields while preserving typed unavailable reasons and projecting real committed Notebook Survey packets through the bounded public-result seam.

**Architecture:** Keep the existing server-owned artifact verification and shared Survey projection as the authority. Change only the Agent projection assembly so optional sections are attached conditionally when persisted evidence produces them; use committed Notebook receipt fixtures to exercise the same `_public_operation_artifact_result` path used by the workflow reader. Report remains a regression boundary and is verified without changing its established projection.

**Tech Stack:** Python 3.14, pytest, Workbench `NodeOperationContextProvider`, server-owned artifact indexes, committed Notebook JSONL receipts, formal `scripts/devline_control.py`.

---

### Task 1: Freeze remediation-2 scope and formal evidence

**Files:**
- Create: `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-2-objective.md`
- Create: `.agent/devlines/v1-8-9-p1-survey-remediation-2/*` through `scripts/devline_control.py start`
- Create: `docs/superpowers/plans/2026-08-20-survey-remediation-2.md`

- [x] **Step 1: Read the root rules, global rules, prior Context Pack, prior retrospective, and prior handoff.**
- [x] **Step 2: Verify the exact baseline is `35898162aa6f15420997665a05f70c4f589e6f97` and the new line name is unused.**
- [x] **Step 3: Start only `v1-8-9-p1-survey-remediation-2` via the formal CLI with the objective, exact affected/allowed paths, protected historical lines, focused tests, and known gates.**
- [x] **Step 4: Read the generated `context-pack.md` and verify it before implementation.**

### Task 2: Add RED Agent unavailable/no-Survey probes

**Files:**
- Modify: `tests/test_agent_context_tools.py`
- Modify: `tests/test_agent_reads_v187_results.py`

- [x] **Step 1: Add a direct `_agent_result_unavailable` contract probe asserting only typed availability/status/reason fields and no synthetic Survey/table fields.**
- [x] **Step 2: Add a real provider workflow probe that removes or invalidates server-owned model artifacts and asserts both `inspect_result_summary` and `inspect_diagnostics` omit optional Survey/table fields while preserving `available=False`, status, and reason.**
- [x] **Step 3: Add a real ordinary non-Survey workflow probe using the existing OLS fixture and assert diagnostics/result output does not contain `survey_design`, `marginal_effects`, or optional table placeholders when no persisted fields exist.**
- [x] **Step 4: Run the narrow new probes and confirm they fail because current code emits `None`/empty placeholders.**

### Task 3: Add RED committed Notebook Survey packet probes

**Files:**
- Modify: `tests/test_agent_context_tools.py`

- [x] **Step 1: Extend the committed Notebook receipt fixture with a registered post-estimation packet containing bounded Survey metadata, then add a real receipt-reader probe asserting typed metadata and provenance survive.**
- [x] **Step 2: Add the matching packet-without-Survey-metadata probe asserting no Survey field is invented.**
- [x] **Step 3: Run both probes and record whether the package-local admitted Notebook path is covered; leave admitted central Notebook acceptance explicitly `NOT VERIFIED`.**

### Task 4: Minimal conditional Agent projection repair

**Files:**
- Modify: `backend/workbench/agent/context_tools.py`

- [x] **Step 1: Make `_agent_result_unavailable` return only typed unavailable fields.**
- [x] **Step 2: Change diagnostics assembly to attach `survey_design` only when `_bounded_survey_design` returns persisted evidence and attach `regression_table` only when a bounded table has a persisted model source.**
- [x] **Step 3: Make result-summary optional persisted sections conditional, including existing summary/table metadata that would otherwise become synthetic `None`/`[]`; preserve bounded typed values when source keys exist.**
- [x] **Step 4: Route committed Notebook artifact results through the existing bounded public-result function without defaulting missing Survey metadata.**

### Task 5: Green and regression verification

**Files:**
- No additional product files; verify `backend/workbench/report_view_model.py` and existing Survey engine paths.

- [x] **Step 1: Rerun the RED probes and the focused Agent/Notebook/Report suites.**
- [x] **Step 2: Rerun the Survey regression suites covering falsey declarations, shared variance, weights, replicate weights, and exposure.**
- [x] **Step 3: Run `compileall` and `git diff --check`.**
- [x] **Step 4: Record all material RED/GREEN/GAP/REVIEW/STATE_CHANGE events via CLI, including the historical state-chain gap and current reproducible mismatch count.**

### Task 6: Exact-tip handoff and closeout

**Files:**
- Create: `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-2-handoff.md`
- Modify only through CLI: `.agent/devlines/v1-8-9-p1-survey-remediation-2/*`

- [x] **Step 1: Commit the product/test fix and capture the exact product tip.**
- [x] **Step 2: Write the handoff with exact tip, formal manifest, commands, real counts, Notebook coverage, the computed historical state-chain mismatch, and all NOT VERIFIED boundaries.**
- [x] **Step 3: Append final gate and continuous state transition through CLI, run formal verify and retrospective, and commit formal records plus handoff.**
- [x] **Step 4: Verify clean worktree and report product tip/final tip separately without claiming central or release acceptance.**
