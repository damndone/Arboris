# Retrospective — v1-8-9-p1-transform-model-integration

## Goal

# Workbench v1.8.9 P1 Transform-to-Model Integration  Close the real persisted-child workflow failure where a typed data transform is followed by model genesis. Keep receipt-bound artifact admission and source-content binding fail-closed; do not bypass the server registry or fall back to the target dataset.  Scope: backend/workbench/agent/workflow_runtime.py, tests/test_agent_data_management_p4.py.  Acceptance: the real transform-to-model path completes with the renamed child as the model source; tampered/missing/foreign result artifacts remain rejected; focused regression and formal verification pass.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/7 (57.1%; 57.1 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-21T07:12:13.795Z `transform_model_genesis_red`; cause_status: `known`; cause: The real persisted-child transform-to-model regression completed the renamed transform step but model genesis was rejected at result artifact admission with WORKFLOW_TARGET_RUN_MISMATCH because the foreign child model branch was compared to the original target artifact instead of the typed upstream source.; resolution: `open`; lesson: Typed model source admission must validate the upstream produced binding against server-owned producer provenance, not assume every model source is the workflow target artifact.
- #4 2026-08-21T07:17:07.441Z `canonical_model_source_red`; cause_status: `known`; cause: After the first admission guard was corrected, canonical model completion still rejected the valid child source because its source_refs validator independently required the original target artifact.; resolution: `resolved`; lesson: Search every completion and resume validator for the same target-artifact assumption after changing a typed source admission rule.

## All errors

- #2 2026-08-21T07:12:13.676Z `formal_cli_wrong_worktree_import`; cause_status: `known`; cause: The first formal append help invocation imported the linked workbench-v1.8.6 source instead of this worktree and failed before dispatch because the target development-control API was unavailable; the command was corrected with the target backend on PYTHONPATH.; resolution: `resolved`; lesson: Run formal control commands with the target worktree backend explicitly first when linked worktrees share a virtual environment.
- #7 2026-08-21T07:22:27.631Z `git_index_lock_permission`; cause_status: `external`; cause: The first explicit git add was blocked by the shared worktree index lock permission; the same exact allowlisted paths were staged successfully after explicit elevated authorization.; resolution: `resolved`; lesson: In a shared worktree, stage only explicit task paths and request elevated Git metadata access when the index lock is outside the writable source boundary.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `canonical-child-source-validator`: occurrences=1; cause_status: `known`; root cause: After the first admission guard was corrected, canonical model completion still rejected the valid child source because its source_refs validator independently required the original target artifact.; solution: `resolved`
- `formal-cli-target-worktree-import`: occurrences=1; cause_status: `known`; root cause: The first formal append help invocation imported the linked workbench-v1.8.6 source instead of this worktree and failed before dispatch because the target development-control API was unavailable; the command was corrected with the target backend on PYTHONPATH.; solution: `resolved`
- `shared-worktree-index-lock`: occurrences=1; cause_status: `external`; root cause: The first explicit git add was blocked by the shared worktree index lock permission; the same exact allowlisted paths were staged successfully after explicit elevated authorization.; solution: `resolved`
- `typed-child-source-admission-red`: occurrences=1; cause_status: `known`; root cause: The real persisted-child transform-to-model regression completed the renamed transform step but model genesis was rejected at result artifact admission with WORKFLOW_TARGET_RUN_MISMATCH because the foreign child model branch was compared to the original target artifact instead of the typed upstream source.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `canonical-child-source-validator`: line experience occurrence(s)=1
- `formal-cli-target-worktree-import`: line experience occurrence(s)=1
- `shared-worktree-index-lock`: line experience occurrence(s)=1
- `typed-child-source-admission-red`: line experience occurrence(s)=1

## Future guidance

- In a shared worktree, stage only explicit task paths and request elevated Git metadata access when the index lock is outside the writable source boundary.
- Run formal control commands with the target worktree backend explicitly first when linked worktrees share a virtual environment.
- Search every completion and resume validator for the same target-artifact assumption after changing a typed source admission rule.
- Typed model source admission must validate the upstream produced binding against server-owned producer provenance, not assume every model source is the workflow target artifact.

## Event index

- #1: `e6ea5052-90b8-4dfc-a530-64aa13af5189` | 2026-08-21T07:06:47.591Z | STATE_CHANGE/line_started | incident=`e2d83f55-c06f-46af-b127-6b1450a4c9ae` | lesson_key=`frozen-context-before-start` | event_sha256=`c06130a9aabeaa15b96ddd4a3c06705fd4e82729db6d1033f0789316006d4590`
- #2: `c4e7a1d9-5b2f-4a86-9c30-7e1b3d5f8a24` | 2026-08-21T07:12:13.676Z | ERROR/formal_cli_wrong_worktree_import | incident=`d8f2b6c4-0a1e-4d79-8b35-6f2c9e7a1d53` | lesson_key=`formal-cli-target-worktree-import` | event_sha256=`9b2ffacaa2f56b24e4722d5a8da6de6f060634aa26a08017acd6fd3669aa3360`
- #3: `a2f1c9e4-6b7d-4e80-9a31-5c2d7f8b0e64` | 2026-08-21T07:12:13.795Z | FAILURE/transform_model_genesis_red | incident=`f9c3a1e7-2b4d-4f68-8c0a-5e7b9d1f3a26` | lesson_key=`typed-child-source-admission-red` | event_sha256=`bc835f6c44f74813f26ac28081b06ed104a96b048f52e121ab787303c825dfd8`
- #4: `e7b2c4d9-1f36-4a80-9e25-6c8d0b3f5a17` | 2026-08-21T07:17:07.441Z | FAILURE/canonical_model_source_red | incident=`b6d0f2a8-4c1e-497b-8d35-7f9a2c6e0b14` | lesson_key=`canonical-child-source-validator` | event_sha256=`7d73e3d9ac1d71a9eb6f91b8f07b51f7a27f90319a1f3a12ba2d7932cdd57006`
- #5: `f1a3c5e7-9b2d-4f68-8a10-3c6e7b9d2f45` | 2026-08-21T07:19:43.548Z | GATE/transform_model_admission_gate | incident=`a8c4e2f6-0b1d-4379-9e52-6f3a7d1c5b80` | lesson_key=`child-source-provenance-gate` | event_sha256=`f964c6893996e8001c8a9cb8842aa7c0b485406bc02e4adab4b955f2e31ecdc4`
- #6: `b4d8f2a6-0c1e-4379-9a52-6f3c7e1d5b80` | 2026-08-21T07:20:05.624Z | STATE_CHANGE/line_completed | incident=`c9e5a1d7-2b4f-4680-8c31-5e7a9d3f0b26` | lesson_key=`formal-closeout-after-real-integration` | event_sha256=`a42ad1ef3003b04891fe44ea1525abdd0686e306c45b419918318b9531cd9dae`
- #7: `d2f6a8c0-4e1b-4379-9c52-7a3d5f8b0e16` | 2026-08-21T07:22:27.631Z | ERROR/git_index_lock_permission | incident=`e8c4a2f6-0b1d-4379-9e52-6f3a7c1d5b80` | lesson_key=`shared-worktree-index-lock` | event_sha256=`016a33b5b23bbacdb54cec9b5ed9a58a97826a03d50f49fa0e71ff33108cd1a6`
