# Work order: v1.8.9 P1 native statistical-file interchange

- Objective: `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-native-statistical-interchange-objective.md`
- Formal line: `v1-8-9-p1-native-statistical-interchange`
- Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Allowed paths

- `pyproject.toml`
- `backend/workbench/data_interchange.py`
- `tests/test_v189_data_interchange.py`
- `tests/test_v189_data_operation_manifest.py`
- `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-native-statistical-interchange-objective.md`
- this work order

## Protected paths

- `backend/workbench/agent/**`
- `backend/workbench/data_operations.py`
- `backend/workbench/http/**`
- `backend/workbench/providers/**`
- `frontend/**`
- all prior formal records, root checkout, and other worktrees

## Required tests

```text
PYTHONPATH=backend:tests .venv/bin/python -m pytest tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py -q --disable-warnings
PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/data_interchange.py tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py
git diff --check
```

## Safety rule

Do not advertise native availability based only on package discovery. The
adapter must pass its bounded import and real probe, and every failed write or
read must leave no invented artifact or success evidence.

## Bounded RED → GREEN record (2026-08-21)

### RED

With `pyreadstat==1.3.6` installed, the focused interchange/manifest suite
reported `41 passed, 1 failed`. The failure was
`test_pyreadstat_admission_runs_a_bounded_probe_through_the_real_adapter`:
`_pyreadstat_probe_succeeded` used the column name
`__workbench_probe__`, which pyreadstat rejects because variable names may not
start with `_`; admission therefore returned `None` instead of claiming the
real adapter was available. The test-first extension also reproduced the same
failure for the synthetic SAV/ZSAV/DTA probe (`42 passed, 2 failed`).

### GREEN

- Changed only the bounded probe column name to `workbench_probe`; the probe
  still performs real SAV, compressed ZSAV, and DTA write/read operations.
- Added real public-contract round-trip evidence tests for `.sav`, `.zsav`,
  and `.dta`, including non-empty artifact evidence, value equality, and
  schema/dtype equality.
- Added native metadata-loss assertions for measurement level and user-missing
  fields; these results remain `metadata_loss`, never `verified`.
- Kept missing, broken-import, and broken-callable adapter tests explicitly
  typed `unavailable`; no `find_spec`-only admission or fallback was added.
- Made the stable provider-fixture test pin the environment-sensitive optional
  native capability to its unavailable fixture baseline; live manifest status
  remains tested separately.

Fresh verification:

```text
PYTHONPATH=backend:tests .venv/bin/python -m pytest tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py -q --disable-warnings
44 passed in 1.71s

PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/data_interchange.py tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py
exit 0

git diff --check
exit 0

PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --line v1-8-9-p1-native-statistical-interchange
exit 0
```

This bounded line does not claim browser, real-provider, full-host, merge,
tag, or release acceptance.
