# Retrospective — v1-8-9-p0-evidence-core-remediation-2

## Goal

# v1.8.9 P0 Evidence Core Remediation 2 Objective  Close the independently reproduced Evidence Core persistence and provenance gaps before integration admission. The persistence layer must remain safe when multiple store instances write the same project, must bind commit identity to an immutable trusted admission rather than merely matching two mutable files, and must reject path-like structured references at every nested provenance boundary. Public projection and persistence-admission value construction must not provide a success or write capability that bypasses the server-owned factory/receipt boundary.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-evidence-core-remediation-2 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core  Required outcomes:  - cross-instance and cross-process concurrent writes preserve every committed   index entry or fail with a stable retryable conflict; - commit and packet bindings cannot be changed together and remain accepted; - ContractRef and nested provenance use one strict closed opaque-ref grammar; - public projection values cannot be forged into a successful mutable result; - persistence admission requires an unforgeable server-issued admission token; - adversarial tests demonstrate each bypass fails before unsafe persistence or   consumer-visible success.  Keep the locked C0 envelope and package-local boundary. Do not modify runtime, consumers, central catalog, frontend, provider wiring, or protected paths.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/5 (40.0%; 40.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: N/A (sample=0; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T10:45:11.000Z `evidence_remediation_2_adversarial_red`; cause_status: `known`; cause: The current Evidence Core uses instance-local locking, pairwise packet and commit consistency, permissive structured references, public projection construction, and a public FD admission constructor.; resolution: `open`; lesson: Evidence persistence and consumer-facing success require cross-process serialization and server-owned construction proofs at every boundary.

## All errors

- None recorded.

## All gaps

- #4 2026-08-16T10:48:51.000Z `evidence_remediation_2_ruff_unavailable`; cause_status: `external`; cause: The isolated worktree environment does not contain a ruff executable, so the optional static lint command cannot be run without installing a dependency.; resolution: `accepted`; lesson: A missing optional verifier must remain an explicit evidence boundary rather than being replaced by an unreported installation or an unsupported success claim.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-remediation-2-boundaries`: occurrences=1; cause_status: `known`; root cause: The current Evidence Core uses instance-local locking, pairwise packet and commit consistency, permissive structured references, public projection construction, and a public FD admission constructor.; solution: `open`
- `evidence-remediation-2-ruff-gap`: occurrences=1; cause_status: `external`; root cause: The isolated worktree environment does not contain a ruff executable, so the optional static lint command cannot be run without installing a dependency.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-remediation-2-boundaries`: line experience occurrence(s)=1
- `evidence-remediation-2-ruff-gap`: line experience occurrence(s)=1

## Future guidance

- A missing optional verifier must remain an explicit evidence boundary rather than being replaced by an unreported installation or an unsupported success claim.
- Evidence persistence and consumer-facing success require cross-process serialization and server-owned construction proofs at every boundary.

## Event index

- #1: `37b7491e-a857-432d-97f2-e2e25867bfa7` | 2026-08-16T10:37:49.339Z | STATE_CHANGE/line_started | incident=`b2341398-ddeb-4508-a5c2-2d6313461427` | lesson_key=`frozen-context-before-start` | event_sha256=`e823e11310e5fb43f6cdbea73ff6c7b698212826dcad98e4193f92f4ea33158a`
- #2: `f1a6e79e-2e25-4c99-bd08-8e8c93ddc1d3` | 2026-08-16T10:45:11.000Z | FAILURE/evidence_remediation_2_adversarial_red | incident=`1db1a20e-b55c-49a2-853c-29a79ebd2583` | lesson_key=`evidence-remediation-2-boundaries` | event_sha256=`d713ac2767e1025bc9e9d61749424ef75ba83f5514a4d65388068b234d855fc9`
- #3: `f7a66e01-6b80-4fe9-bf3e-6f37ba3f2c74` | 2026-08-16T10:48:32.000Z | GATE/evidence_remediation_2_focused_gate | incident=`6a0fbd6e-7626-49a1-a80c-bbc132a247a4` | lesson_key=`evidence-remediation-2-focused-gate` | event_sha256=`84d1916c04a2f89399bc35a0e663ea8f30e1c06e72f2b12b3a63d5421e8e968e`
- #4: `bd4b5ad4-83c3-4d35-9b2a-4eae9f5e8e5a` | 2026-08-16T10:48:51.000Z | GAP/evidence_remediation_2_ruff_unavailable | incident=`15a384e7-06bd-4c68-b1ab-6e969b38e4fb` | lesson_key=`evidence-remediation-2-ruff-gap` | event_sha256=`68bdb139b350e48712b5b428724573f2d06765fc9ce7b213ace390c99b9276fa`
- #5: `4c7797fd-9e52-4ee0-befc-4b77aafc5a7e` | 2026-08-16T10:49:48.000Z | STATE_CHANGE/evidence_remediation_2_completed | incident=`a9f3a5d2-d62b-4f2a-9c8d-511ff9d7c59c` | lesson_key=`evidence-remediation-2-completion-boundary` | event_sha256=`5544c725bf9590cbc6f374cc7f4b7c0087f5764a9958798c7ff5b8527f166921`
