# v1.8.9 P0 design-precheck artifact closeout plan

Formal line: `v1-8-9-p0-design-precheck-artifact`

## Scope

Close the evidence-index regression at baseline
`01d746658eaccaadc4fcd0ee85f7a15fa1bbf225`. The estimation stage already
emits `artifact_type=design_precheck`; the repository's canonical closed
vocabulary must admit that established type without accepting arbitrary
strings or weakening path/digest validation.

## TDD record

1. Added `tests/test_v189_artifact_contracts.py` against the real
   `_validate_artifact_record` entry point.
2. Ran the focused test before the production edit: `1 failed, 1 passed`.
   The expected failure was rejection of `design_precheck` as outside the
   canonical vocabulary; the unknown-type control remained green.
3. Added only `design_precheck` to
   `backend/workbench/repository/run_repository.py`'s closed vocabulary.
4. Focused artifact plus affected model workflow tests: `8 passed`.

## Verification boundary

The wider workflow truth selection now reports `112 passed, 7 failed, 49
warnings`. The seven failures are pre-existing caller/fixture contract
mismatches outside this line: two tests construct incomplete canonical
artifact indexes and therefore fail before the intended source-digest check;
five formal Report race probes still pass raw mappings to the typed Report
writer and fail at the API boundary before the race probe runs. They remain
`NOT VERIFIED` and are not fixed by weakening the new typed Report contract.

Required closeout commands are the focused suite, `compileall`, `git
diff --check`, formal `retrospective`, and formal `verify`. Browser, provider,
host full-gate, central consumer, release, merge, tag, and push remain
`NOT VERIFIED`.
