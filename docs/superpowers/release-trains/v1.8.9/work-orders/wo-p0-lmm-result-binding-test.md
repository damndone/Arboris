# Work Order: v1.8.9 P0 LMM result-binding test contract

## Scope

Update the single stale LMM admission test double to declare the current
registered result binding key.

## Owned paths

- `tests/engine/test_lmm_execution_admission.py`
- this objective and work order

## Protected boundaries

Do not change the LMM engine, result registry, workflow authority, Report,
Agent/Notebook routes, frontend, or provider wiring.

## Acceptance

- the owned LMM execution-admission test file passes;
- compile and diff checks pass;
- formal line closes only its bounded test-contract objective.
