# Retrospective — v1-8-9-p0-workflow-truth-remediation-6

## Goal

# v1.8.9 P0 Workflow Truth Remediation 6 Objective  Close the P0 bypasses found by the independent review of remediation-5. The package-local green suite is not sufficient while a caller can replace the resolver, create a self-consistent artifact index/manifest, mutate a file and its public hash after admission, feed a forged previous artifact to Report, write outside the run during registration, or reuse a live authority after fork.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Formal line: v1-8-9-p0-workflow-truth-remediation-6 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth  Required outcomes:  - formal artifact admission is server-owned and producer-bound; public index,   manifest, file hash or caller metadata cannot create a valid run/branch or   completion record; - admission freezes the artifact path, bytes/content digest, producer receipt,   run/step/branch/source model identity and expected output; completion and   Report validate the frozen registry instead of trusting a mutable index; - Report previous/dependency artifacts require completed server registry   entries and cannot be injected through a public helper argument; - report/export/artifact file commit and registry update share one admitted   no-follow FD/inode transaction; path/root replacement cannot leave a file or   index outside the project even when the operation ultimately fails; - workflow authority records owner PID/process identity and rejects inherited   fork handles, registries, receipts and directory FDs before any formal IO; - deployment host authority is an external process/OS input; caller-selected   resolver/config/socket/FD and same-process replacement do not become a   production trust root. The package defaults fail closed until that input is   wired; - existing valid receipt behavior and all prior focused regressions remain   green, with direct probes for each review finding repeated at least three   times.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/8 (50.0%; 50.0 per 100 events)
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

- #2 2026-08-16T14:10:00.000Z `report_dependency_fixture_blocked`; cause_status: `known`; cause: The report positive-path helper was upgraded to execute the real model.genesis dependency chain, but its six-row fixture triggered the intentional INSUFFICIENT_SAMPLE validation blocker.; resolution: `resolved`; lesson: When replacing fabricated dependency results with a real runtime path, fixtures must satisfy the same declared modeling preconditions as user data.
- #3 2026-08-16T14:12:00.000Z `report_dependency_fixture_below_minimum`; cause_status: `known`; cause: The modeling validation minimum is 30 observations, so the first fixture correction to 24 rows still remained intentionally blocked.; resolution: `resolved`; lesson: Use the repository's declared min_model_n when constructing positive-path fixtures instead of estimating the threshold from a test name or prior fake result.
- #6 2026-08-16T15:05:00.000Z `formal_registration_outside_artifact`; cause_status: `known`; cause: The formal writer committed through an admitted directory fd but then called the legacy pathname artifact index writer before server admission; replacing the run root in that interval left the committed report outside the project.; resolution: `open`; lesson: Formal output commit, server admission, public index publication, and rollback must share one receipt-bound fd/inode transaction; a pathname register_artifact call cannot sit between them.

## All errors

- None recorded.

## All gaps

- #4 2026-08-16T14:14:00.000Z `model_output_registry_bridge_missing`; cause_status: `known`; cause: The real model.genesis executor returned child-run artifact references, but the receipt-gated server artifact registry had no frozen rows for those child-run files before result admission.; resolution: `open`; lesson: Every child-run artifact returned by a receipt-gated producer must be frozen in the server registry with branch provenance before the typed step result is admitted.

## All waste

- None recorded.

## Root causes and solutions

- `formal-output-registration-transaction`: occurrences=1; cause_status: `known`; root cause: The formal writer committed through an admitted directory fd but then called the legacy pathname artifact index writer before server admission; replacing the run root in that interval left the committed report outside the project.; solution: `open`
- `register-child-run-model-artifacts`: occurrences=1; cause_status: `known`; root cause: The real model.genesis executor returned child-run artifact references, but the receipt-gated server artifact registry had no frozen rows for those child-run files before result admission.; solution: `open`
- `runtime-fixture-model-preconditions`: occurrences=1; cause_status: `known`; root cause: The report positive-path helper was upgraded to execute the real model.genesis dependency chain, but its six-row fixture triggered the intentional INSUFFICIENT_SAMPLE validation blocker.; solution: `resolved`
- `use-declared-model-minimum`: occurrences=1; cause_status: `known`; root cause: The modeling validation minimum is 30 observations, so the first fixture correction to 24 rows still remained intentionally blocked.; solution: `resolved`

## Added tests

- `tests/test_v189_workflow_truth.py::test_formal_registration_rolls_back_when_run_root_is_replaced_after_commit`
- `tests/test_workflow_runtime.py::test_report_collection_exports_one_complete_artifact_pack`

## New rules

