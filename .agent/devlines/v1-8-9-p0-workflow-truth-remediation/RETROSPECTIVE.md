# Retrospective — v1-8-9-p0-workflow-truth-remediation

## Goal

# v1.8.9 P0 Workflow Truth Remediation Objective  Remediate the independently verified P0 authority failures in the existing P0 Workflow Truth implementation before any integration admission. The server must issue and verify non-forgeable admission authority, bind completion to the full persisted request and active non-aborted state, make admission reservation atomic, and require a server-owned EvidencePersistencePort receipt before side effects. Preserve typed output/legacy compatibility, family-aware post-estimation, Graph lineage and resume. Do not modify protected paths or claim integration/release evidence.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-workflow-truth-remediation Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth  Required outcomes: adversarial forged target/changed contract/cross-scope/aborted completion/concurrent admission/fake evidence-port probes fail before side effects; source commitments include digest; focused tests and formal evidence reflect the fixes.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/9 (55.6%; 55.6 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T11:30:00.000Z `tdd_red_workflow_truth`; cause_status: `known`; cause: Adversarial workflow truth tests reproduced public compiler hash forgery, non-atomic duplicate admission, forged completion fields, aborted completion, fake evidence ports, missing source digest, and unpersisted model identity.; resolution: `open`; lesson: Treat every workflow admission and completion capability as server-issued, digest-bound, lock-protected authority and prove the negative path before implementation.
- #3 2026-08-16T10:27:25.000Z `focused_regression`; cause_status: `known`; cause: The first post-remediation focused run correctly rejected an old test that mutated a server-compiled draft in place; the test needed a fresh server compilation for the renamed plan.; resolution: `resolved`; lesson: Once compiler authority is opaque and binding-specific, tests that alter a plan must recompile it through the server-owned path.
- #4 2026-08-16T10:33:43.000Z `admission_step_forgery_red`; cause_status: `known`; cause: An adversarial probe showed that an admission caller could reuse a compiled step fingerprint while changing the step specification; admission initially accepted the forged step.; resolution: `resolved`; lesson: Admission must compare the supplied step structure and server receipt step contract, not only the public step fingerprint.

## All errors

- None recorded.

## All gaps

- #5 2026-08-16T10:35:47.000Z `reviewer_fail_report_unavailable`; cause_status: `external`; cause: The independent reviewer FAIL report named by the remediation request was not present at a locatable repository path in the scoped worktree.; resolution: `accepted`; lesson: A remediation handoff must carry a locatable reviewer report reference before independent reconciliation can be claimed.
- #6 2026-08-16T10:35:47.000Z `fd_persistence_boundary_out_of_scope`; cause_status: `known`; cause: The global persistence capability bypass rule requires an admission-gated FD-only writer, but the remediation owned paths do not include the shared storage implementation.; resolution: `accepted`; lesson: Keep shared persistence capability remediation separate from this lane and carry it as an explicit NOT VERIFIED gate.

## All waste

- None recorded.

## Root causes and solutions

- `admission-step-contract-binding`: occurrences=1; cause_status: `known`; root cause: An adversarial probe showed that an admission caller could reuse a compiled step fingerprint while changing the step specification; admission initially accepted the forged step.; solution: `resolved`
- `fd-persistence-separate-lane`: occurrences=1; cause_status: `known`; root cause: The global persistence capability bypass rule requires an admission-gated FD-only writer, but the remediation owned paths do not include the shared storage implementation.; solution: `accepted`
- `focused-recompile-after-authority`: occurrences=1; cause_status: `known`; root cause: The first post-remediation focused run correctly rejected an old test that mutated a server-compiled draft in place; the test needed a fresh server compilation for the renamed plan.; solution: `resolved`
- `reviewer-report-reference`: occurrences=1; cause_status: `external`; root cause: The independent reviewer FAIL report named by the remediation request was not present at a locatable repository path in the scoped worktree.; solution: `accepted`
- `workflow-truth-authority-boundary`: occurrences=1; cause_status: `known`; root cause: Adversarial workflow truth tests reproduced public compiler hash forgery, non-atomic duplicate admission, forged completion fields, aborted completion, fake evidence ports, missing source digest, and unpersisted model identity.; solution: `open`

## Added tests

- `tests/test_v189_workflow_truth.py`
- `tests/test_workflow_runtime.py`

## New rules

- `admission-step-contract-binding`: line experience occurrence(s)=1
- `fd-persistence-separate-lane`: line experience occurrence(s)=1
- `focused-recompile-after-authority`: line experience occurrence(s)=1
- `reviewer-report-reference`: line experience occurrence(s)=1
- `workflow-truth-authority-boundary`: line experience occurrence(s)=1

