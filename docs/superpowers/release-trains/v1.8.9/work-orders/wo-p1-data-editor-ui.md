# Work order: v1.8.9 P1 direct data editor and metadata UI

- Objective: `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-data-editor-ui-objective.md`
- Formal line: `v1-8-9-p1-data-editor-ui`
- Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Owned paths

- `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`
- `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`
- `frontend/src/lineage/dataOperations.ts`
- `frontend/src/workbench/registry/sectionRegistry.ts`
- `backend/workbench/http/data_operation_routes.py`
- `tests/test_v189_data_editor_ui_contract.py`

## Protected boundaries

- Do not change the central evidence authority, provider catalog contract,
  Agent/Notebook compiler, host identity, or model engines.
- Do not expose source paths, raw rows, raw artifact JSON, or caller-supplied
  metadata as authority.
- Do not add a second metadata or data-operation implementation.

## Acceptance

- A server-owned bounded profile can be fetched for the exact source identity.
- The direct UI renders variable name, label, measurement level, missingness,
  user-missing values, value labels, and bounded sample values.
- A metadata edit is previewed, requires the exact preview fingerprint, and
  renders the typed completion/evidence result; stale or unavailable responses
  remain fail-closed.
- Existing manifest-driven operation controls and focused frontend/backend
  suites remain green; `git diff --check` passes.

## Known gates

- Browser-visible acceptance, real provider, native `.sav/.zsav/.dta`, full
  repository gate, merge, tag, and release remain separate evidence.
