# Retrospective — v1-8-9-p0-workflow-result-admission-runtime

## Goal

# v1.8.9 P0 — workflow result admission runtime  Make every dataset-producing workflow step bind its persisted result artifacts to the active server-owned workflow receipt before the executor accepts the typed result. Preserve fail-closed path, digest, producer, and target-run checks; do not weaken the artifact registry boundary or bypass the receipt.  The regression is a real multi-step data-operation execution: \`data.rename\` writes and indexes its output, but \`admit_result_artifacts()\` cannot find a receipt-bound server admission for that output.  Acceptance: the minimal real persisted-child workflow completes with both output artifacts receipt-bound; tampering, missing registration, and wrong producer remain rejected; the scoped suite and compile/diff checks pass. Browser, real Provider, external host resolver, and release gates remain explicit known gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/7 (57.1%; 57.1 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #2 2026-08-21T06:46:35.718Z `formal_event_schema_probe`; cause_status: `known`; cause: The first formal red-event draft omitted the required schema_version field and the devline CLI rejected it before appending.; resolution: `resolved`; lesson: Validate the complete formal event envelope before treating a CLI append attempt as recorded.
- #3 2026-08-21T06:46:53.850Z `stale_pycache_collection_probe`; cause_status: `known`; cause: The prescribed red command loaded stale worktree bytecode and stopped during collection because the current dirty branch source exports MICE_IMPUTATION_METHOD while the cached module did not.; resolution: `resolved`; lesson: Use an isolated bytecode cache when a dirty multi-worktree environment can retain stale compiled modules.
- #4 2026-08-21T06:52:03.855Z `workflow_result_admission_red`; cause_status: `known`; cause: A real data.rename workflow persisted and indexed its dataset and recipe artifacts, but the adapter returned them without binding either artifact to the active server-owned workflow receipt, so admit_result_artifacts rejected the typed result.; resolution: `accepted`; lesson: Every persisted dataset producer must freeze each indexed output through the active server receipt before returning its typed result.

## All gaps

- #5 2026-08-21T06:55:15.573Z `model_branch_followup_gap`; cause_status: `known`; cause: The supplemental pre-existing data.rename to model.genesis integration probe reached the preserved target-run fail-closed check and rejected a foreign model branch binding; this model-branch boundary is outside the two owned paths and was not changed.; resolution: `accepted`; lesson: Keep supplemental model-branch target-run failures separate from the bounded data-result admission repair.

## All waste

- None recorded.

## Root causes and solutions

- `formal-event-envelope-probe`: occurrences=1; cause_status: `known`; root cause: The first formal red-event draft omitted the required schema_version field and the devline CLI rejected it before appending.; solution: `resolved`
- `isolated-pycache-red-probe`: occurrences=1; cause_status: `known`; root cause: The prescribed red command loaded stale worktree bytecode and stopped during collection because the current dirty branch source exports MICE_IMPUTATION_METHOD while the cached module did not.; solution: `resolved`
- `model-branch-followup-gap`: occurrences=1; cause_status: `known`; root cause: The supplemental pre-existing data.rename to model.genesis integration probe reached the preserved target-run fail-closed check and rejected a foreign model branch binding; this model-branch boundary is outside the two owned paths and was not changed.; solution: `accepted`
- `workflow-result-admission-red`: occurrences=1; cause_status: `known`; root cause: A real data.rename workflow persisted and indexed its dataset and recipe artifacts, but the adapter returned them without binding either artifact to the active server-owned workflow receipt, so admit_result_artifacts rejected the typed result.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `formal-event-envelope-probe`: line experience occurrence(s)=1
- `isolated-pycache-red-probe`: line experience occurrence(s)=1
- `model-branch-followup-gap`: line experience occurrence(s)=1
- `workflow-result-admission-red`: line experience occurrence(s)=1

## Future guidance

- Every persisted dataset producer must freeze each indexed output through the active server receipt before returning its typed result.
- Keep supplemental model-branch target-run failures separate from the bounded data-result admission repair.
- Use an isolated bytecode cache when a dirty multi-worktree environment can retain stale compiled modules.
- Validate the complete formal event envelope before treating a CLI append attempt as recorded.

## Event index

- #1: `b89640d4-2e8a-49e1-8bef-b4c42d8fbb19` | 2026-08-21T06:31:52.982Z | STATE_CHANGE/line_started | incident=`c7bb4011-f971-417c-8c71-a3f6e2536f58` | lesson_key=`frozen-context-before-start` | event_sha256=`afca105e974384d8bf71eb5f00bfe42211b3a7334f5dbb4d8d33fed7b68893e3`
- #2: `0c0d4d8a-c8e6-4ab5-9a6d-8a4a9b6c7d11` | 2026-08-21T06:46:35.718Z | ERROR/formal_event_schema_probe | incident=`1d2e3f40-5a6b-4c7d-8e9f-0a1b2c3d4e51` | lesson_key=`formal-event-envelope-probe` | event_sha256=`37392a65e7030c4fcd3950882d63cdfa89187ad3dbe537ac06dc3de6ebf43add`
- #3: `0c0d4d8a-c8e6-4ab5-9a6d-8a4a9b6c7d12` | 2026-08-21T06:46:53.850Z | ERROR/stale_pycache_collection_probe | incident=`1d2e3f40-5a6b-4c7d-8e9f-0a1b2c3d4e50` | lesson_key=`isolated-pycache-red-probe` | event_sha256=`b922e93f5b125beb79a459804e8e829d37f6cbe701ecb7721a6e30a07520de43`
- #4: `0c0d4d8a-c8e6-4ab5-9a6d-8a4a9b6c7d13` | 2026-08-21T06:52:03.855Z | ERROR/workflow_result_admission_red | incident=`1d2e3f40-5a6b-4c7d-8e9f-0a1b2c3d4e52` | lesson_key=`workflow-result-admission-red` | event_sha256=`fcb7c8be816748c1ccc9e293a7514ffbcebd9e846d88bd50377228ea390267a4`
- #5: `0c0d4d8a-c8e6-4ab5-9a6d-8a4a9b6c7d14` | 2026-08-21T06:55:15.573Z | GAP/model_branch_followup_gap | incident=`1d2e3f40-5a6b-4c7d-8e9f-0a1b2c3d4e53` | lesson_key=`model-branch-followup-gap` | event_sha256=`edf90ece188078045412c2bede25d17a3ed4531b46be684a5381c69a9c01bd2f`
- #6: `0c0d4d8a-c8e6-4ab5-9a6d-8a4a9b6c7d15` | 2026-08-21T06:56:48.082Z | GATE/workflow_result_admission_green | incident=`1d2e3f40-5a6b-4c7d-8e9f-0a1b2c3d4e54` | lesson_key=`workflow-result-admission-green` | event_sha256=`e1bb798c56758b0ccae7d84443638097c8c93e5e9cdd3e0adf76caf1c9a1d3b1`
- #7: `0c0d4d8a-c8e6-4ab5-9a6d-8a4a9b6c7d16` | 2026-08-21T06:57:21.922Z | STATE_CHANGE/workflow_result_admission_completed | incident=`1d2e3f40-5a6b-4c7d-8e9f-0a1b2c3d4e55` | lesson_key=`workflow-result-admission-completed` | event_sha256=`d90a4272360e44558537890192a32dc2fa6479906d782cc4956d6166debfc65b`
