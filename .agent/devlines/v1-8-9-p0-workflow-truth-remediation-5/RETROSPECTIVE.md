# Retrospective — v1-8-9-p0-workflow-truth-remediation-5

## Goal

# v1.8.9 P0 Workflow Truth Remediation 5 Objective  Close the remaining Workflow Truth trust and containment gaps found by the remediation-4 independent review. A caller-created workflow endpoint or directory FD must not be accepted as host authority. Completion must prove that every artifact is registered by the admitted target run and branch, not merely match caller-supplied metadata, hashes or a public registry row. All formal report/export writers must use the same admitted receipt and must validate the destination before writing so symlinks cannot cause an outside file to be created before failure.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-workflow-truth-remediation-5 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth  Required outcomes:  - workflow host/evidence authority is accepted only from the deployment-owned   supervisor boundary; caller-created path/FD/socket/config and self-authored   authority fail closed before any formal write; - completion verifies durable artifact provenance, exact run/branch ownership,   source model-run identity, expected output and digest against an admitted   server-side registry/receipt, rejecting foreign-run and forged same-run   registry/artifact cases; - public HTML/PDF/XLSX/report/export writers are receipt-gated before any IO;   destination directories and all parent components are checked before write,   and symlink/path replacement cannot leave outside artifacts behind; - existing receipt, post-estimation, restart, FD/inode and no-write behavior   remains intact; - production host resolver and Agent/Notebook cutover remain explicit   integration dependencies and are not claimed verified by local fixtures.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T17:20:00.000Z `tdd_red_workflow_remediation_5`; cause_status: `known`; cause: Remediation-4 direct probes reproduced caller-selected host endpoint admission, forged same-run and foreign-run artifact completion, receipt-less formal report/export writes, and symlinked report output escaping before failure.; resolution: `open`; lesson: Production host trust must come only from a deployment resolver; completion must consume a server-owned artifact admission registry; all formal writers must validate receipt and no-follow paths before IO.
- #3 2026-08-16T13:23:24.000Z `runtime_artifact_path_red`; cause_status: `known`; cause: The independent post-estimation symlink probe first reproduced a generic-path write outside the run before artifact registration rejected it.; resolution: `resolved`; lesson: All workflow-owned artifact producers must open and commit through the admitted no-follow parent FD before registry validation.

## All errors

- None recorded.

## All gaps

- #6 2026-08-16T13:32:00.000Z `production_host_integration_boundary`; cause_status: `external`; cause: The package has no deployment-owned supervisor resolver in this worktree, so production host authority cannot be verified here and the default issue path intentionally fails closed.; resolution: `accepted`; lesson: The next integration line must wire the supervisor-owned endpoint and then verify Agent/Notebook, provider, browser, full gate, and release separately.

## All waste

- None recorded.

## Root causes and solutions

- `production-host-integration-boundary`: occurrences=1; cause_status: `external`; root cause: The package has no deployment-owned supervisor resolver in this worktree, so production host authority cannot be verified here and the default issue path intentionally fails closed.; solution: `accepted`
- `runtime-artifact-no-follow`: occurrences=1; cause_status: `known`; root cause: The independent post-estimation symlink probe first reproduced a generic-path write outside the run before artifact registration rejected it.; solution: `resolved`
- `workflow-remediation-5-red-before-fix`: occurrences=1; cause_status: `known`; root cause: Remediation-4 direct probes reproduced caller-selected host endpoint admission, forged same-run and foreign-run artifact completion, receipt-less formal report/export writes, and symlinked report output escaping before failure.; solution: `open`

## Added tests

- `focused workflow truth suite; three adversarial rounds; compileall; diff-check`
- `tests/test_v189_workflow_truth.py::test_post_estimation_writer_rejects_a_symlink_parent_before_external_write`
- `tests/test_v189_workflow_truth.py; tests/test_reporting.py`
- `tests/test_v189_workflow_truth.py; tests/test_reporting.py; backend/workbench/agent/workflow_runtime.py`
- `tests/test_v189_workflow_truth.py; tests/test_reporting.py; focused workflow truth gate`

