# Work Order: v1.8.9 P1 native interchange metadata and fail-closed adapter

## Scope

Extend the existing pyreadstat-backed native interchange adapter with typed
metadata round-trip and robust unavailable/loss behavior.

## Owned paths

- `backend/workbench/data_interchange.py`
- `tests/test_v189_data_interchange.py`
- this objective and work order

## Protected boundaries

Do not change proposal authority, compiler, evidence, Report, Agent/Notebook
routes, model engines, frontend, or package dependencies outside the existing
native extra.

## Acceptance

- focused native interchange and manifest tests cover variable/value labels,
  unsupported metadata loss, corrupt input, non-DataFrame adapter output, and
  partial-write cleanup;
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py -q --disable-warnings` passes;
- selected compileall and `git diff --check` pass.

## Known gates

Browser, external provider, cross-process, full host gate, clean-install
optional dependency execution, merge, tag, and release remain separate
evidence.
