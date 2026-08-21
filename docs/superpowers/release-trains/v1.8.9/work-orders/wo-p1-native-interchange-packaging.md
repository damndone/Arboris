# Work order: v1.8.9 P1 native interchange packaging

## Scope

Add the `native` optional dependency extra for `pyreadstat` and document the
clean-install command for SPSS/Stata interchange. Keep the adapter's typed
unavailable behavior when the extra is absent or unusable.

## Allowed paths

- `pyproject.toml`
- `README.md`
- `tests/test_v189_data_interchange.py`
- `tests/test_v189_data_operation_manifest.py`
- this objective and work order

## Protected paths

- `backend/workbench/data_interchange.py`
- `backend/workbench/data_operation_manifest.py`
- Agent, Notebook, Report, provider, evidence, and deployment runtime paths

## Checks

- red metadata assertion before the package edit;
- native round-trip and fail-closed interchange suites;
- manifest capability suite;
- `git diff --check`;
- formal verification and generated retrospective.