## Future guidance

- A remediation handoff must carry a locatable reviewer report reference before independent reconciliation can be claimed.
- Admission must compare the supplied step structure and server receipt step contract, not only the public step fingerprint.
- Keep shared persistence capability remediation separate from this lane and carry it as an explicit NOT VERIFIED gate.
- Once compiler authority is opaque and binding-specific, tests that alter a plan must recompile it through the server-owned path.
- Treat every workflow admission and completion capability as server-issued, digest-bound, lock-protected authority and prove the negative path before implementation.
- Treat focused adversarial evidence and integration/release evidence as separate claims.

## Event index

- #1: `3eaf1a31-4ef5-4553-9301-5275f9358722` | 2026-08-16T10:09:26.483Z | STATE_CHANGE/line_started | incident=`aa7fab6c-f124-4ec0-bd2a-f840185a624e` | lesson_key=`frozen-context-before-start` | event_sha256=`002d750faf33469e7c8fb20cd9edba0b79e32439ea05f0be7ca4b9d0aaec8f1c`
- #2: `7a22d3d4-7d93-4f84-9f34-5cc47f3bb901` | 2026-08-16T11:30:00.000Z | FAILURE/tdd_red_workflow_truth | incident=`d60cf7a5-f0cf-4c2b-8bb8-c0f99b1f3202` | lesson_key=`workflow-truth-authority-boundary` | event_sha256=`476731c75f55046aa4511da4881298086089c622f4acda424c68a40e419cdb38`
- #3: `b0c63a07-6d37-4d0b-9a6e-490a74fd255d` | 2026-08-16T10:27:25.000Z | FAILURE/focused_regression | incident=`db2e77f1-593e-4c4d-a1a9-0a0f7b32a8d6` | lesson_key=`focused-recompile-after-authority` | event_sha256=`b3d9971a2821413fd06bbf06dbda1022f348d79430f810f213e6dcadd615f75d`
- #4: `4b86549b-b1f8-45d7-bab8-9c134fa55e6d` | 2026-08-16T10:33:43.000Z | FAILURE/admission_step_forgery_red | incident=`6557bfe5-2e35-4dd4-b178-6f78aa1e4d65` | lesson_key=`admission-step-contract-binding` | event_sha256=`e9a6271c074145cab6921a6320192a3e93a3d160a7ece42cd376ef0732b0e289`
- #5: `fbeb8c7e-8ab2-47e0-8d7d-82f7cc142e29` | 2026-08-16T10:35:47.000Z | GAP/reviewer_fail_report_unavailable | incident=`a5e6f0bc-a1cc-44e6-9f29-c16b3775363c` | lesson_key=`reviewer-report-reference` | event_sha256=`0f958ad6e96da84fea92b485f409c5c20197c4236413592c584787a18b9f0f25`
- #6: `f99bcbc5-2769-4f6d-9d73-2967e40e5cd6` | 2026-08-16T10:35:47.000Z | GAP/fd_persistence_boundary_out_of_scope | incident=`0cb76929-4764-4036-a4d5-8c4fa9da3d88` | lesson_key=`fd-persistence-separate-lane` | event_sha256=`c8b88129a28857fa7a36bf91e4d197a1a9c20f47293733431769925eef52681a`
- #7: `97b99a27-3bc1-4c77-a6ae-2724a24e4115` | 2026-08-16T10:35:47.000Z | REVIEW/workflow_truth_adversarial_review | incident=`eeb3a5ce-44bd-4430-a9f6-b5b6df3ffb5f` | lesson_key=`lane-local-evidence-boundary` | event_sha256=`caa82446da53beb52ed325ef0ef39c84d85ac198d356db84b939cc8eba0456c2`
- #8: `f7cad2a8-6c78-4a4d-84cb-f22efc5a9c1a` | 2026-08-16T10:35:47.000Z | GATE/focused_workflow_truth_green | incident=`e7e15a37-5c4a-4dc6-a178-24df3a972541` | lesson_key=`focused-gate-evidence` | event_sha256=`27932aad990b9c4b8e9a102fa8fc374a068b390280671d5645190be78d8a2a11`
- #9: `8fd283b4-55cb-4b17-9ae9-72a36b037e31` | 2026-08-16T10:36:38.000Z | STATE_CHANGE/line_completed | incident=`486e7a7a-7cab-430d-89cf-7b40b8c08cd1` | lesson_key=`close-with-explicit-nonclaims` | event_sha256=`edfcec793985f7abefb86d33819b3b15cef31ac73021912f96871ee5451dca52`
