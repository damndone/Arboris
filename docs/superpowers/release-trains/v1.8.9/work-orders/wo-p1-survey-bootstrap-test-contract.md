# Work Order: v1.8.9 P1 Survey bootstrap test contract

## Scope

Migrate one stale clean-process Survey capability test to the current typed
bootstrap contract after the import-cycle fix.

## Owned paths

- `tests/test_survey_glm_family_wiring_v189.py`
- this objective and work order

## Protected boundaries

Do not modify Survey estimators, capability registry production code, Agent,
Notebook, Report, evidence, frontend, or provider wiring.

## Acceptance

- the owned Survey suite passes;
- compile and diff checks pass;
- formal line records focused evidence and keeps browser/provider/full/release
  gates separate.
