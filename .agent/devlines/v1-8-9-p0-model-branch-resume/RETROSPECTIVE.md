# Retrospective — v1-8-9-p0-model-branch-resume

## Goal

# Workbench v1.8.9 P0 model-branch Resume objective  ## Objective  Close the remaining P0 workflow truth boundary at baseline \`46db296cf10651b3242dd9ab07c18c78db3f5c7f\`: completed model branches must be persisted and restored through one typed, server-bound output binding rather than relying on payload/lineage fallback data. Resume must preserve the exact child run, artifact/evidence/source identity and model family, and must not create a duplicate child run for the same branch execution key.  ## Required behavior  - A completed model step publishes   \`output_bindings["model_branches"]\` as the canonical branch result. - Each branch binding contains server-derived \`run_ref\`, artifact refs,   evidence refs, source refs, family identity and the execution/idempotency   key required to rebind the same child run. - Resume and downstream consumers validate and read the canonical binding   first. The existing payload/lineage branch shape may remain only as an   explicitly bounded compatibility alias for legacy states. - A state that claims model completion without the canonical binding or a   migration-safe legacy shape fails closed with a typed migration/availability   result; it must not silently normalize to an empty branch map. - A child run created before workflow completion is resumed by the same   branch-aware execution key and is not duplicated. - Existing compiler receipt, EvidencePersistencePort admission/completion,   artifact registry, path, digest, owner and authority checks remain intact. - The runtime must use the existing state store and contracts; do not create a   parallel persistence system or trust callback-provided raw mappings.  ## Scope  Allowed product/test/document paths:  - \`backend/workbench/agent/workflow.py\` - \`backend/workbench/agent/workflow_runtime.py\` - \`backend/workbench/contracts/workflow/state.py\` - \`tests/test_workflow_runtime.py\` - \`tests/test_workflow_resume.py\` - \`tests/test_v189_resume_authority.py\` - \`tests/test_v189_workflow_truth.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-model-branch-resume-objective.md\` - \`docs/superpowers/plans/2026-08-20-model-branch-resume.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-model-branch-resume-handoff.md\`  Protected paths include model estimator math, Survey engine, central consumer cutover, unrelated Report migration, other worktrees, and release/merge/tag/ push machinery.  ## Baseline, dependency, and gates  - Exact baseline: \`46db296cf10651b3242dd9ab07c18c78db3f5c7f\`. - Dependency: \`v1-8-9-p0-design-precheck-artifact\`. - Required checks: TDD RED before production edits, focused producer/consumer   and resume tests, child idempotency probe, compileall, \`git diff --check\`,   formal retrospective, and formal verify. - Cross-process restart, multi-worker receipt consumption, browser/provider/   host full gate, central Agent/Notebook/Report cutover, release, merge, tag,   and push remain explicit follow-up gates unless independently proven.  ## Completion target  The line is complete only when a real model workflow writes and restores the canonical model-branch binding, old-state handling is explicitly fail-closed or migration-required, and a child-run creation/completion interruption resumes to the same server-bound child without duplication.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/16 (31.2%; 31.2 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=5; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T08:46:12.215Z `model_branch_canonical_binding_tdd_red`; cause_status: `known`; cause: The real model-genesis producer publishes only payload/lineage branches, and the dependent consumer reads those legacy aliases before the typed model_branches output binding.; resolution: `open`; lesson: Model branch state needs one canonical typed binding; compatibility aliases must not outrank the server-bound output.
- #5 2026-08-20T09:30:56.765Z `model_branch_post_review_red_probes`; cause_status: `known`; cause: The post-review TDD probes first failed because model.auto discarded the canonical model_branches binding and completion accepted a forged evidence_refs list; the focused runtime file also exposed the missing WorkflowExecutor import in the active diff.; resolution: `resolved`; lesson: Run focused red probes for selector wrappers and completion-time identity before relying on the broader Resume suite.
- #10 2026-08-20T10:37:28.156Z `contract_collision_guard`; cause_status: `known`; cause: The first contract collision guard treated existing declared capability overlays as unexpected and blocked module import.; resolution: `resolved`; lesson: Contract collision guards must distinguish intentional overlays from accidental identity replacement and fail closed on the latter.
- #11 2026-08-20T10:37:48.671Z `completion_semantic_default`; cause_status: `known`; cause: Completion-time branch semantic validation initially required an explicit covariance even though existing Genesis model families intentionally default omitted covariance to unadjusted.; resolution: `resolved`; lesson: New authority checks must reuse the execution path's declared defaults instead of introducing a stricter parallel semantic rule.

## All errors

