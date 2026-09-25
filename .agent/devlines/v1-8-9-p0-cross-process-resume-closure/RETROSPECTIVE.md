# Retrospective — v1-8-9-p0-cross-process-resume-closure

## Goal

# Workbench v1.8.9 P0 model-branch Resume objective  ## Objective  Close the remaining P0 workflow truth boundary at baseline \`46db296cf10651b3242dd9ab07c18c78db3f5c7f\`: completed model branches must be persisted and restored through one typed, server-bound output binding rather than relying on payload/lineage fallback data. Resume must preserve the exact child run, artifact/evidence/source identity and model family, and must not create a duplicate child run for the same branch execution key.  ## Required behavior  - A completed model step publishes   \`output_bindings["model_branches"]\` as the canonical branch result. - Each branch binding contains server-derived \`run_ref\`, artifact refs,   evidence refs, source refs, family identity and the execution/idempotency   key required to rebind the same child run. - Resume and downstream consumers validate and read the canonical binding   first. The existing payload/lineage branch shape may remain only as an   explicitly bounded compatibility alias for legacy states. - A state that claims model completion without the canonical binding or a   migration-safe legacy shape fails closed with a typed migration/availability   result; it must not silently normalize to an empty branch map. - A child run created before workflow completion is resumed by the same   branch-aware execution key and is not duplicated. - Existing compiler receipt, EvidencePersistencePort admission/completion,   artifact registry, path, digest, owner and authority checks remain intact. - The runtime must use the existing state store and contracts; do not create a   parallel persistence system or trust callback-provided raw mappings.  ## Scope  Allowed product/test/document paths:  - \`backend/workbench/agent/workflow.py\` - \`backend/workbench/agent/workflow_runtime.py\` - \`backend/workbench/contracts/workflow/state.py\` - \`tests/test_workflow_runtime.py\` - \`tests/test_workflow_resume.py\` - \`tests/test_v189_resume_authority.py\` - \`tests/test_v189_workflow_truth.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-model-branch-resume-objective.md\` - \`docs/superpowers/plans/2026-08-20-model-branch-resume.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-model-branch-resume-handoff.md\`  Protected paths include model estimator math, Survey engine, central consumer cutover, unrelated Report migration, other worktrees, and release/merge/tag/ push machinery.  ## Baseline, dependency, and gates  - Exact baseline: \`46db296cf10651b3242dd9ab07c18c78db3f5c7f\`. - Dependency: \`v1-8-9-p0-design-precheck-artifact\`. - Required checks: TDD RED before production edits, focused producer/consumer   and resume tests, child idempotency probe, compileall, \`git diff --check\`,   formal retrospective, and formal verify. - Cross-process restart, multi-worker receipt consumption, browser/provider/   host full gate, central Agent/Notebook/Report cutover, release, merge, tag,   and push remain explicit follow-up gates unless independently proven.  ## Completion target  The line is complete only when a real model workflow writes and restores the canonical model-branch binding, old-state handling is explicitly fail-closed or migration-required, and a child-run creation/completion interruption resumes to the same server-bound child without duplication.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/7 (14.3%; 14.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=764377 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T18:44:02.922Z `spawn_resume_authority_red`; cause_status: `known`; cause: A fresh spawned worker obtained the same admitted host directory FD and created a new port, but persisted completion validation rejected the original worker process owner instead of rebinding through a durable host authority identity.; resolution: `open`; lesson: Persisted workflow authority must bind to a server-owned durable host identity while receipt objects remain process-local.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `durable-resume-authority`: occurrences=1; cause_status: `known`; root cause: A fresh spawned worker obtained the same admitted host directory FD and created a new port, but persisted completion validation rejected the original worker process owner instead of rebinding through a durable host authority identity.; solution: `open`

## Added tests

- `tests/test_v189_resume_authority.py::test_spawn_worker_rebinds_completed_step_from_the_same_host_authority`

## New rules

- `durable-resume-authority`: line experience occurrence(s)=1

## Future guidance

- A green normal-path suite is insufficient for Resume authority; lifecycle side records, directory replacement, and BaseException boundaries must be adversarially probed before closure.
- Close a cross-process RED with direct fresh-worker evidence while retaining process-local object and receipt capabilities.
- Lifecycle side records and uncertain filesystem commits require the same durable authority and fail-closed validation as the primary completion record.
- Persisted workflow authority must bind to a server-owned durable host identity while receipt objects remain process-local.

## Event index

- #1: `a58892c7-d50e-4990-be4b-fa2fadb36326` | 2026-08-21T18:30:39.745Z | STATE_CHANGE/line_started | incident=`d79f249c-d680-4297-aea9-3247d67322a4` | lesson_key=`frozen-context-before-start` | event_sha256=`56a4bcdc6af776a760f8ff4be2c6b73c7893eb9bbebeff395a173a7a30dcd417`
- #2: `2dd17b2c-7e8e-4e51-9a70-9dd06b7ee8d1` | 2026-08-21T18:44:02.922Z | FAILURE/spawn_resume_authority_red | incident=`1a3b9c1d-65be-4f1a-a8f2-278b08f2e1c4` | lesson_key=`durable-resume-authority` | event_sha256=`b0cb23a31524fd8c3f1e792b3a7eff77d14245b6a2ef4f01015f5edcbdbe02fe`
- #3: `3ae1c6d4-8f52-4b70-9c13-5d7e2a4f6b81` | 2026-08-21T18:56:47.299Z | REVIEW/spawn_resume_authority_green | incident=`1a3b9c1d-65be-4f1a-a8f2-278b08f2e1c4` | lesson_key=`durable-resume-authority` | event_sha256=`eda0566c347ac3cd82bda5b81f29c5ed7b84e6829182020bd1f5c15b98dfe980`
- #4: `b4b2b8a6-1d5a-4ee8-bf6d-cd6bb4e1bd40` | 2026-08-21T20:16:48.951Z | REVIEW/p0_a_security_review_red | incident=`e7b78ba0-6e07-45da-9757-d9f982da1d86` | lesson_key=`p0-resume-adversarial-lifecycle-boundary` | event_sha256=`e58cf22db29b844c082a6d3658fa3441b94505f695cfabe77d2e15adb15b6567`
- #5: `9e25ef8d-4e19-4e5d-9db1-27df6b4b5d92` | 2026-08-21T20:40:16.172Z | REVIEW/p0_a_security_review_green | incident=`e7b78ba0-6e07-45da-9757-d9f982da1d86` | lesson_key=`p0-resume-adversarial-lifecycle-boundary` | event_sha256=`39b3246d83d636af4e76f42801703ed6268869c960c6bd790f4bb07739ca6fb6`
- #6: `d9f8e7c6-b5a4-4321-9fed-c8b7a6d5e4f3` | 2026-08-21T20:41:10.823Z | GATE/p0_a_matrix_green | incident=`e7b78ba0-6e07-45da-9757-d9f982da1d86` | lesson_key=`p0-a-gate-evidence` | event_sha256=`c5c593d2b492f5d14bf92e95a57756dbdd2258d3baaadb4aedfd7dc99d5ff5d8`
- #7: `a1b2c3d4-e5f6-4789-9012-3a4b5c6d7e8f` | 2026-08-21T20:42:16.435Z | STATE_CHANGE/p0_a_completed | incident=`e7b78ba0-6e07-45da-9757-d9f982da1d86` | lesson_key=`p0-formal-closeout-boundary` | event_sha256=`a52f8fadf8ddf2933fc96deb3f89576f8880da8377fda6345566b08bc3ea5b55`
