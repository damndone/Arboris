# Frozen Context Pack

Line: `v1-8-9-p0-model-branch-resume`
Baseline SHA: `46db296cf10651b3242dd9ab07c18c78db3f5c7f`

## Objective
# Workbench v1.8.9 P0 model-branch Resume objective

## Objective

Close the remaining P0 workflow truth boundary at baseline
`46db296cf10651b3242dd9ab07c18c78db3f5c7f`: completed model branches must be
persisted and restored through one typed, server-bound output binding rather
than relying on payload/lineage fallback data. Resume must preserve the exact
child run, artifact/evidence/source identity and model family, and must not
create a duplicate child run for the same branch execution key.

## Required behavior

- A completed model step publishes
  `output_bindings["model_branches"]` as the canonical branch result.
- Each branch binding contains server-derived `run_ref`, artifact refs,
  evidence refs, source refs, family identity and the execution/idempotency
  key required to rebind the same child run.
- Resume and downstream consumers validate and read the canonical binding
  first. The existing payload/lineage branch shape may remain only as an
  explicitly bounded compatibility alias for legacy states.
- A state that claims model completion without the canonical binding or a
  migration-safe legacy shape fails closed with a typed migration/availability
  result; it must not silently normalize to an empty branch map.
- A child run created before workflow completion is resumed by the same
  branch-aware execution key and is not duplicated.
- Existing compiler receipt, EvidencePersistencePort admission/completion,
  artifact registry, path, digest, owner and authority checks remain intact.
- The runtime must use the existing state store and contracts; do not create a
  parallel persistence system or trust callback-provided raw mappings.

## Scope

Allowed product/test/document paths:

- `backend/workbench/agent/workflow.py`
- `backend/workbench/agent/workflow_runtime.py`
- `backend/workbench/contracts/workflow/state.py`
- `tests/test_workflow_runtime.py`
- `tests/test_workflow_resume.py`
- `tests/test_v189_resume_authority.py`
- `tests/test_v189_workflow_truth.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-model-branch-resume-objective.md`
- `docs/superpowers/plans/2026-08-20-model-branch-resume.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-model-branch-resume-handoff.md`

Protected paths include model estimator math, Survey engine, central consumer
cutover, unrelated Report migration, other worktrees, and release/merge/tag/
push machinery.

## Baseline, dependency, and gates

- Exact baseline: `46db296cf10651b3242dd9ab07c18c78db3f5c7f`.
- Dependency: `v1-8-9-p0-design-precheck-artifact`.
- Required checks: TDD RED before production edits, focused producer/consumer
  and resume tests, child idempotency probe, compileall, `git diff --check`,
  formal retrospective, and formal verify.
- Cross-process restart, multi-worker receipt consumption, browser/provider/
  host full gate, central Agent/Notebook/Report cutover, release, merge, tag,
  and push remain explicit follow-up gates unless independently proven.

## Completion target

The line is complete only when a real model workflow writes and restores the
canonical model-branch binding, old-state handling is explicitly fail-closed
or migration-required, and a child-run creation/completion interruption
resumes to the same server-bound child without duplication.

## Boundary
- Affected paths: `backend/workbench/agent/workflow_contracts.py`
- Allowed paths: `backend/workbench/agent/workflow_contracts.py`
- Protected paths: none
- Dependencies: `v1-8-9-p0-design-precheck-artifact`
- Tests: `tests/test_workflow_runtime.py`, `tests/test_workflow_resume.py`, `tests/test_v189_resume_authority.py`, `tests/test_v189_workflow_truth.py`
- Known gates: `cross-process restart and multi-worker receipt consumption remain NOT VERIFIED`, `central Agent/Notebook/Report, browser/provider/host/full-gate/release remain NOT VERIFIED`

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

### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-workflow-truth-remediation-3 (2026-08-16T15:26:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-3; final_state=COMPLETED; failure_lesson_keys=unsupported-formal-status-command, workflow-remediation-3-red-before-fix

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix

### v1-8-9-p0-workflow-truth-remediation-4 (2026-08-16T12:44:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-4; final_state=COMPLETED; failure_lesson_keys=test-selector-command-error, workflow-remediation-4-red-before-fix, workflow4-host-integration-dependency

### v1-8-9-p0-workflow-truth-remediation-2 (2026-08-16T11:10:20.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-2; final_state=COMPLETED; failure_lesson_keys=workflow-persistence-and-lineage-gap, workflow-remediation-red-before-fix

### v1-8-9-p0-workflow-truth-remediation (2026-08-16T10:36:38.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation; final_state=COMPLETED; failure_lesson_keys=admission-step-contract-binding, fd-persistence-separate-lane, focused-recompile-after-authority, reviewer-report-reference, workflow-truth-authority-boundary

### v1-8-9-p0-workflow-truth-core (2026-08-16T09:53:39.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-core; final_state=COMPLETED; failure_lesson_keys=retry-admission-reservation, shared-gates-not-verified, typed-output-persistence

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required
