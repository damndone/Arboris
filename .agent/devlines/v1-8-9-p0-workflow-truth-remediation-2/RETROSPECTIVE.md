# Retrospective — v1-8-9-p0-workflow-truth-remediation-2

## Goal

# v1.8.9 P0 Workflow Truth Remediation 2 Objective  Close the independently reproduced Workflow Truth authority and persistence gaps before integration admission. Workflow admission must be atomic across processes, public executor construction must not create a write-capable callback outside a server-issued receipt, completion must be bound to the immutable admitted plan and result identity, and model runs must be proven to belong to the admitted source artifact rather than merely carrying non-empty ids and digests.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-workflow-truth-remediation-2 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth  Required outcomes:  - cross-process duplicate admissions yield one durable winner or a stable   replay/conflict, never two active receipts; - build_workflow_step_executor and every write-capable callback require a   server-issued admission/receipt and cannot be called as a public bypass; - completion revalidates the complete persisted admission, plan, step,   contract, output and content identity before append; - workflow template, bindings, preconditions and plan digest are immutable   admission inputs; - model run, source artifact and source digest are cross-checked against the   same project/registry record; - no filesystem directory or output is created before valid admission.  Keep the locked C0 contract and package-local boundary. Do not modify central catalog, shared cutover, frontend, provider wiring, or protected paths.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/12 (16.7%; 16.7 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=60000 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T12:15:00.000Z `tdd_red_workflow_remediation`; cause_status: `known`; cause: The remediation red tests reproduced cross-process duplicate admissions, a public write-capable callback bypass, paired completion tampering, incomplete plan binding, source artifact mismatch, and directory creation without an admission receipt.; resolution: `open`; lesson: Every workflow write must be gated by a server-issued receipt and every persisted identity must be bound to an immutable admission and verifiable completion seal.

## All errors

- None recorded.

## All gaps

- #4 2026-08-16T12:15:00.000Z `workflow_persistence_gap`; cause_status: `known`; cause: The current package-local boundary has no cross-process admission fence, no immutable completion authenticity anchor, and no registry cross-check tying a model branch to the draft source artifact and digest.; resolution: `open`; lesson: Keep persistence and model lineage fail-closed at the exact server authority boundary before adding Agent or Notebook consumers.

## All waste

- None recorded.

## Root causes and solutions

- `workflow-persistence-and-lineage-gap`: occurrences=1; cause_status: `known`; root cause: The current package-local boundary has no cross-process admission fence, no immutable completion authenticity anchor, and no registry cross-check tying a model branch to the draft source artifact and digest.; solution: `open`
- `workflow-remediation-red-before-fix`: occurrences=1; cause_status: `known`; root cause: The remediation red tests reproduced cross-process duplicate admissions, a public write-capable callback bypass, paired completion tampering, incomplete plan binding, source artifact mismatch, and directory creation without an admission receipt.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `workflow-persistence-and-lineage-gap`: line experience occurrence(s)=1
- `workflow-remediation-red-before-fix`: line experience occurrence(s)=1

## Future guidance

- Every workflow write must be gated by a server-issued receipt and every persisted identity must be bound to an immutable admission and verifiable completion seal.
- Keep persistence and model lineage fail-closed at the exact server authority boundary before adding Agent or Notebook consumers.
- Treat a focused green suite as insufficient until independent process, callback, tamper, and source-registry probes pass.

## Event index

