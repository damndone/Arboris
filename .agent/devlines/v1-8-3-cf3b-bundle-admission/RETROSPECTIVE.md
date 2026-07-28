# Retrospective — v1-8-3-cf3b-bundle-admission

## Goal

# CF3B exact registration and scoped admission  Implement the narrow CF3B control-plane boundary from the approved v1.8.3 Capability Factory design. Register only an exact already-validated ImplementationRevision together with its AdapterContract, ValidationBundle, server EvidenceAssessment, runtime policy ref, and host-containment ref. Make the registration immutable and idempotent for the same identity, reject rebinding or successor substitution, and expose a scoped-admission service that delegates to the existing server-owned admission controller. This phase must remain execution-free, network-free, and unmounted from Agent/HTTP/Notebook.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/11 (45.5%; 45.5 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=4; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-07-27T13:50:00.000Z `cf3b_registration_admission_red`; cause_status: `known`; cause: CF3B tests were written before exact validated registration and scoped admission service existed.; resolution: `resolved`; lesson: Keep exact registration and admission service tests ahead of implementation and preserve the existing server-owned controller as the single admission state machine.
- #3 2026-07-27T14:00:00.000Z `cf3b_trace_contract_red`; cause_status: `known`; cause: CF3B trace tests exposed that the package-local vocabulary had no exact registration or admission lifecycle events.; resolution: `resolved`; lesson: Every new control-plane lifecycle needs an exact package-local trace vocabulary before integration registration.
- #8 2026-07-27T14:25:00.000Z `cf3b_host_validity_red`; cause_status: `known`; cause: CF3B consumption tests exposed that the B1 validity store had no lookup by the immutable validity record reference.; resolution: `resolved`; lesson: Host validity consumers need an exact current-record lookup and must reject expired or revoked records.

## All errors

- #4 2026-07-27T14:10:00.000Z `cf3b_test_path_correction`; cause_status: `known`; cause: A compatibility test command included tests/test_capability_registry.py, which is not present in this checkout.; resolution: `resolved`; lesson: Use the repository's current test paths when assembling compatibility gates.

## All gaps

- #5 2026-07-27T14:15:00.000Z `notebook_v11_test_alignment_gap`; cause_status: `known`; cause: Two existing Notebook binding tests still construct RecommendationDecision@1.0 while the current service requires the server-owned V1.1 contract for admitted capability bindings.; resolution: `open`; lesson: Keep Notebook admitted-capability fixtures on the same server-owned recommendation revision as the production consumer.

## All waste

- None recorded.

## Root causes and solutions

- `cf3b-host-validity-current`: occurrences=1; cause_status: `known`; root cause: CF3B consumption tests exposed that the B1 validity store had no lookup by the immutable validity record reference.; solution: `resolved`
- `cf3b-registration-red`: occurrences=1; cause_status: `known`; root cause: CF3B tests were written before exact validated registration and scoped admission service existed.; solution: `resolved`
- `cf3b-test-path-correction`: occurrences=1; cause_status: `known`; root cause: A compatibility test command included tests/test_capability_registry.py, which is not present in this checkout.; solution: `resolved`
- `cf3b-trace-vocabulary`: occurrences=1; cause_status: `known`; root cause: CF3B trace tests exposed that the package-local vocabulary had no exact registration or admission lifecycle events.; solution: `resolved`
- `notebook-v11-test-alignment`: occurrences=1; cause_status: `known`; root cause: Two existing Notebook binding tests still construct RecommendationDecision@1.0 while the current service requires the server-owned V1.1 contract for admitted capability bindings.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `cf3b-host-validity-current`: line experience occurrence(s)=1
- `cf3b-registration-red`: line experience occurrence(s)=1
- `cf3b-test-path-correction`: line experience occurrence(s)=1
- `cf3b-trace-vocabulary`: line experience occurrence(s)=1
- `notebook-v11-test-alignment`: line experience occurrence(s)=1

## Future guidance

- Every new control-plane lifecycle needs an exact package-local trace vocabulary before integration registration.
- Host validity consumers need an exact current-record lookup and must reject expired or revoked records.
- Keep Notebook admitted-capability fixtures on the same server-owned recommendation revision as the production consumer.
- Keep capability registration and admission as server-owned exact-fact boundaries before later Agent or Notebook integration.
- Keep exact registration and admission service tests ahead of implementation and preserve the existing server-owned controller as the single admission state machine.
- Use the repository's current test paths when assembling compatibility gates.

## Event index

