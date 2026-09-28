# WO: Agent / Notebook Runtime Bridge

## Baseline

- Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a`
- Branch: `workbench-v1.8.9-wave-a`
- Exact baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Upstream slice: `v1-8-9-agent-notebook-cutover`
- Integration mode: uncommitted worktree; no merge, push, tag or release.

## Parallel ownership

| lane | owned files | deliverable |
|---|---|---|
| Runtime/bootstrap | `backend/workbench/agent/cutover_runtime.py`, `backend/workbench/app.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_agent_notebook_runtime_bridge.py` | Explicit server bootstrap and provider runtime join |
| Notebook adapter | `backend/workbench/http/notebook_routes.py`, `tests/test_v189_notebook_cutover_route.py` | Scope-checked Notebook natural-language bridge |
| Report consumer | `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx` | Hash-checked classification evidence loading |
| Integrator | handoff, focused verification, formal events | Review seams and preserve existing suites |

No lane edits another lane's source or test files. The integrator may make only
minimal conflict-resolution edits after reviewing the owning lane's tests.

## Protected paths

- `backend/workbench/agent/workflow_runtime.py`
- `backend/workbench/agent/workflow.py`
- `backend/workbench/agent/plan_compiler.py`
- `backend/workbench/agent/context_compiler.py`
- `backend/workbench/data_operations.py`
- `backend/workbench/evidence`
- `backend/workbench/predictive_research`

## Required gates

- New runtime bridge and Notebook route tests.
- Existing `tests/test_v189_agent_notebook_cutover.py`,
  `tests/test_notebook_planning_agent.py`, and `tests/test_notebook_routes.py` targeted
  regression where compatible.
- Frontend classification/report context tests and `npm run typecheck`.
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench`.
- `git diff --check`.
- Formal Context Pack verify and retrospective through `scripts/devline_control.py`.

## Explicit non-goals

- No new statistical formula, model family, external provider call or default fake runtime.
- No migration of the protected historical workflow runtime.
- No browser acceptance or release claim.
