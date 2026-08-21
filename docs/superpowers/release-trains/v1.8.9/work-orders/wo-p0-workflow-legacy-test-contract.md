# Work Order: v1.8.9 P0 workflow legacy-test contract migration

## Scope

Update only stale test fixtures that still call the pre-hardening workflow and
data-management contracts.

## Owned paths

- `tests/test_agent_data_management_p4.py`
- `tests/test_agent_generic_workflow.py`
- `tests/test_agent_natural_language_reach_v187.py`
- this objective and work order

## Protected boundaries

Do not change production workflow authority, compiler scope validation,
metadata registry requirements, model execution, Agent/Notebook/Report routes,
frontend, or provider wiring.

## Acceptance

- the three owned test files are run together and their result is recorded;
- compile and diff checks pass;
- formal line records the current fail-closed contract, any owned-suite
  residual, and the separate browser/provider/full-gate limits.

## Current evidence boundary

The fixture migration itself is complete for compiler scope, confirmed
metadata, composition, derived-column, survey-design, and execution setup.
The exact scoped suite currently reports `61 passed, 1 failed`. The remaining
failure is intentionally preserved rather than masked: the `data.rename`
workflow adapter persists its result in the public artifact index but does not
admit the result into the active server-owned workflow artifact registry, so a
dependent `model.genesis` step aborts with
`WORKFLOW_ARTIFACT_REGISTRY_REQUIRED`. Fixing that adapter belongs to a
production integration line and is outside this test-contract line.

`compileall` and `git diff --check` are local checks only. Browser acceptance,
real provider acceptance, full host integration, and release readiness remain
`NOT VERIFIED`.
