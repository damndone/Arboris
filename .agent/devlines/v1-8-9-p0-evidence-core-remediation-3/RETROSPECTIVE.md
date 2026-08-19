# Retrospective — v1-8-9-p0-evidence-core-remediation-3

## Goal

# v1.8.9 P0 Evidence Core Remediation 3 Objective  Close the remaining independent Evidence Core fail-closed gaps before integration admission. A caller must not be able to create a self-consistent packet/commit/index outside a trusted registry and have load accept it; every evidence reference, including oracle-check references, must use the closed opaque grammar; cross-process serialization must not be defeated by replacing the lock path; and failed commits must not leave consumer-visible orphaned state. The authority proof must remain valid across the intended process boundary or fail closed rather than relying on a forgeable public Python token.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-evidence-core-remediation-3 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core  Required outcomes:  - load/load_packet require a trusted registry/admission record and reject   hand-built self-consistent persistence artifacts; - oracle_checks.reference and every nested ref reject raw paths, URLs,   slash/backslash and path-like contract identities; - the cross-process lock capability is anchored to the admitted root/FD and   cannot be replaced by a different pathname to create two lock domains; - packet/commit writes are transactional: failed index admission leaves no   orphaned durable packet/commit or returns a clearly quarantined state; - public tokens/receipts cannot be reconstructed to cross a process or owner   boundary; missing proof fails closed.  Keep C0 contracts and the package-local boundary. Do not modify runtime, consumers, central catalog, frontend, provider wiring, or protected paths.

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

- #2 2026-08-16T11:07:31.000Z `evidence_remediation_3_adversarial_red`; cause_status: `known`; cause: Evidence persistence reads were not bound to a trusted registry receipt, oracle reference fields bypassed the closed opaque grammar, the pathname lock could be replaced into a second domain, and index admission failure left newly written packet and commit files.; resolution: `open`; lesson: Every evidence load and persistence mutation must require a non-reconstructable authority proof, root-anchored serialization, closed provenance grammar, and compensating transaction boundary.

## All errors

- None recorded.

## All gaps

- #4 2026-08-16T11:10:01.000Z `ruff_unavailable`; cause_status: `external`; cause: The isolated worktree environment does not provide a ruff executable, so static lint verification cannot be run in this line.; resolution: `accepted`; lesson: Do not install or substitute a tool during a package-local security line merely to turn an unavailable verification surface green.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-remediation-3-authority-transaction-boundary`: occurrences=1; cause_status: `known`; root cause: Evidence persistence reads were not bound to a trusted registry receipt, oracle reference fields bypassed the closed opaque grammar, the pathname lock could be replaced into a second domain, and index admission failure left newly written packet and commit files.; solution: `open`
- `evidence-remediation-3-lint-boundary`: occurrences=1; cause_status: `external`; root cause: The isolated worktree environment does not provide a ruff executable, so static lint verification cannot be run in this line.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-remediation-3-authority-transaction-boundary`: line experience occurrence(s)=1
- `evidence-remediation-3-lint-boundary`: line experience occurrence(s)=1

## Future guidance

- Do not install or substitute a tool during a package-local security line merely to turn an unavailable verification surface green.
- Every evidence load and persistence mutation must require a non-reconstructable authority proof, root-anchored serialization, closed provenance grammar, and compensating transaction boundary.

## Event index

- #1: `37f5150a-c7b7-4af6-b5bc-131f89373706` | 2026-08-16T11:02:34.695Z | STATE_CHANGE/line_started | incident=`764aca2c-1290-4a52-b02b-bfb701b501df` | lesson_key=`frozen-context-before-start` | event_sha256=`3ad70af1c07d6d02b4d7e11fe2ea1929323b7c1305b70c18d73d0785748705e3`
- #2: `9f6f8c6e-4a5b-4f1c-8b2d-7e3a91c5d204` | 2026-08-16T11:07:31.000Z | FAILURE/evidence_remediation_3_adversarial_red | incident=`b0c2d3e4-f5a6-4789-9012-3456789abcde` | lesson_key=`evidence-remediation-3-authority-transaction-boundary` | event_sha256=`8c99a4c016bf0cc7e926d367c039ae556f663490f249af473b2455f1f5ec531f`
- #3: `4a2b1c0d-9e8f-47a6-b5c4-d3e2f1a09876` | 2026-08-16T11:10:00.000Z | GATE/evidence_remediation_3_focused_gate | incident=`c1d2e3f4-a5b6-4789-9012-3456789abcde` | lesson_key=`evidence-remediation-3-focused-gate` | event_sha256=`51a338608d7b42e146889d83f904a6e14d1cc6a7e116e04b03d1b44e4dce4708`
- #4: `5b3c2d1e-0f9a-48b7-c6d5-e4f3a2b10987` | 2026-08-16T11:10:01.000Z | GAP/ruff_unavailable | incident=`d2e3f4a5-b6c7-4890-9123-456789abcdef` | lesson_key=`evidence-remediation-3-lint-boundary` | event_sha256=`b653975b78d2914bba095f771482cb03b737fd5175c83ea00628dbcce8cb9fe3`
- #5: `6c4d2e1f-0a9b-48c7-d6e5-f4a3b2c10987` | 2026-08-16T11:12:00.000Z | STATE_CHANGE/remediation_line_completed | incident=`e3f4a5b6-c7d8-4901-2345-6789abcdef01` | lesson_key=`evidence-remediation-3-boundary-handoff` | event_sha256=`bd815431c89d492798565fbd07192844e74ef1d375747b35370731ab598e30af`
