# Retrospective — v1-8-3-cf4-admission-control

## Goal

# v1.8.3 CF4 scoped admission control-plane foundation  Implement one bounded CF4 slice: derive a server-owned EvidenceAssessment from the CF3 validation bundle, record append-only validity changes, and bind a scoped capability admission record to the exact adapter, validation bundle, assessment, runtime policy, operations, and consumer slots. Add an Agent-side high-risk proposal binding through the existing ProposalStore and RiskAuthorizationStore only; do not consume a grant or execute an adapter.  Evidence tier and admission state must remain separate. E1 or lower evidence must not become normally source-eligible merely because a user confirms an admission proposal. Admission must fail closed on identity, freshness, scope, operation, consumer, or validity mismatches. Keep the slice generic across capability kinds and avoid modifying Notebook, Graph, HTTP, workflow, AgentCore, registry, runtime ABI, user-data access, network access, imports, installation, or execution surfaces.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
- Repeat rate: 1/3 (33.3%)
- Recurrence rate: 1/2 (50.0%)
- MTTR: median=0 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-07-26T14:53:10.000Z `tdd_red_before_admission_modules`; cause_status: `known`; cause: CF4 admission tests ran before the target modules existed and produced the expected import failures.; resolution: `resolved`; lesson: Write admission negative tests before implementing the scoped control plane.
- #3 2026-07-26T14:58:10.000Z `forged_admission_record_red`; cause_status: `known`; cause: A copied admission record with matching fields was initially accepted without proving it was the controller current record.; resolution: `resolved`; lesson: Every admission use must prove current controller identity, exact binding, validity, scope, and evidence floor.
- #5 2026-07-26T15:03:17.000Z `independent_review_gap`; cause_status: `known`; cause: Independent review found that admission use did not bind the presented runtime policy, and completion did not prove that the controller's current record matched the confirmed proposal.; resolution: `resolved`; lesson: Every admission completion and use must bind the exact current record and runtime policy, not only stable capability references.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-admission-separation`: occurrences=1; cause_status: `known`; root cause: CF4 admission tests ran before the target modules existed and produced the expected import failures.; solution: `resolved`
- `fail-closed-admission`: occurrences=2; cause_status: `known`; root cause: A copied admission record with matching fields was initially accepted without proving it was the controller current record.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-admission-separation`: line experience occurrence(s)=1
- `fail-closed-admission`: line experience occurrence(s)=2

## Future guidance

- Admission must bind the current immutable record and must not infer trust from copied fields.
- Every admission completion and use must bind the exact current record and runtime policy, not only stable capability references.
- Every admission use must prove current controller identity, exact binding, validity, scope, and evidence floor.
- Write admission negative tests before implementing the scoped control plane.

## Event index

- #1: `ca422a39-7dbd-4274-8b54-75b4e80b2cbb` | 2026-07-26T14:45:18.365Z | STATE_CHANGE/line_started | incident=`038d6d05-d056-43d1-86af-590ac610e544` | lesson_key=`frozen-context-before-start` | event_sha256=`f3feff07f22c6fa52ff92759a2b6f30fc13e4a2fd95f28fcd6a2cd2b5f55a1f4`
- #2: `d8d458bb-9cc6-4e6d-9864-5fddaf88d0ef` | 2026-07-26T14:53:10.000Z | FAILURE/tdd_red_before_admission_modules | incident=`bb87c5df-d2b7-4638-a754-81d60a04d33d` | lesson_key=`evidence-admission-separation` | event_sha256=`5070e59ccb7821199c891cee12a5f265919fa2d957b0b2da3767621afb6f3d53`
- #3: `7c18f9fb-18ed-45ea-b2c3-c2dd11a3b6b6` | 2026-07-26T14:58:10.000Z | FAILURE/forged_admission_record_red | incident=`c0f6fd7a-7c01-49e4-a6c0-d3e731004f4b` | lesson_key=`fail-closed-admission` | event_sha256=`96945bfab998ee45f4ff1f6837211db68d37d99f83085712e35dbb2c273b9137`
- #4: `5bcff7c2-9df1-468a-ab22-c2fa0e3b9c6a` | 2026-07-26T14:58:33.000Z | REVIEW/cf4_admission_boundary_review | incident=`00e54453-97fb-46d0-bdd1-c955e978a777` | lesson_key=`fail-closed-admission` | event_sha256=`3abaf54e590c353745b88e62106473bd059b31e6c892ee514d1f051e5b6c65b4`
- #5: `e6c55a18-4cd3-4d4b-b1a6-8d0b7f263ab0` | 2026-07-26T15:03:17.000Z | FAILURE/independent_review_gap | incident=`b4d7d2b0-61bc-42a5-88bf-c0fda286e4ac` | lesson_key=`fail-closed-admission` | event_sha256=`6aa726f0baa3d07622cd7902e343eaa928fbf570a865a36aba0e04426d51480c`
- #6: `a1b62dca-9f5f-4e6b-b3da-b3e14fd9ffb5` | 2026-07-26T15:04:30.000Z | GATE/cf4_targeted_regression_gate | incident=`2f3e1b72-7d27-42a1-9d6f-7b796b7f0b2d` | lesson_key=`targeted-cf4-gate` | event_sha256=`300e94ddd58d8bb56c03cd6ee205dfb434d80f9d515aad4164a2645b9ecb34c9`
- #7: `2bdc7e7c-34b5-46ed-96f4-b72a8d6bf7ef` | 2026-07-26T15:04:30.000Z | STATE_CHANGE/line_completed | incident=`3a7f8af2-54bb-4e83-a79b-3f6b09c4f0d8` | lesson_key=`close-on-evidence-boundary` | event_sha256=`48cc83b803f30512ce17cf25f875d1aa0d782ea7a3b6dadeffd52820ba713e7e`