- #9 2026-08-20T10:37:05.491Z `model_auto_admission_boundary`; cause_status: `known`; cause: The first real model.auto selector execution exposed a mismatch between the original admitted selector step and the resolved execution step.; resolution: `resolved`; lesson: Variant-resolved execution must retain the exact admitted step as the authority boundary.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `completion-validation-shares-defaults`: occurrences=1; cause_status: `known`; root cause: Completion-time branch semantic validation initially required an explicit covariance even though existing Genesis model families intentionally default omitted covariance to unadjusted.; solution: `resolved`
- `contract-collision-overlay-allowlist`: occurrences=1; cause_status: `known`; root cause: The first contract collision guard treated existing declared capability overlays as unexpected and blocked module import.; solution: `resolved`
- `model-auto-admission-resolution`: occurrences=1; cause_status: `known`; root cause: The first real model.auto selector execution exposed a mismatch between the original admitted selector step and the resolved execution step.; solution: `resolved`
- `model-branch-canonical-binding-red`: occurrences=1; cause_status: `known`; root cause: The real model-genesis producer publishes only payload/lineage branches, and the dependent consumer reads those legacy aliases before the typed model_branches output binding.; solution: `open`
- `post-review-red-probes-before-close`: occurrences=1; cause_status: `known`; root cause: The post-review TDD probes first failed because model.auto discarded the canonical model_branches binding and completion accepted a forged evidence_refs list; the focused runtime file also exposed the missing WorkflowExecutor import in the active diff.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `completion-validation-shares-defaults`: line experience occurrence(s)=1
- `contract-collision-overlay-allowlist`: line experience occurrence(s)=1
- `model-auto-admission-resolution`: line experience occurrence(s)=1
- `model-branch-canonical-binding-red`: line experience occurrence(s)=1
- `post-review-red-probes-before-close`: line experience occurrence(s)=1

## Future guidance

- A green producer/consumer probe is insufficient for Resume; prove interruption recovery and preserve unrelated generic state semantics before closing a model-specific line.
- Close each RED incident by linking the green implementation and direct regression evidence to the same incident identity.
- Contract collision guards must distinguish intentional overlays from accidental identity replacement and fail closed on the latter.
- Every persisted artifact that participates in Resume authority must use one held no-follow read boundary for all derived checks.
- Keep an independent review after each security-boundary repair and record the exact remaining verification scope.
- Model branch state needs one canonical typed binding; compatibility aliases must not outrank the server-bound output.
- New authority checks must reuse the execution path's declared defaults instead of introducing a stricter parallel semantic rule.
- Review every model producer subtype and every persisted/live result transition, then separate local proof from cross-process recovery evidence.
- Review the entire typed-output lifecycle from producer through completion and Resume, including selector wrappers and compatibility paths.
- Run focused red probes for selector wrappers and completion-time identity before relying on the broader Resume suite.
- Variant-resolved execution must retain the exact admitted step as the authority boundary.

## Event index

