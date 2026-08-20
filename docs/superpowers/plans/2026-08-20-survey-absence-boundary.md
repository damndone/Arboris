# v1.8.9 P0 survey-absence boundary plan

## Completed scope

1. Freeze the exact baseline `7756709aa9c34084ccfe1e2e9060af4c5a9423f9` and
   formal line `v1-8-9-p0-survey-absence-boundary`.
2. Add a red HTTP-to-dispatch regression probe for an omitted survey
   subpopulation.
3. Make `/runs` and `/runs/batch` nullable at the HTTP boundary; make the
   service dispatch default nullable without weakening the typed Survey
   adapter.
4. Prove explicit empty and falsey declarations still fail closed.
5. Run the focused wiring suite, compileall, and diff check; record the
   inherited broad workflow failures separately from this fix.

## Verification

- `tests/test_survey_design_wiring_v187.py`: 23 passed, 1 warning.
- The original RED probe observed `survey_subpop == ""`.
- The green probe observes `survey_subpop is None` when the HTTP field is
  omitted.
- Explicit empty and falsey typed declarations remain `SURVEY_SUBPOP_INVALID`
  (or their existing typed validation code).
- `compileall`: passed.
- `git diff --check`: passed.

## Not claimed by this plan

This boundary fix does not close persisted model-branch migration, the strict
legacy raw-mapping report race fixtures, central consumer coverage, browser or
provider acceptance, host/full-gate acceptance, or release readiness.