- #1: `b74c3877-5490-411e-9427-eeedca36cd51` | 2026-07-27T08:55:47.103Z | STATE_CHANGE/line_started | incident=`7b3e2a68-dba8-4377-8d31-65510e35f484` | lesson_key=`frozen-context-before-start` | event_sha256=`181669522975c18bd6cfc0a9a0010820f2a4298105e3eef6c84b8a014007a369`
- #2: `e5fb9b6f-87c0-4d47-9af7-950214e2c1d2` | 2026-07-27T13:50:00.000Z | FAILURE/cf3b_registration_admission_red | incident=`e2d93983-036e-4d55-b5b5-508619966216` | lesson_key=`cf3b-registration-red` | event_sha256=`413d680e9348b669a872c17ea58c188843cc8f9ff456f83a21d809f9806699e1`
- #3: `b67b824f-2ddc-4e1c-bd7e-faa9b3f8cae4` | 2026-07-27T14:00:00.000Z | FAILURE/cf3b_trace_contract_red | incident=`b2adf594-f6dc-4fb5-96af-3b5c8e8be8d5` | lesson_key=`cf3b-trace-vocabulary` | event_sha256=`701b6c121feceb7d7cffd68ced5fd2e761307cf18fda7bd87d81ffdc5af480dd`
- #4: `f13c6e7e-19e7-49e5-b62e-b98fae2ec5dd` | 2026-07-27T14:10:00.000Z | ERROR/cf3b_test_path_correction | incident=`56b43852-7fd9-42c2-bf5f-7ef0f07df98f` | lesson_key=`cf3b-test-path-correction` | event_sha256=`1d871c5847ead189f1a0e5a221da33f3d71d73e3902fec52829d3863bd6cf3d9`
- #5: `2b71f739-e358-4ee7-b0e9-63e891e1bff0` | 2026-07-27T14:15:00.000Z | GAP/notebook_v11_test_alignment_gap | incident=`e8fbc20c-b55f-4163-aa3b-eaa0278119fb` | lesson_key=`notebook-v11-test-alignment` | event_sha256=`316dd84f93b1d7445ed64b966a3900d90e7fe6146a921587127fd611de2b9d18`
- #6: `e0819be5-6d15-4a5c-a60d-f511f149cba1` | 2026-07-27T09:07:17.080Z | STATE_CHANGE/context_rescope_required | incident=`e0001e49-7a86-472e-94f7-adde02206333` | lesson_key=`context-pack-rescope` | event_sha256=`058441ac8c3ee23b84d55724ac3d62d63f626493bd0dc2b38768f82f5a108af3`
- #7: `06b40be7-6a19-4cc2-9ff2-86e3d36e2643` | 2026-07-27T09:07:17.084Z | STATE_CHANGE/context_rescoped | incident=`9f093e9f-2908-4e08-a8c7-56234fdb2b65` | lesson_key=`context-pack-rescope` | event_sha256=`db58da7ff8bae34d8326563cf89717d9173da59b81f49cf7eb54e1bbf7df4521`
- #8: `bf0e246e-77d5-4118-8808-d70bfa7e07f3` | 2026-07-27T14:25:00.000Z | FAILURE/cf3b_host_validity_red | incident=`1f8bf5c5-1b05-4814-9b6d-bb05c35ab5c9` | lesson_key=`cf3b-host-validity-current` | event_sha256=`fc285ddecc043f4f7f6447f270cd433f034d23b9861499ec4370ba87a402ed67`
- #9: `5a6c3d5a-9f58-4b63-bf04-8e6c77a5a9d2` | 2026-07-27T09:12:31.000Z | REVIEW/cf3b_exact_fact_boundary_review | incident=`e3cc9f67-0b9e-44e1-a97f-8cc7f8e5531a` | lesson_key=`cf3b-exact-fact-boundary` | event_sha256=`eb2e31d321f4203d2db4c34ccde2d73247aeff5ab18f7b89060f0751045cd39a`
- #10: `7cd26d21-4aaf-4e45-b7c5-24d55b4ce1d1` | 2026-07-27T09:12:31.000Z | GATE/cf3b_control_plane_gate | incident=`c12bf8df-d6e4-4e34-94d5-a5bc14d13a10` | lesson_key=`cf3b-control-plane-gate-separate-from-host-acceptance` | event_sha256=`35b3d673770be86b57526136ad0a02d39e05d531fea3c32f67caad9616aaefe0`
- #11: `f9cfe8d6-b4a7-4fe6-a9d2-4f285b7f5d2e` | 2026-07-27T09:12:31.000Z | STATE_CHANGE/cf3b_exact_registration_admission_completed | incident=`bbf401f5-8be7-4e44-a070-8a93bbde8dc7` | lesson_key=`close-bounded-control-plane-before-cf4` | event_sha256=`9e91506cfda26962e3d691fe2ed739d27e69dd48df7c3525895cfd3f6fa993f2`