- #1: `1e9582d2-b449-463c-956d-bfc34acd9488` | 2026-08-16T10:51:28.070Z | STATE_CHANGE/line_started | incident=`856d956a-085b-4df0-86ba-97595e79ba9d` | lesson_key=`frozen-context-before-start` | event_sha256=`e00f0c61f678ca0ce6df3a7079f9a7c168304e51a7eb5dded4614a8b9cad4c1d`
- #2: `2d1e7a40-1b72-4f5f-9e5f-5d3b8f6d4a01` | 2026-08-16T12:15:00.000Z | FAILURE/tdd_red_workflow_remediation | incident=`a3c6e8d1-5f42-4f95-8e21-7b0c9d4a6e12` | lesson_key=`workflow-remediation-red-before-fix` | event_sha256=`c41d65364a4fbeece61a60206288ae3cc40bfd84c450866a44684c06cca6def8`
- #3: `3e2f8b51-2c83-4a60-af60-6e4c97e5b123` | 2026-08-16T12:15:00.000Z | REVIEW/workflow_authority_review | incident=`b4d7f9e2-6a53-4fa6-9f32-8c1d0e5b7f23` | lesson_key=`workflow-review-must-probe-real-authority` | event_sha256=`e35e86fc3c46392250d7e1f01287e17144b6619d54f05a18c73d6b4ce9118484`
- #4: `4f30c962-3d94-4b71-b071-7f5da8f6c234` | 2026-08-16T12:15:00.000Z | GAP/workflow_persistence_gap | incident=`c5e80af3-7b64-4ab7-a043-9d2e1f6c8a34` | lesson_key=`workflow-persistence-and-lineage-gap` | event_sha256=`e7f669ea339cfab167a3e5ecd92174e8901e969fc97ba5f3f577e2837fe1be22`
- #5: `5a3b7c91-6f2e-4b8d-9c10-2d4e6f8a1b30` | 2026-08-16T11:10:20.000Z | GATE/workflow_targeted_gate | incident=`6b4c8d02-7e3f-4a9b-8c21-3e5f7a9b2c41` | lesson_key=`bounded-workflow-gate-separate-from-release` | event_sha256=`1c8ef8f4e8e15988a98b02bf9562e27f4c332b75713397bfc63fb24afc85ef3a`
- #6: `7c5e9a13-8b4d-4f20-a6c1-5e7b9d2f4a86` | 2026-08-16T11:10:20.000Z | STATE_CHANGE/workflow_truth_remediation_completed | incident=`8d6f0b24-9c5e-4a31-b7e2-6f8c0d4a9b17` | lesson_key=`close-bounded-workflow-line` | event_sha256=`c943eb8fd0fabf5a3d4353ef398579e73f2ca697f8b3f9ea25c7d487699c5593`
- #7: `9e7a1c53-4b6d-4f20-8a92-6c1e3d5f7b04` | 2026-08-16T11:11:56.000Z | REVIEW/tdd_red_workflow_remediation_resolved | incident=`a3c6e8d1-5f42-4f95-8e21-7b0c9d4a6e12` | lesson_key=`workflow-remediation-red-before-fix` | event_sha256=`48c0d0e53315f0d6c1e6a42892010b152fdba657bbeed77b4e41e60bbb42233c`
- #8: `af8c2e64-5b7d-4a91-9c03-7e2f4d6b8a15` | 2026-08-16T11:11:56.000Z | REVIEW/workflow_authority_review_resolved | incident=`b4d7f9e2-6a53-4fa6-9f32-8c1d0e5b7f23` | lesson_key=`workflow-review-must-probe-real-authority` | event_sha256=`3e60830242a2b6690b195ac3387006fb7f1764228486d07bf64827b87ef2a2ad`
- #9: `c19d3f75-6a8e-4b02-9d14-8f3e5c7a9b26` | 2026-08-16T11:11:56.000Z | REVIEW/workflow_persistence_gap_resolved | incident=`c5e80af3-7b64-4ab7-a043-9d2e1f6c8a34` | lesson_key=`workflow-persistence-and-lineage-gap` | event_sha256=`ee440ecceec64b221e6576a56d0a7dee10ffef083038f5b20a7bee540a88930e`
- #10: `d2a4f6b8-1c3e-4d5f-9a70-2b4c6e8f0a13` | 2026-08-16T12:16:00.000Z | REVIEW/tdd_red_workflow_remediation_resolved_late | incident=`a3c6e8d1-5f42-4f95-8e21-7b0c9d4a6e12` | lesson_key=`workflow-remediation-red-before-fix` | event_sha256=`5b764b880aa5423528ca01b9f9fed8df2316312f3f3fc72f05f7fdfd17b75448`
- #11: `e3b5a7c9-2d4f-4e60-8b91-3c5d7f9a1e24` | 2026-08-16T12:16:00.000Z | REVIEW/workflow_authority_review_resolved_late | incident=`b4d7f9e2-6a53-4fa6-9f32-8c1d0e5b7f23` | lesson_key=`workflow-review-must-probe-real-authority` | event_sha256=`3fbf621458525c09f752045b89eea8e518ec40f1e99ec2dfe60cb4107367d644`
- #12: `f4c6b8d0-3e5a-4f71-9c02-4d6e8a0b2f35` | 2026-08-16T12:16:00.000Z | REVIEW/workflow_persistence_gap_resolved_late | incident=`c5e80af3-7b64-4ab7-a043-9d2e1f6c8a34` | lesson_key=`workflow-persistence-and-lineage-gap` | event_sha256=`ea70fc59f68ec0b159c755f25f0e2405ba4a5082bfec4eb5bcb787a55cbb33e9`
