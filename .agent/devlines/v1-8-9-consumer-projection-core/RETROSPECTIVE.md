# Retrospective — v1-8-9-consumer-projection-core

## Goal

# Workbench v1.8.9 Consumer Projection Core Objective  ## Objective  Build the bounded, non-recomputing evidence-consumer layer for Agent, Notebook, Report and UI. Every consumer must select facts from a persisted, server-bound EvidenceEnvelope/artifact identity; it must never recalculate statistics, accept client-supplied facts, expose unrestricted raw payloads or turn unavailable evidence into zeros or empty success states.  ## Required behavior  - Resolve a committed EvidenceEnvelope and its artifact/data snapshot identity   before projecting any facts. - Define a declarative, versioned consumer projection registry with consumer ID,   accepted evidence/envelope refs, selected fact kinds, redaction policy,   budget, ordering and renderer key. - Agent and Notebook projections are bounded and sensitivity-aware; remote   contexts use the existing C0 egress gateway and produce an auditable receipt. - Report/UI projections preserve fact IDs, values, units, intervals, caveats,   availability and validation provenance while visibly distinguishing   \`UNAVAILABLE\`, \`DEGRADED\` and \`BLOCKED\`. - Unknown schema, sensitivity, renderer, consumer or evidence identity fails   closed. No generic raw-dict fallback is allowed. - Coverage is derived from provider and consumer declarations, versioned at the   raw-key level, and reports direct/composable/unreachable/exempt paths without   aggregate-count-only claims.  ## Scope  Owned files are exactly those listed in the formal Work Order \`docs/superpowers/release-trains/v1.8.9/work-orders/wo-consumer-projection-core.md\`. Central compiler, workflow runtime, central registry, Notebook planner, Report mount and section registry are protected and must not be modified in this line.  ## Baseline and gates  - Exact baseline: \`91ee6a05eab2a1892844c8a3057e1e607359a29e\`. - Dependency: the closed P0 model-branch Resume line and existing Contract   Lock/Evidence Core/Agent Compiler contracts. - Required: TDD RED/GREEN, persisted-envelope mutation probe, sensitivity and   egress adversarial probes, exact identity/coverage tests, frontend renderer   tests/typecheck, compileall, diff check, formal retrospective and verify. - Browser, real provider, production host, full repository gate, merge, push,   tag and release remain explicit follow-up gates.

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 9/16 (56.2%; 56.2 per 100 events)
- Repeat rate: 0/9 (0.0%)
- Recurrence rate: 0/9 (0.0%)
- MTTR: median=0 ms (sample=5; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-20T11:10:14.205Z `path_class_coverage_tdd_red`; cause_status: `known`; cause: The coverage raw key did not retain whether a declared path was direct or composable, so the new audit invariant failed before implementation.; resolution: `resolved`; lesson: Run a real RED probe for path-level coverage before changing the coverage model
- #4 2026-08-20T11:14:35.905Z `consumer_artifact_boundary_tdd_red`; cause_status: `known`; cause: The consumer projection allowed a forged binding artifact admission for the Report consumer because its artifact check was excluded from the common boundary.; resolution: `resolved`; lesson: Every consumer must share the same server-bound artifact admission check
- #5 2026-08-20T11:18:17.989Z `consumer_ui_identity_contract_tdd_red`; cause_status: `known`; cause: The typed Report renderer did not surface the persisted input data snapshot identity and accepted a Notebook contract under the Report consumer gate.; resolution: `resolved`; lesson: Typed consumer parsers must bind contract identity to the expected consumer and visibly preserve input snapshot identity
- #7 2026-08-20T11:30:28.822Z `consumer_ui_renderer_snapshot_validation_tdd_red`; cause_status: `known`; cause: The typed Report parser accepted a projection without a renderer declaration and accepted a non-digest data snapshot identity.; resolution: `open`; lesson: Typed UI boundaries must reject both missing renderer identity and malformed data snapshot digests before rendering any facts.
- #9 2026-08-20T11:43:27.736Z `consumer_projection_direct_forgery_red`; cause_status: `known`; cause: The production Agent, Notebook and shared projection boundary accepted a caller-constructed PersistedEvidenceEnvelopeV1 without a server-owned packet store, registry receipt, or host authority capability.; resolution: `open`; lesson: Consumer projections must require a live server-owned persistence capability instead of trusting a self-consistent persisted-envelope value object.
- #12 2026-08-20T12:12:43.723Z `family_result_binding_regression`; cause_status: `known`; cause: The P0 consumer-boundary refactor exposed an existing workflow result-contract failure in the ARMA/GARCH real-workflow Report regression: the time-series result has a persisted production artifact but no generic coefficients map, so the generic estimation binding rejects it as MODEL_RESULT_INVALID.; resolution: `open`; lesson: Every supported model family needs a family-aware persisted result binding; generic coefficient validation must not reject valid non-coefficient time-series evidence.
- #13 2026-08-20T12:32:07.154Z `report_request_identity_boundary`; cause_status: `known`; cause: The report view builder still accepts a caller-created request identity and returns available facts instead of rejecting the unadmitted identity.; resolution: `open`; lesson: A caller-supplied report request identity cannot be treated as server authority even when its fields match the owner.
- #15 2026-08-20T12:44:59.523Z `consumer_private_raw_reader_red`; cause_status: `known`; cause: The server-owned consumer source still exposed _load_record(), allowing a private object method to return a PersistedEvidenceEnvelopeV1 with available facts outside the Registry.project production boundary.; resolution: `resolved`; lesson: Keep raw persisted-envelope reload inside the module projection seam and expose only typed projections from server-owned consumer sources.

## All errors

- None recorded.

## All gaps

- #2 2026-08-20T11:03:29.833Z `provider_consumer_declaration_schema`; cause_status: `known`; cause: The current fixed provider catalog schema cannot express fact kinds, sensitivity/redaction budgets, ordering, renderer version, or unreachable/exempt ownership metadata required for declaration-derived consumer coverage.; resolution: `open`; lesson: Do not encode missing provider declaration semantics as consumer-side hardcoded defaults

## All waste

- None recorded.

## Root causes and solutions

- `all-consumers-artifact-admission`: occurrences=1; cause_status: `known`; root cause: The consumer projection allowed a forged binding artifact admission for the Report consumer because its artifact check was excluded from the common boundary.; solution: `resolved`
- `consumer-private-raw-reader-boundary`: occurrences=1; cause_status: `known`; root cause: The server-owned consumer source still exposed _load_record(), allowing a private object method to return a PersistedEvidenceEnvelopeV1 with available facts outside the Registry.project production boundary.; solution: `resolved`
- `consumer-projection-direct-forgery-red`: occurrences=1; cause_status: `known`; root cause: The production Agent, Notebook and shared projection boundary accepted a caller-constructed PersistedEvidenceEnvelopeV1 without a server-owned packet store, registry receipt, or host authority capability.; solution: `open`
- `consumer-provider-schema-gap`: occurrences=1; cause_status: `known`; root cause: The current fixed provider catalog schema cannot express fact kinds, sensitivity/redaction budgets, ordering, renderer version, or unreachable/exempt ownership metadata required for declaration-derived consumer coverage.; solution: `open`
- `consumer-ui-contract-identity-red`: occurrences=1; cause_status: `known`; root cause: The typed Report renderer did not surface the persisted input data snapshot identity and accepted a Notebook contract under the Report consumer gate.; solution: `resolved`
- `consumer-ui-renderer-snapshot-red`: occurrences=1; cause_status: `known`; root cause: The typed Report parser accepted a projection without a renderer declaration and accepted a non-digest data snapshot identity.; solution: `open`
- `coverage-path-class-red`: occurrences=1; cause_status: `known`; root cause: The coverage raw key did not retain whether a declared path was direct or composable, so the new audit invariant failed before implementation.; solution: `resolved`
- `family-aware-result-binding-regression`: occurrences=1; cause_status: `known`; root cause: The P0 consumer-boundary refactor exposed an existing workflow result-contract failure in the ARMA/GARCH real-workflow Report regression: the time-series result has a persisted production artifact but no generic coefficients map, so the generic estimation binding rejects it as MODEL_RESULT_INVALID.; solution: `open`
- `report-request-identity-authority`: occurrences=1; cause_status: `known`; root cause: The report view builder still accepts a caller-created request identity and returns available facts instead of rejecting the unadmitted identity.; solution: `open`

## Added tests

- `docs/superpowers/handoff/2026-08-20-v1.8.9-consumer-projection-core-handoff.md`
- `frontend/src/report/FamilyEvidence.test.tsx`
- `tests/test_v189_consumer_coverage.py`
- `tests/test_v189_consumer_projection.py`
- `tests/test_v189_consumer_projection.py::test_agent_notebook_and_shared_registry_reject_direct_forged_persisted_envelope`
- `tests/test_v189_evidence_report_boundary.py::test_arma_garch_report_admission_valid_real_workflow_renders_owner_document`
- `tests/test_v189_evidence_report_boundary.py::test_remediation_four_caller_created_request_identity_cannot_admit_report_view`

## New rules

- `all-consumers-artifact-admission`: line experience occurrence(s)=1
- `consumer-private-raw-reader-boundary`: line experience occurrence(s)=1
- `consumer-projection-direct-forgery-red`: line experience occurrence(s)=1
- `consumer-provider-schema-gap`: line experience occurrence(s)=1
- `consumer-ui-contract-identity-red`: line experience occurrence(s)=1
- `consumer-ui-renderer-snapshot-red`: line experience occurrence(s)=1
- `coverage-path-class-red`: line experience occurrence(s)=1
- `family-aware-result-binding-regression`: line experience occurrence(s)=1
- `report-request-identity-authority`: line experience occurrence(s)=1

## Future guidance

- A caller-supplied report request identity cannot be treated as server authority even when its fields match the owner.
- A production consumer projection boundary must require an exact server-issued source and owner-issued request identity, not only matching value-object fields or digests.
- Consumer projections must require a live server-owned persistence capability instead of trusting a self-consistent persisted-envelope value object.
- Do not encode missing provider declaration semantics as consumer-side hardcoded defaults
- Every consumer must share the same server-bound artifact admission check
- Every supported model family needs a family-aware persisted result binding; generic coefficient validation must not reject valid non-coefficient time-series evidence.
- Green package tests do not prove that every consumer input originated from a server-owned persistence receipt; review the authority boundary separately from projection semantics.
- Keep raw persisted-envelope reload inside the module projection seam and expose only typed projections from server-owned consumer sources.
- Keep renderer identity and snapshot digest validation at the runtime boundary, not only in TypeScript types.
- Run a real RED probe for path-level coverage before changing the coverage model
- Typed UI boundaries must reject both missing renderer identity and malformed data snapshot digests before rendering any facts.
- Typed consumer parsers must bind contract identity to the expected consumer and visibly preserve input snapshot identity

## Event index

- #1: `33541e20-8a42-460d-ab82-1f9fb995f56a` | 2026-08-20T10:53:18.680Z | STATE_CHANGE/line_started | incident=`f8f873f5-d35d-4d52-a4e5-d0490bb19d08` | lesson_key=`frozen-context-before-start` | event_sha256=`6bf86cb0d39555f6ccf07f6a253844782b3db0ed9f93278368c71bd16a2b0898`
- #2: `5f1b5e85-2af2-4bf1-9e90-34e49b49d101` | 2026-08-20T11:03:29.833Z | GAP/provider_consumer_declaration_schema | incident=`07fdfb98-3f23-4d1a-a93e-0f5d0d845c7d` | lesson_key=`consumer-provider-schema-gap` | event_sha256=`823bf0dac101bf21acc8aee37b438b9147dba1570eb7c32078ea69bc8361c841`
- #3: `a77e4cc1-6db1-4b25-a0a7-8f4f4d5f1b1c` | 2026-08-20T11:10:14.205Z | FAILURE/path_class_coverage_tdd_red | incident=`b915f76d-8c9d-4c50-9e7e-1dd4b9a5be0c` | lesson_key=`coverage-path-class-red` | event_sha256=`81dc287da7e27c0a8752d1d360e030643ff2e7679ef3cbc5bd74e9f4d90abda7`
- #4: `f1e95f16-88e6-4b19-a3c5-4ab1e4e8d0ab` | 2026-08-20T11:14:35.905Z | FAILURE/consumer_artifact_boundary_tdd_red | incident=`c3e7a7ef-7754-4b23-9fc9-0b44dbb31b47` | lesson_key=`all-consumers-artifact-admission` | event_sha256=`fcdc2e846e1d9d4f438c12cbb1d68dabbb9497377411b6f5b5c257ad515168c0`
- #5: `d8d93446-bfb4-4c4b-9f5a-a8f02d6a2a8c` | 2026-08-20T11:18:17.989Z | FAILURE/consumer_ui_identity_contract_tdd_red | incident=`e5b7b620-9c45-4af5-83e7-79a55f91db94` | lesson_key=`consumer-ui-contract-identity-red` | event_sha256=`61a1716736b8471736c830ebc59c986d6f6684a7b7195284b2563742923e26b4`
- #6: `c4b6afcb-0b6c-40f9-9d3f-6303c52aeb7f` | 2026-08-20T11:27:11.639Z | REVIEW/consumer_projection_spec_review_not_ready | incident=`7fa0f137-3aaf-4fb7-b5dc-c2e8f1fdc55a` | lesson_key=`consumer-projection-server-authority-review` | event_sha256=`5e529463d6eaa4018181bbd4c513b744890aad08a6cc4c2d5daf7f05dae2160b`
- #7: `b4b7a44b-6b10-481e-98b3-5e8867808107` | 2026-08-20T11:30:28.822Z | FAILURE/consumer_ui_renderer_snapshot_validation_tdd_red | incident=`1e979c5a-7dba-4b9a-925e-3b7d0c00a2e8` | lesson_key=`consumer-ui-renderer-snapshot-red` | event_sha256=`3b4e1f26d285344cccdc996b0c6f8b8cfed138c2eab2e05f25cb4fdc0c3e74ea`
- #8: `f20f1597-5e1a-4b94-a09f-757aaaf2b81f` | 2026-08-20T11:31:34.350Z | REVIEW/consumer_ui_renderer_snapshot_validation_green | incident=`1e979c5a-7dba-4b9a-925e-3b7d0c00a2e8` | lesson_key=`consumer-ui-renderer-snapshot-red` | event_sha256=`1b67cf43d0dacfb7d3c64231c3915bf7a7023446d239d188ae0b6e35c4c853ed`
- #9: `6c842bfd-4721-4e32-8c30-64ebf6f650f4` | 2026-08-20T11:43:27.736Z | FAILURE/consumer_projection_direct_forgery_red | incident=`fe1f012e-76f5-49cb-baf9-17a602ff429f` | lesson_key=`consumer-projection-direct-forgery-red` | event_sha256=`524c335efa2b68a971919a908f13c3c774a391c2a2239e22e8fba4c4d6fef444`
- #10: `879cbb67-e787-4a71-9f76-2f236df1fa0e` | 2026-08-20T11:58:27.536Z | STATE_CHANGE/context_rescope_required | incident=`629acf4a-7933-408d-a584-6c823567cb1d` | lesson_key=`context-pack-rescope` | event_sha256=`95ea7bf764c7ce42299a02f1fadf825386daeca83e3349757f456f8bc5fae14b`
- #11: `cd78828c-4162-40f9-933d-4b65f750a389` | 2026-08-20T11:58:27.541Z | STATE_CHANGE/context_rescoped | incident=`fd712e3a-9ae8-493b-acce-7635ec2e7557` | lesson_key=`context-pack-rescope` | event_sha256=`e87d1791a4f022329a99718917aea4e80d7e4889b883775d0f803a4e5058361f`
- #12: `f3f75bd4-f41e-4f1b-a618-619c0176d43a` | 2026-08-20T12:12:43.723Z | FAILURE/family_result_binding_regression | incident=`3042bae2-8a44-42bf-97f6-084c4a160054` | lesson_key=`family-aware-result-binding-regression` | event_sha256=`44b9792a1adf1a58a30f3ad2640c20841ee89478dc0a92a64cb3d572915efd9b`
- #13: `d5e6f7a8-b9c0-41d2-e3f4-a5b6c7d8e9f0` | 2026-08-20T12:32:07.154Z | FAILURE/report_request_identity_boundary | incident=`e6f7a8b9-c0d1-42e3-f4a5-b6c7d8e9f0a1` | lesson_key=`report-request-identity-authority` | event_sha256=`d6fe068b8b82b37d5577a65b6b2de840b6e847c9b73a62473739933bf260811c`
- #14: `6be27120-ec9b-4392-8130-e33674aacb28` | 2026-08-20T12:34:56.997Z | REVIEW/consumer_source_authority_green | incident=`05dfc267-1214-428f-95d6-e4a766b82c0a` | lesson_key=`consumer-source-exact-authority` | event_sha256=`cc3ed1cdeb4f3ea8d611b162da9727368debfc33acf653679b5e70bd49307410`
- #15: `b8c2d6f0-1f25-4d8c-9b77-5a2e3c4d6f81` | 2026-08-20T12:44:59.523Z | FAILURE/consumer_private_raw_reader_red | incident=`c7d9e1f3-2a46-4b8c-9d10-6e5f4a3b2c18` | lesson_key=`consumer-private-raw-reader-boundary` | event_sha256=`3b31a4acdb4d97c20596062cadae5a35ee1b2d54295da720300cfdba9d18ad9d`
- #16: `5a9b9c1d-4ee7-4ca3-b7b5-3d4a5d7a9f21` | 2026-08-21T05:07:46.452Z | GATE/external_consumer_authority_gate | incident=`a8e0f9c1-6b75-4d2e-9f3a-1c5b7d8e0f42` | lesson_key=`external-host-transport-evidence` | event_sha256=`a8e223b1798d6a57edf46f96325b5dac1b614e36e470e004e3e3f0550b448712`
