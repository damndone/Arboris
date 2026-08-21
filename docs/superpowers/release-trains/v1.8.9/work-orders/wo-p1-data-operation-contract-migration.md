# Work order: v1.8.9 P1 data-operation contract migration

- Objective: `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-data-operation-contract-migration-objective.md`
- Formal line: `v1-8-9-p1-data-operation-contract-migration`
- Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Allowed paths

- `tests/test_data_column_cast.py`
- `tests/test_data_columns_cast.py`
- `tests/test_data_operation_routes.py`
- this objective and work order

## Protected paths

- `backend/workbench/agent/proposals.py`
- `backend/workbench/agent/orchestrator.py`
- `backend/workbench/data_operations.py`
- `backend/workbench/http/agent_routes.py`
- `backend/workbench/http/data_operation_routes.py`
- all prior formal records, root checkout, and other worktrees

## Required tests

```text
PYTHONPATH=backend:tests .venv/bin/python -m pytest tests/test_data_column_cast.py tests/test_data_columns_cast.py tests/test_data_operation_routes.py -q --disable-warnings
PYTHONPATH=backend:tests .venv/bin/python -m pytest tests/test_v189_data_editor_ui_contract.py tests/test_v189_data_consumer_editor.py tests/test_v189_data_consumer_central_mount.py tests/test_v189_data_host_port.py tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py -q --disable-warnings
PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests
git diff --check
```

## Safety rule

Do not remove or relax the `ProposalStoreCapabilityV1` requirement and do not
make legacy metadata authoritative. If a fixture cannot use the existing
server-owned seam, record the incompatibility as a typed gap rather than
inventing a test-only authority.

