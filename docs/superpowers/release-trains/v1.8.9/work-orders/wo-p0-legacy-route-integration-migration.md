# Work Order: v1.8.9 P0 legacy route/workflow integration migration

## Scope

Test-only compatibility migration for the four remaining full-gate failures in
the Agent analysis-loop route and workflow integration suites.

## Owned paths

- `tests/test_agent_analysis_loop_routes.py`
- `tests/test_agent_workflow_integration.py`
- this objective and work order

## Protected boundaries

Do not modify production Agent/Notebook compiler, proposal authority, workflow
runtime, evidence, Report, data operations, model engines, frontend, catalog,
or provider code. Do not add a test-local trust shortcut.

## Acceptance

- The four previously failing tests pass against the current server-owned
  proposal/compiler boundary.
- The adjacent route/workflow tests remain green.
- `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_agent_analysis_loop_routes.py tests/test_agent_workflow_integration.py -q --disable-warnings`
  passes, selected `compileall` passes, and `git diff --check` passes.

## Known gates

Browser, external provider, cross-process restart, full host gate, merge, tag,
and release remain separate evidence.