- #1: `e1192821-ec17-4574-b155-9f53729e783d` | 2026-08-20T08:43:17.477Z | STATE_CHANGE/line_started | incident=`974cf345-8f88-4f41-b32b-c25ec11907db` | lesson_key=`frozen-context-before-start` | event_sha256=`0f73ca1af2b5c7c0d4408f014fa71349fd10db92228f890d5d04b4b29ed5c2a4`
- #2: `b7e2c5a1-4d90-48f3-9b6e-2a7c5d1e804f` | 2026-08-20T08:46:12.215Z | FAILURE/model_branch_canonical_binding_tdd_red | incident=`d1a6f4c8-2b7e-49e0-8c5d-3a9f6b1e7042` | lesson_key=`model-branch-canonical-binding-red` | event_sha256=`9aff95ff0ae2171c73cae7f142c26c779d5df002b4564fbaecdb4a672858443e`
- #3: `c8f1a4e6-2b73-49d0-95a8-7e3c1d6f204b` | 2026-08-20T09:06:58.445Z | REVIEW/model_branch_resume_spec_review_not_ready | incident=`f4b2d8a6-1c73-49e0-85d2-6a7c3e1b9045` | lesson_key=`model-branch-resume-review-not-ready` | event_sha256=`b0740b79fbb5fcfde488a9c6ae5c00e865f8e0b9942b0139632e53908f629ba4`
- #4: `6f9b7d2e-4c11-4b8a-9f25-6d3e1c7a8042` | 2026-08-20T09:28:11.494Z | REVIEW/model_branch_resume_second_pass_not_ready | incident=`2a6e8c41-7f53-4d90-b1c8-5e2a9f704316` | lesson_key=`review-full-typed-output-lifecycle` | event_sha256=`c58735b9ed55897fd1fc6da2c80e30e45e8986c1f4433448d63c7e50d44c9f4b`
- #5: `8d2f6a41-9b73-4e05-a8c1-7f2d9e604315` | 2026-08-20T09:30:56.765Z | FAILURE/model_branch_post_review_red_probes | incident=`4c7e1a93-5f20-4b86-a2d9-6e3c8f704152` | lesson_key=`post-review-red-probes-before-close` | event_sha256=`359003997a3774d115dbd2a030bbab7e4d443e14a284f124cf2e6af0fde6f570`
- #6: `1e7c4a92-6d35-4f80-b1a9-5e2d8c704316` | 2026-08-20T09:43:18.412Z | REVIEW/model_branch_resume_spec_compliance_second_review | incident=`7b3e1f64-9a20-4d85-b6c1-2e7f904315a8` | lesson_key=`model-producer-and-recovery-boundaries` | event_sha256=`b81abf002926f89061c166541db0f7c12d7de642818796e262e83cc38136ac2b`
- #7: `775691d6-dc34-4012-9b74-c009adfb999d` | 2026-08-20T09:59:45.832Z | STATE_CHANGE/context_rescope_required | incident=`adc0e758-f716-4773-8180-fba21259d626` | lesson_key=`context-pack-rescope` | event_sha256=`7099447c544586400938e83a17f7c8b28ac32b032bef5bffa645e5b852a460ca`
- #8: `17998f35-9a8c-42d7-8189-25452a025af3` | 2026-08-20T09:59:45.838Z | STATE_CHANGE/context_rescoped | incident=`100310ff-45a1-4cab-a831-1b19d23fb909` | lesson_key=`context-pack-rescope` | event_sha256=`ef7e52f0befd21f56970f43061751af0f099781ac9e2647cd9a8bc159b56f268`
- #9: `b7a4b1d5-9d48-4a88-83c8-11e8b9c2a601` | 2026-08-20T10:37:05.491Z | ERROR/model_auto_admission_boundary | incident=`a15b9e24-bc5a-4d8e-9f01-7c6a3b2e5d48` | lesson_key=`model-auto-admission-resolution` | event_sha256=`5c2b76621429f70718bf1d0a4aa0d71216aa8834e41146dc190cb23149cb31d9`
- #10: `c8d3e2f1-6a54-4b97-90e1-2f7a8c5d3b46` | 2026-08-20T10:37:28.156Z | FAILURE/contract_collision_guard | incident=`d26f1a9b-4c83-5e70-9a12-7b6d3f8e5c04` | lesson_key=`contract-collision-overlay-allowlist` | event_sha256=`b376f8780b73c14932e5b913e77b8d4fe9d99141a7ea0dab46ff3f934fe01e6b`
- #11: `d9e4f3a2-7b65-4c08-91f2-3a8d6e5b4c17` | 2026-08-20T10:37:48.671Z | FAILURE/completion_semantic_default | incident=`e37a2b91-5c84-6d70-9f12-8b4e3a7c5d06` | lesson_key=`completion-validation-shares-defaults` | event_sha256=`a80711f948fcaf7a835b0e6dc8ff040cfffb0797528032e4a40fa7b1f50b4fdd`
- #12: `e4f1a2b3-8c65-4d97-90e1-5b7a3c6d2f48` | 2026-08-20T10:45:38.998Z | REVIEW/model_artifact_path_race | incident=`f5a2b3c4-9d76-4e08-91f2-6a8c3b7d5e10` | lesson_key=`model-artifact-fd-read-review` | event_sha256=`708458ea1299471a9e16e518617ae535b599cc78e889c2e88221629368a2dfa0`
- #13: `f6b2c3d4-0e87-4a19-92f3-7b5d8c6e1a20` | 2026-08-20T10:45:54.962Z | REVIEW/model_branch_resume_ready | incident=`a7c3d4e5-1f98-4b20-83f4-6d8a2c5e7b10` | lesson_key=`resume-security-review-ready` | event_sha256=`60dfd0d523a13b7fcfabd0e3cc483fda596d5234f38e4951b405da2c763baab1`
- #14: `a8c4d5e6-2f19-4b30-87a5-6d3e9c1b7f20` | 2026-08-20T10:48:04.597Z | GATE/model_branch_resume_local_gate | incident=`b9d5e6f7-3a20-4c41-98b6-7e4d1a2c8f30` | lesson_key=`scoped-resume-local-gate` | event_sha256=`affaa16c5165ddecd13bfbd632d5d9b5ec25858dfb631852dee738669863b475`
- #15: `c0e6f7a8-4b31-5d52-9a17-8c4e2b6f0d93` | 2026-08-20T10:48:22.378Z | STATE_CHANGE/line_completed | incident=`d1f7a8b9-5c42-6e63-0b28-9d5f3a7c1e04` | lesson_key=`close-resume-line-with-boundaries` | event_sha256=`c2f896fd0cb308fd61f56a15ddeccea9c077306888e3c1d77add7801d8713583`
- #16: `d2f8a9b0-6c43-7e74-1a39-0b5d4c8e2f16` | 2026-08-20T10:48:55.189Z | REVIEW/model_branch_canonical_binding_resolved | incident=`d1a6f4c8-2b7e-49e0-8c5d-3a9f6b1e7042` | lesson_key=`resolve-model-branch-canonical-red` | event_sha256=`7c3c3dc9b51c12fd8ef400b5119647e4e8e1349451ffe7d0398a8951d26ec1b3`
