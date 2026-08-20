# Retrospective — v1-8-9-p0-model-branch-resume

## Goal

# Workbench v1.8.9 P0 model-branch Resume objective  ## Objective  Close the remaining P0 workflow truth boundary at baseline \`46db296cf10651b3242dd9ab07c18c78db3f5c7f\`: completed model branches must be persisted and restored through one typed, server-bound output binding rather than relying on payload/lineage fallback data. Resume must preserve the exact child run, artifact/evidence/source identity and model family, and must not create a duplicate child run for the same branch execution key.  ## Required behavior  - A completed model step publishes   \`output_bindings["model_branches"]\` as the canonical branch result. - Each branch binding contains server-derived \`run_ref\`, artifact refs,   evidence refs, source refs, family identity and the execution/idempotency   key required to rebind the same child run. - Resume and downstream consumers validate and read the canonical binding   first. The existing payload/lineage branch shape may remain only as an   explicitly bounded compatibility alias for legacy states. - A state that claims model completion without the canonical binding or a   migration-safe legacy shape fails closed with a typed migration/availability   result; it must not silently normalize to an empty branch map. - A child run created before workflow completion is resumed by the same   branch-aware execution key and is not duplicated. - Existing compiler receipt, EvidencePersistencePort admission/completion,   artifact registry, path, digest, owner and authority checks remain intact. - The runtime must use the existing state store and contracts; do not create a   parallel persistence system or trust callback-provided raw mappings.  ## Scope  Allowed product/test/document paths:  - \`backend/workbench/agent/workflow.py\` - \`backend/workbench/agent/workflow_runtime.py\` - \`backend/workbench/contracts/workflow/state.py\` - \`tests/test_workflow_runtime.py\` - \`tests/test_workflow_resume.py\` - \`tests/test_v189_resume_authority.py\` - \`tests/test_v189_workflow_truth.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-model-branch-resume-objective.md\` - \`docs/superpowers/plans/2026-08-20-model-branch-resume.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-model-branch-resume-handoff.md\`  Protected paths include model estimator math, Survey engine, central consumer cutover, unrelated Report migration, other worktrees, and release/merge/tag/ push machinery.  ## Baseline, dependency, and gates  - Exact baseline: \`46db296cf10651b3242dd9ab07c18c78db3f5c7f\`. - Dependency: \`v1-8-9-p0-design-precheck-artifact\`. - Required checks: TDD RED before production edits, focused producer/consumer   and resume tests, child idempotency probe, compileall, \`git diff --check\`,   formal retrospective, and formal verify. - Cross-process restart, multi-worker receipt consumption, browser/provider/   host full gate, central Agent/Notebook/Report cutover, release, merge, tag,   and push remain explicit follow-up gates unless independently proven.  ## Completion target  The line is complete only when a real model workflow writes and restores the canonical model-branch binding, old-state handling is explicitly fail-closed or migration-required, and a child-run creation/completion interruption resumes to the same server-bound child without duplication.

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `e1192821-ec17-4574-b155-9f53729e783d` | 2026-08-20T08:43:17.477Z | STATE_CHANGE/line_started | incident=`974cf345-8f88-4f41-b32b-c25ec11907db` | lesson_key=`frozen-context-before-start` | event_sha256=`0f73ca1af2b5c7c0d4408f014fa71349fd10db92228f890d5d04b4b29ed5c2a4`
