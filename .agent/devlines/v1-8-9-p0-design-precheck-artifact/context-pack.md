# Frozen Context Pack

Line: `v1-8-9-p0-design-precheck-artifact`
Baseline SHA: `01d746658eaccaadc4fcd0ee85f7a15fa1bbf225`

## Objective
# Workbench v1.8.9 P0 design-precheck artifact objective

## Objective

Close the exact-baseline workflow evidence regression at
`01d746658eaccaadc4fcd0ee85f7a15fa1bbf225`: the workflow emits a typed
`design_precheck` artifact, but the canonical repository artifact vocabulary
does not admit that type. As a result, model estimation can complete while
the formal artifact index is rejected as invalid.

## Required behavior

- `design_precheck` is admitted by the same closed canonical artifact
  vocabulary used by the repository reader.
- The reader still rejects unknown artifact types and malformed records.
- Add a regression probe against the real canonical record validator.
- Re-run the affected workflow truth tests to prove model results and evidence
  can be consumed after the index is validated.
- Do not loosen path, digest, required-field, or result-evidence checks.

## Scope

Allowed product/test/document paths:

- `backend/workbench/repository/run_repository.py`
- `tests/test_v189_artifact_contracts.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-design-precheck-artifact-objective.md`
- `docs/superpowers/plans/2026-08-20-design-precheck-artifact.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-design-precheck-artifact-handoff.md`

Protected paths include model estimators, Survey engine, central Agent/
Notebook/Report cutover, other worktrees, and release/merge/tag/push
machinery.

## Baseline, dependency, and gates

- Exact baseline: `01d746658eaccaadc4fcd0ee85f7a15fa1bbf225`.
- Dependency: `v1-8-9-p0-survey-absence-boundary`.
- Required checks: TDD RED before production edits, focused artifact contract
  tests, affected workflow truth tests, compileall, `git diff --check`, formal
  verify, and retrospective.
- Browser, provider, host, full gate, central candidate, release, merge, tag,
  and push remain `NOT VERIFIED`.

## Completion target

The line is complete only when `design_precheck` is admitted without admitting
arbitrary unknown types, and an affected workflow truth test proves the model
artifact can be read through the canonical index.

## Boundary
- Affected paths: `backend/workbench/repository/run_repository.py`, `tests/test_v189_artifact_contracts.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-design-precheck-artifact-objective.md`, `docs/superpowers/plans/2026-08-20-design-precheck-artifact.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-design-precheck-artifact-handoff.md`
- Allowed paths: `backend/workbench/repository/run_repository.py`, `tests/test_v189_artifact_contracts.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-design-precheck-artifact-objective.md`, `docs/superpowers/plans/2026-08-20-design-precheck-artifact.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-design-precheck-artifact-handoff.md`
- Protected paths: none
- Dependencies: `v1-8-9-p0-survey-absence-boundary`
- Tests: `tests/test_v189_artifact_contracts.py`, `tests/test_workflow_runtime.py`, `tests/test_v189_workflow_truth.py`
- Known gates: `central consumer cutover remains NOT VERIFIED`, `browser/provider/host/full-gate/release remain NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
