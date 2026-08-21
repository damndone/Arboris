# Work Order: Agent/Notebook Runtime Bootstrap

Development line: `v1-8-9-agent-notebook-runtime-bootstrap`

This work order executes the runtime-bootstrap objective after the existing
contract-lock, P0 workflow/evidence/compiler, data-consumer, classification,
and consumer-projection lines. The line owns only provider contribution
composition and application bootstrap. It must preserve the current dirty
integration worktree and use the formal devline CLI for all line records.

## Write boundary

- `backend/workbench/agent/provider_runtime_contributions.py`
- `backend/workbench/agent/runtime_bootstrap.py`
- `backend/workbench/app.py`
- `backend/workbench/data_operation_manifest.py`
- `backend/workbench/predictive_research/classification_adapters.py`
- `backend/workbench/agent/cutover_runtime.py`
- `tests/test_v189_agent_notebook_runtime_bootstrap.py`
- `tests/test_v189_data_operation_manifest.py`
- `tests/test_v189_classification_production.py`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-agent-notebook-runtime-bootstrap-handoff.md`

## Protected boundary

The statistical estimator packages, Evidence Core persistence/egress,
Report projection semantics, frontend mounts, and release artifacts are
protected. Any public-contract change must return to the owning lane.

## Acceptance commands

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  tests/test_v189_agent_notebook_runtime_bootstrap.py \
  tests/test_v189_agent_notebook_runtime_bridge.py \
  tests/test_v189_agent_notebook_cutover.py -q
PYTHONPATH=backend .venv/bin/python -m pytest \
  tests/test_v189_data_operation_manifest.py \
  tests/test_v189_classification_production.py -q
PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests
git diff --check
```

## Known gates

Focused tests do not substitute for real provider, browser, host identity,
cross-process, full-gate, merge, tag, or release evidence.