## New rules

- `production-host-integration-boundary`: line experience occurrence(s)=1
- `runtime-artifact-no-follow`: line experience occurrence(s)=1
- `workflow-remediation-5-red-before-fix`: line experience occurrence(s)=1

## Future guidance

- All workflow-owned artifact producers must open and commit through the admitted no-follow parent FD before registry validation.
- Keep package authority and deployment authority separate; prove every output with the admitted receipt and held filesystem identity.
- Production host trust must come only from a deployment resolver; completion must consume a server-owned artifact admission registry; all formal writers must validate receipt and no-follow paths before IO.
- The next integration line must wire the supervisor-owned endpoint and then verify Agent/Notebook, provider, browser, full gate, and release separately.

## Event index

- #1: `76bb3e62-3ff5-4908-b5e6-94651c8c6d8f` | 2026-08-16T12:53:46.686Z | STATE_CHANGE/line_started | incident=`96c4b60f-68e8-437f-9d62-27a9258bee49` | lesson_key=`frozen-context-before-start` | event_sha256=`a9b6fa5985665221b8f3d6c42bd0762f4fd6db8f85dc3c21d06c75d76d51522e`
- #2: `c2e4a6f8-0b1d-3f5a-7c9e-2b4d6f8a0c1e` | 2026-08-16T17:20:00.000Z | FAILURE/tdd_red_workflow_remediation_5 | incident=`d4f6a8c0-2e4b-6f8a-0c1e-3f5a7c9e2b4d` | lesson_key=`workflow-remediation-5-red-before-fix` | event_sha256=`005f0b54bc95411c1ebe248557922e80cc41a8f835cccae34fcff93401683c95`
- #3: `2c6e8a10-4d3f-4b5e-9c71-f3a5d7b9e1d4` | 2026-08-16T13:23:24.000Z | FAILURE/runtime_artifact_path_red | incident=`3f5a7c9e-2b4d-6f8a-0c1e-4b6d8f0a2c5e` | lesson_key=`runtime-artifact-no-follow` | event_sha256=`647fa2ce9346be9ba47b95304c025221b9649436bb483ce614fa1e51f9b8fa82`
- #4: `4d7f9b1c-3e5a-4c6d-8b0e-2f4a6d8c1e3b` | 2026-08-16T13:26:00.000Z | REVIEW/independent_security_self_review | incident=`5e7f9b1d-3a5c-7e9f-1b3d-5f7a9c2e4b6d` | lesson_key=`workflow-remediation-5-review` | event_sha256=`caa4ea259c66cb73846bd24f6a0c4d69656cf8f4c9d5ddb467d29f4043554f18`
- #5: `6a8c0e2f-4b6d-8f0a-2c5e-7a9d1b3f5c7e` | 2026-08-16T13:30:00.000Z | GATE/focused_adversarial_compile_diff_gate | incident=`7b9d1f3a-5c7e-9b1d-3f5a-7c9e2b4d6f8a` | lesson_key=`workflow-remediation-5-gate` | event_sha256=`f51f64a99f32c0aac8bcb8344ff128c1149a917beb1cb55d462941d19b8bff2b`
- #6: `8c0e2f4a-6d8f-0a2c-5e7a-9d1b3f5c7e9a` | 2026-08-16T13:32:00.000Z | GAP/production_host_integration_boundary | incident=`9d1b3f5c-7e9a-1b3d-5f7a-9c2e4b6d8f0a` | lesson_key=`production-host-integration-boundary` | event_sha256=`da6297c31ea3dd966a9e1c3153c5ff86b8edbdb510bcbaf9bbfda7431da2ea2f`
- #7: `0e2f4a6d-8f0a-2c5e-7a9d-1b3f5c7e9a1c` | 2026-08-16T13:35:00.000Z | STATE_CHANGE/package_local_completion | incident=`1f3a5c7e-9b1d-3f5a-7c9e-2b4d6f8a0c1e` | lesson_key=`workflow-remediation-5-package-complete` | event_sha256=`9bee14604bd661d075a209656321fc707617a4935a1c9048977f6ed80b5b368b`