- `formal-output-registration-transaction`: line experience occurrence(s)=1
- `register-child-run-model-artifacts`: line experience occurrence(s)=1
- `runtime-fixture-model-preconditions`: line experience occurrence(s)=1
- `use-declared-model-minimum`: line experience occurrence(s)=1

## Future guidance

- Every child-run artifact returned by a receipt-gated producer must be frozen in the server registry with branch provenance before the typed step result is admitted.
- Formal output commit, server admission, public index publication, and rollback must share one receipt-bound fd/inode transaction, and cleanup failures must remain typed and visible.
- Formal output commit, server admission, public index publication, and rollback must share one receipt-bound fd/inode transaction; a pathname register_artifact call cannot sit between them.
- Use the repository's declared min_model_n when constructing positive-path fixtures instead of estimating the threshold from a test name or prior fake result.
- When replacing fabricated dependency results with a real runtime path, fixtures must satisfy the same declared modeling preconditions as user data.

## Event index

- #1: `7be5915e-0e51-4e6f-a2a9-68795839835f` | 2026-08-16T13:41:21.414Z | STATE_CHANGE/line_started | incident=`51851b00-7150-4a17-bcb0-442eb5990e12` | lesson_key=`frozen-context-before-start` | event_sha256=`644fc933fdcf30a26b7bfdb304af6b5ed532870432b36b857948f4780c94561e`
- #2: `d19a5b2d-3e9e-4d51-9de2-8f4d4f9b9a41` | 2026-08-16T14:10:00.000Z | FAILURE/report_dependency_fixture_blocked | incident=`c7b0a9d6-1e47-4d5a-9c81-2e6f0c8a1b32` | lesson_key=`runtime-fixture-model-preconditions` | event_sha256=`0e53a820ce9d2c9290dadce226f94acb030058901a36586d5fe387a2b80a69a2`
- #3: `e8f6c3a1-7b52-4d09-9c44-1a2e5f8b6d37` | 2026-08-16T14:12:00.000Z | FAILURE/report_dependency_fixture_below_minimum | incident=`f4b7d2a9-6e31-4c85-b0d2-9a7f5e1c3b64` | lesson_key=`use-declared-model-minimum` | event_sha256=`5bf3e44a4acfbfc8f303e07628faba4d458d2bb45c521d5c59e821be780ab587`
- #4: `a6d4f2c9-8b17-4e53-9a60-1c7f5b2d4e89` | 2026-08-16T14:14:00.000Z | GAP/model_output_registry_bridge_missing | incident=`b9e3c7a1-5f24-4d80-9c62-1e7a4b6d8f30` | lesson_key=`register-child-run-model-artifacts` | event_sha256=`da14b122504e1e77e5b4ad18f63fdae6e5f2498461e8f72b26fe660e54c8167e`
- #5: `7f2c4a8e-1b63-4d90-9e57-2a6c8b0f4d31` | 2026-08-16T14:25:00.000Z | GATE/workflow_truth_remediation_6_gate | incident=`3e7a1c9d-5b42-4f80-a6d3-2c9e7b1f5a64` | lesson_key=`one-receipt-artifact-registry` | event_sha256=`aa8153dcfd1384d795a7c0c85cdcca8d5f0d0e4253f4b19ee73bd2574866d7ba`
- #6: `b5e7c1a9-4d62-4f80-9a3e-7c1d5b8f2a64` | 2026-08-16T15:05:00.000Z | FAILURE/formal_registration_outside_artifact | incident=`c8f2a6d9-1b47-4e53-9a70-2d6f0c8b5e31` | lesson_key=`formal-output-registration-transaction` | event_sha256=`a101747343373c17265f5f37e2b9d6fcfc650db9f6a86689365f99f6266c055a`
- #7: `d3e9a2c1-7b45-4f80-9a62-1c8e5d0b3f74` | 2026-08-16T16:05:00.000Z | REVIEW/formal_output_transaction_remediated | incident=`c8f2a6d9-1b47-4e53-9a70-2d6f0c8b5e31` | lesson_key=`formal-output-registration-transaction` | event_sha256=`f04101416dce71db539b0802c924b19dfb985c268c929a2d560589734e42f0e5`
- #8: `e4f0b8c2-6a13-4d97-9e54-1b7c5f0a2d86` | 2026-08-16T16:15:00.000Z | STATE_CHANGE/line_completed | incident=`3e7a1c9d-5b42-4f80-a6d3-2c9e7b1f5a64` | lesson_key=`separate-local-and-external-proof` | event_sha256=`a5cd6779aec7111c7fa10aab4c0dc83a6a0e41ca97968f62f0407baa211fe137`
