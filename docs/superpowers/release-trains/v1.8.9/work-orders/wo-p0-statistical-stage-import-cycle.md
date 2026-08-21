# Work Order: v1.8.9 P0 statistical stage import-cycle and ARMA gate

## Scope

Fix the production import cycle observed by the ARMA-GARCH pack runtime and
update only the directly adjacent public workflow assertion that still expects
an unauthorised HTML report.

## Owned paths

- `backend/workbench/engine/stages/statistical_tests.py`
- `backend/workbench/orchestrator/__init__.py`
- `backend/workbench/orchestrator/_errors.py`
- `tests/models/arma_garch/test_pack_runtime.py`
- this objective and work order

## Protected boundaries

Do not modify model formulas, statistical estimators, evidence authority,
Report writer authority, provider runtime, frontend, data interchange, or
Agent/Notebook compiler behavior. Do not reintroduce a raw `report.html`
fallback.

## Acceptance

- the ARMA pack runtime focused tests pass or preserve only explicit host-bound
  skips;
- production imports no longer form the observed `StatisticalTestsStage`
  cycle;
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest tests/models/arma_garch/test_pack_runtime.py -q --disable-warnings` passes;
- selected compileall and `git diff --check` pass.

## Known gates

Browser, external provider, cross-process, full host gate, merge, tag, and
release remain separate evidence.
