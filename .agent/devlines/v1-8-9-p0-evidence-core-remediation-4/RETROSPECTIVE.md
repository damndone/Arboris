# Retrospective — v1-8-9-p0-evidence-core-remediation-4

## Goal

# v1.8.9 P0 Evidence Core Remediation 4 Objective  Close the final public-construction and proof-forgery gaps found by the remediation-3 adversarial review. EvidenceRegistry construction must be server-factory-only and its durable namespace must be bound to a server-issued authority proof; object.__new__ or a caller-created registry must not make hand-built packet/commit/index artifacts loadable. Persistence admission must validate a non-reconstructible server proof, and projector success must require a non-reconstructible receipt rather than a recomputable summary hash. Invalid proof objects must fail with stable typed errors before reading or writing durable evidence.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-evidence-core-remediation-4 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core  Required outcomes:  - public \`EvidenceRegistryV1()\` and caller-created registries cannot admit or   load durable evidence; only the server factory can issue the registry proof; - object.__new__/field-forged \`EvidencePersistenceAdmissionV1\` cannot write; - fake/recomputed projector receipts cannot create a consumer-visible success; - malformed, cross-owner and cross-process proofs fail with typed,   deterministic errors before packet/index reads; - existing 68 focused cases plus direct construction, proof forgery and   no-read/no-write probes remain green.  Keep the C0 contracts and package-local boundary. Do not modify runtime, consumers, central catalog, frontend, provider wiring, or protected paths.

## Final status

STARTED

## Metrics

- Failure frequency: 1/3 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T12:00:00.000Z `remediation_red_suite`; cause_status: `known`; cause: The new remediation-4 adversarial tests reproduce public registry construction, copied persistence admission, recomputed projection receipt, forged outcome, and no-read proof validation failures in the current implementation.; resolution: `open`; lesson: Adversarial proof and no-read/no-write tests must precede authority-bound Evidence Core implementation.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-remediation-proof-boundary`: occurrences=1; cause_status: `known`; root cause: The new remediation-4 adversarial tests reproduce public registry construction, copied persistence admission, recomputed projection receipt, forged outcome, and no-read proof validation failures in the current implementation.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-remediation-proof-boundary`: line experience occurrence(s)=1

## Future guidance

- Adversarial proof and no-read/no-write tests must precede authority-bound Evidence Core implementation.

## Event index

- #1: `688b7a32-7674-4ed9-9804-a5042c1195c2` | 2026-08-16T11:21:25.401Z | STATE_CHANGE/line_started | incident=`6ce8ef22-9b8b-45c8-a487-cf8f1d1b76c3` | lesson_key=`frozen-context-before-start` | event_sha256=`58e900a838a74cdf1a294ec0d43718312293a99c79c077875da4fcccc02b3b3a`
- #2: `0f84a5c7-3b6a-4f72-9a1d-2c8e6b7f4d10` | 2026-08-16T12:00:00.000Z | FAILURE/remediation_red_suite | incident=`0f84a5c7-3b6a-4f72-9a1d-2c8e6b7f4d10` | lesson_key=`evidence-remediation-proof-boundary` | event_sha256=`b80b99712192f5b9d6017c3535dd892693e77bb89760838213fcd58afff98636`
- #3: `7c1e4a90-5d2b-4f83-9e16-2a7b8c0d4f35` | 2026-08-16T12:10:00.000Z | GATE/evidence_core_adversarial_gate | incident=`7c1e4a90-5d2b-4f83-9e16-2a7b8c0d4f35` | lesson_key=`evidence-proof-adversarial-gate` | event_sha256=`1819cdd5d33a1f2b8c6d3e1d5bca45fa594c67064b404e231fca92c0f5fec20d`
