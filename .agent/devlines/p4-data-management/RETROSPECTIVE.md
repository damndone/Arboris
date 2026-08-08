# Retrospective — p4-data-management

## Goal

# P4 Data Management Objective  At baseline \`ebba33f18037d3569f3d39dae8773b21a870e6e5\`, make the existing typed data-management executors reachable through the server-owned \`operation.multi_step@v1\` contract seam, with one live \`OperationDefinition\` per transformation and one shared feature-recipe definition.  The delivered scope is:  - \`data.merge\`, \`data.append\`, \`data.reshape\`, and \`data.subset\` as typed,   closed workflow-step proposals; - the five registered feature recipes through \`data.feature_recipe\`; - \`data.dedupe\`, \`data.rename\`, \`data.aggregate\`, \`data.fill_missing\`,   \`data.tsset\`, and \`data.lag\` as new closed workflow-step operations; - the closed subset operators \`eq\`, \`ne\`, \`gt\`, \`ge\`, \`lt\`, \`le\`, \`in\`,   \`not_in\`, \`between\`, \`is_missing\`, and \`not_missing\`, while retaining the   legacy \`equals\` form; - the chain-scoped, read-only \`list_project_datasets\` tool, which returns only   real \`(run_id, node_id, artifact_id)\` identities resolved from graph and   artifact-index state and never invents an identity; - declaration-driven proposal/editable schemas, vocabulary, capability   inventory, source/producer projections, validation, execution, graph child,   \`node_index\`, and lineage evidence; - a real workflow path in which a data transformation or recipe is followed by   \`model.genesis\` and the model reads the persisted transformed dataset.  Preserve the P0–P3 source commitment, fail-closed dependency, fingerprint, and capability semantics. Use one generic workflow-runtime data-operation executor selected by the trusted declaration seam; do not add an operation-specific four-way manual dispatch table to the orchestrator. Keep \`data.sort\`, arbitrary code execution, \`model.custom\`, frontend changes, browser/P7 work, push, PR, merge, tag, and release integration out of this line.  Evidence required before close: focused red-to-green TDD tests, declaration injection tests, hard-coded-replacement mutation failures, focused and relevant backend regressions, a fresh repository-root backend suite with only the two valid DID ignores, formal event verification and retrospective regeneration, and a local English commit.

## Final status

COMPLETED

## Metrics

- Failure frequency: 13/22 (59.1%; 59.1 per 100 events)
- Repeat rate: 0/13 (0.0%)
- Recurrence rate: 0/13 (0.0%)
- MTTR: median=0 ms (sample=12; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- #2 2026-08-08T22:43:57.000Z `tdd_red_before_p4_data_management`; cause_status: `known`; cause: The new P4 contract, data-operation, subset-filter, workflow-runtime, and dataset-discovery assertions are red at the verified P3 baseline because the requested declarations, execution paths, closed filters, and chain tool do not exist yet.; resolution: `accepted`; lesson: Freeze typed declarations and their red assertions before implementing the shared data-operation seam.
- #6 2026-08-08T23:18:46.000Z `branch_local_column_projection`; cause_status: `known`; cause: The first P0 lineage extension validated sibling source branches against one mutable global visible-column set; reshape changed that set and the later subset could no longer see scaled from first.; resolution: `resolved`; lesson: Compile column visibility from the declared source branch; sibling transforms must not mutate one another's schema context.
- #10 2026-08-08T23:18:50.000Z `exploration_return_regression`; cause_status: `known`; cause: While inserting the generic data-operation adapter, the existing exploration branch's return was temporarily displaced, causing P0 exploration results to become None.; resolution: `resolved`; lesson: Keep existing branch returns structurally adjacent to their branch and rerun the seam immediately after generic dispatch insertion.
- #12 2026-08-08T23:18:54.000Z `mutation_registry_projection`; cause_status: `known`; cause: A temporary hard-coded exclusion of p4_test.injected from STEP_PRODUCES_DATASET was introduced to test whether declaration injection reached the derived projection.; resolution: `resolved`; lesson: Declaration injection catches hard-coded projection sets when the test asserts every live derived view.
- #13 2026-08-08T23:18:56.000Z `mutation_lag_constant`; cause_status: `known`; cause: A temporary replacement of lag.shift with a constant zero series was introduced to test declaration-derived values.; resolution: `resolved`; lesson: Value-level assertions detect a hard-coded lag output even when output columns and persistence shape remain correct.
- #14 2026-08-08T23:19:10.000Z `mutation_dataset_detail_omission`; cause_status: `known`; cause: A temporary hard-coded false guard suppressed the unresolved detail check in list_project_datasets.; resolution: `resolved`; lesson: A bounded discovery tool must fail visibly for requested identities it cannot resolve rather than omit them.

## All errors

- #5 2026-08-08T23:18:45.000Z `formal_start_tag_rejected`; cause_status: `known`; cause: The first start invocation supplied dotted tag v1.8.8; the formal CLI rejected it before creating a line because tags must be normalized identifiers.; resolution: `resolved`; lesson: Use normalized identifier tags when starting a formal line and treat a rejected start as no line creation.
- #7 2026-08-08T23:18:47.000Z `runtime_source_field_leak`; cause_status: `known`; cause: The generic data-operation adapter forwarded the composition-only source commitment into DataTransformSpecV1.parameters, where the closed service schema correctly rejected it.; resolution: `resolved`; lesson: Strip composition-owned fields at the declaration/runtime boundary before constructing the typed service spec.
- #8 2026-08-08T23:18:48.000Z `runtime_compatibility_field_leak`; cause_status: `known`; cause: The generic adapter initially passed the workflow compatibility field source_artifact_fingerprint into the closed data-operation parameter map.; resolution: `resolved`; lesson: Keep compatibility and composition metadata outside the typed transformation parameter namespace.
- #9 2026-08-08T23:18:49.000Z `runtime_preview_count_field`; cause_status: `known`; cause: The generic adapter read DataTransformPreview.row_count even though the typed preview exposes row_count_before and row_count_after.; resolution: `resolved`; lesson: Use the exact typed preview fields at the service seam and retain before/after row evidence separately.
- #11 2026-08-08T23:18:51.000Z `dataset_tool_mapping_import`; cause_status: `known`; cause: The first dataset-discovery implementation referenced Mapping without importing it in context_tools.py.; resolution: `resolved`; lesson: Run the provider handler test, not only tool-definition projection tests, after adding a bounded evidence reader.
- #17 2026-08-08T23:52:00.000Z `registry_review_command_error`; cause_status: `known`; cause: The final registry smoke used a non-existent OperationRegistry.list_operations method and exited before completing the inventory assertion.; resolution: `resolved`; lesson: Inspect the live registry API before writing a final smoke query and treat a failed review command as an explicit process event.
- #20 2026-08-08T23:55:00.000Z `formal_review_event_rejected`; cause_status: `known`; cause: The first self-review event payload used unsupported preventability value not_applicable and the formal CLI rejected it before append.; resolution: `resolved`; lesson: Use the formal event vocabulary exactly and validate a review payload before treating it as recorded evidence.

## All gaps

- None recorded.

## All waste

- #18 2026-08-08T23:53:00.000Z `review_scan_scope_error`; cause_status: `known`; cause: The review grep included intentional negative-test assertions for data.sort, so the shell guard exited even though production implementation paths contained no data.sort registration.; resolution: `resolved`; lesson: Scope negative vocabulary scans to production paths and verify forbidden identities through the live registry assertions separately.

## Root causes and solutions

- `branch-local-schema-projection`: occurrences=1; cause_status: `known`; root cause: The first P0 lineage extension validated sibling source branches against one mutable global visible-column set; reshape changed that set and the later subset could no longer see scaled from first.; solution: `resolved`
- `execute-provider-handler-after-projection`: occurrences=1; cause_status: `known`; root cause: The first dataset-discovery implementation referenced Mapping without importing it in context_tools.py.; solution: `resolved`
- `formal-event-vocabulary`: occurrences=1; cause_status: `known`; root cause: The first self-review event payload used unsupported preventability value not_applicable and the formal CLI rejected it before append.; solution: `resolved`
- `formal-start-normalized-tags`: occurrences=1; cause_status: `known`; root cause: The first start invocation supplied dotted tag v1.8.8; the formal CLI rejected it before creating a line because tags must be normalized identifiers.; solution: `resolved`
- `mutation-derived-values`: occurrences=1; cause_status: `known`; root cause: A temporary replacement of lag.shift with a constant zero series was introduced to test declaration-derived values.; solution: `resolved`
- `mutation-live-projection`: occurrences=1; cause_status: `known`; root cause: A temporary hard-coded exclusion of p4_test.injected from STEP_PRODUCES_DATASET was introduced to test whether declaration injection reached the derived projection.; solution: `resolved`
- `mutation-no-silent-dataset-omission`: occurrences=1; cause_status: `known`; root cause: A temporary hard-coded false guard suppressed the unresolved detail check in list_project_datasets.; solution: `resolved`
- `p4-contract-first`: occurrences=1; cause_status: `known`; root cause: The new P4 contract, data-operation, subset-filter, workflow-runtime, and dataset-discovery assertions are red at the verified P3 baseline because the requested declarations, execution paths, closed filters, and chain tool do not exist yet.; solution: `accepted`
- `preserve-existing-branch-return`: occurrences=1; cause_status: `known`; root cause: While inserting the generic data-operation adapter, the existing exploration branch's return was temporarily displaced, causing P0 exploration results to become None.; solution: `resolved`
- `review-live-registry-api`: occurrences=1; cause_status: `known`; root cause: The final registry smoke used a non-existent OperationRegistry.list_operations method and exited before completing the inventory assertion.; solution: `resolved`
- `review-scan-production-scope`: occurrences=1; cause_status: `known`; root cause: The review grep included intentional negative-test assertions for data.sort, so the shell guard exited even though production implementation paths contained no data.sort registration.; solution: `resolved`
- `strip-composition-fields-at-adapter`: occurrences=1; cause_status: `known`; root cause: The generic data-operation adapter forwarded the composition-only source commitment into DataTransformSpecV1.parameters, where the closed service schema correctly rejected it.; solution: `resolved`
- `typed-adapter-parameter-boundary`: occurrences=1; cause_status: `known`; root cause: The generic adapter initially passed the workflow compatibility field source_artifact_fingerprint into the closed data-operation parameter map.; solution: `resolved`
- `typed-preview-field-fidelity`: occurrences=1; cause_status: `known`; root cause: The generic adapter read DataTransformPreview.row_count even though the typed preview exposes row_count_before and row_count_after.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `branch-local-schema-projection`: line experience occurrence(s)=1
- `execute-provider-handler-after-projection`: line experience occurrence(s)=1
- `formal-event-vocabulary`: line experience occurrence(s)=1
- `formal-start-normalized-tags`: line experience occurrence(s)=1
- `mutation-derived-values`: line experience occurrence(s)=1
- `mutation-live-projection`: line experience occurrence(s)=1
- `mutation-no-silent-dataset-omission`: line experience occurrence(s)=1
- `p4-contract-first`: line experience occurrence(s)=1
- `preserve-existing-branch-return`: line experience occurrence(s)=1
- `review-live-registry-api`: line experience occurrence(s)=1
- `review-scan-production-scope`: line experience occurrence(s)=1
- `strip-composition-fields-at-adapter`: line experience occurrence(s)=1
- `typed-adapter-parameter-boundary`: line experience occurrence(s)=1
- `typed-preview-field-fidelity`: line experience occurrence(s)=1

## Future guidance

- A bounded discovery tool must fail visibly for requested identities it cannot resolve rather than omit them.
- Compile column visibility from the declared source branch; sibling transforms must not mutate one another's schema context.
- Declaration injection catches hard-coded projection sets when the test asserts every live derived view.
- Freeze typed declarations and their red assertions before implementing the shared data-operation seam.
- Inspect the live registry API before writing a final smoke query and treat a failed review command as an explicit process event.
- Keep compatibility and composition metadata outside the typed transformation parameter namespace.
- Keep existing branch returns structurally adjacent to their branch and rerun the seam immediately after generic dispatch insertion.
- Keep the declaration seam, typed operation service, and persisted graph binding under one review boundary; report host-containment evidence separately from managed-terminal failures.
- Run the provider handler test, not only tool-definition projection tests, after adding a bounded evidence reader.
- Scope negative vocabulary scans to production paths and verify forbidden identities through the live registry assertions separately.
- Strip composition-owned fields at the declaration/runtime boundary before constructing the typed service spec.
- Use normalized identifier tags when starting a formal line and treat a rejected start as no line creation.
- Use the exact typed preview fields at the service seam and retain before/after row evidence separately.
- Use the formal event vocabulary exactly and validate a review payload before treating it as recorded evidence.
- Value-level assertions detect a hard-coded lag output even when output columns and persistence shape remain correct.

## Event index

- #1: `03603c3f-bcfa-42e1-90ae-a031c00d3b86` | 2026-08-08T22:28:47.300Z | STATE_CHANGE/line_started | incident=`3238b8da-8049-4c9e-a7ca-5c3169fc6b3c` | lesson_key=`frozen-context-before-start` | event_sha256=`7ed96275eb348935e74eedaccde4a9435d372e220c41b45802820e8e742742ae`
- #2: `1b5f8b57-04b9-4c5c-9e3a-0e2c1a3e4f61` | 2026-08-08T22:43:57.000Z | FAILURE/tdd_red_before_p4_data_management | incident=`d0f3d3c5-8f28-4f7e-9f29-7d2c1e4b6a80` | lesson_key=`p4-contract-first` | event_sha256=`1200d836566d162e69dbdb9e487fe4f3985b778cd490c112b3fe1ac7c4fcfdf0`
- #3: `4f3b34b3-c67f-4278-8127-74c45f310ef8` | 2026-08-08T23:07:11.539Z | STATE_CHANGE/context_rescope_required | incident=`9b0fb053-ef47-43ef-9ea3-adc3e1f2bc8f` | lesson_key=`context-pack-rescope` | event_sha256=`869eabc5016f7bc56f451d4721082b5c63627753f83bb5ff6db8495513b30142`
- #4: `da5f7cc0-19a9-4bac-bc98-0b5f66787867` | 2026-08-08T23:07:11.544Z | STATE_CHANGE/context_rescoped | incident=`d22ee219-ead3-4e4c-b3aa-34005ba0325b` | lesson_key=`context-pack-rescope` | event_sha256=`63438c6ff2e6e904c464287a90d58729cc5379b5a723ea70e10284444e08f136`
- #5: `0e1d2f3a-4b5c-46d7-8e9f-0a1b2c3d4e5f` | 2026-08-08T23:18:45.000Z | ERROR/formal_start_tag_rejected | incident=`1f2e3d4c-5b6a-47f8-9012-3a4b5c6d7e8f` | lesson_key=`formal-start-normalized-tags` | event_sha256=`8e84e9418909cb4d4545438c238b0f9ae6b1f3159911e7c8393845a4fae504d5`
- #6: `1a2b3c4d-5e6f-47a8-9b0c-1d2e3f4a5b6c` | 2026-08-08T23:18:46.000Z | FAILURE/branch_local_column_projection | incident=`2b3c4d5e-6f7a-48b9-0c1d-2e3f4a5b6c7d` | lesson_key=`branch-local-schema-projection` | event_sha256=`77cd842bb7ce99ab95c2f40dc24064b0114eb6498a176a6b0b32e322b68eb865`
- #7: `2b3c4d5e-6f7a-48b9-0c1d-2e3f4a5b6c7d` | 2026-08-08T23:18:47.000Z | ERROR/runtime_source_field_leak | incident=`3c4d5e6f-7a8b-49c0-1d2e-3f4a5b6c7d8e` | lesson_key=`strip-composition-fields-at-adapter` | event_sha256=`58774e9b11bc37a24407800d28ddea2aa8a6beda6defa2907d32e29674ca46b1`
- #8: `3c4d5e6f-7a8b-49c0-1d2e-3f4a5b6c7d8e` | 2026-08-08T23:18:48.000Z | ERROR/runtime_compatibility_field_leak | incident=`4d5e6f7a-8b9c-40d1-2e3f-4a5b6c7d8e9f` | lesson_key=`typed-adapter-parameter-boundary` | event_sha256=`b78e75f081d716d9cd2b032e0d260a53c165cd9462961f3d7e9504cf0b3ea160`
- #9: `4d5e6f7a-8b9c-40d1-2e3f-4a5b6c7d8e9f` | 2026-08-08T23:18:49.000Z | ERROR/runtime_preview_count_field | incident=`5e6f7a8b-9c0d-41e2-3f4a-5b6c7d8e9f0a` | lesson_key=`typed-preview-field-fidelity` | event_sha256=`af74458399ef24c83a5797225325ef838c1b96ff753a420e96c6f505ec7b7148`
- #10: `5e6f7a8b-9c0d-41e2-3f4a-5b6c7d8e9f0a` | 2026-08-08T23:18:50.000Z | FAILURE/exploration_return_regression | incident=`6f7a8b9c-0d1e-42f3-4a5b-6c7d8e9f0a1b` | lesson_key=`preserve-existing-branch-return` | event_sha256=`47a77d139c5487a5822afbcaa7d6b68e487ed062020826167461cf160af488ab`
- #11: `6f7a8b9c-0d1e-42f3-4a5b-6c7d8e9f0a1b` | 2026-08-08T23:18:51.000Z | ERROR/dataset_tool_mapping_import | incident=`7a8b9c0d-1e2f-43a4-5b6c-7d8e9f0a1b2c` | lesson_key=`execute-provider-handler-after-projection` | event_sha256=`21e575e6569412f65e27aacecda9b3cc6f20858f83d2cd7781186becc40a7b93`
- #12: `9c0d1e2f-3a4b-45c6-7d8e-9f0a1b2c3d4e` | 2026-08-08T23:18:54.000Z | FAILURE/mutation_registry_projection | incident=`abcde123-4567-48f9-9012-3456789abcde` | lesson_key=`mutation-live-projection` | event_sha256=`1d0272db1b450759c33e3c1d1380896485c7a8c171e62dcef38b04dc1a3f2987`
- #13: `bdef2345-6789-4abc-def0-123456789abc` | 2026-08-08T23:18:56.000Z | FAILURE/mutation_lag_constant | incident=`cdef2345-6789-4abc-def0-123456789abc` | lesson_key=`mutation-derived-values` | event_sha256=`83b63f9f606a123f21b051cde1c57acdf40d87b319823794d6d842c4518aca5c`
- #14: `cdef3456-789a-4bcd-ef01-23456789abcd` | 2026-08-08T23:19:10.000Z | FAILURE/mutation_dataset_detail_omission | incident=`def04567-89ab-4cde-f012-3456789abcde` | lesson_key=`mutation-no-silent-dataset-omission` | event_sha256=`bcaa1a003b82e75780c7aca01d638decb7e180f01b71339a6e5091415bdf98e6`
- #15: `ef012345-6789-4abc-def0-123456789abc` | 2026-08-08T23:32:00.000Z | GATE/full_backend_sandbox_containment | incident=`f0123456-789a-4bcd-ef01-23456789abcd` | lesson_key=`full-suite-host-containment-boundary` | event_sha256=`0c86d37bbc061598e157b84fb951842d8281cc58f34cc5c7121c9384cf798886`
- #16: `f1234567-89ab-4cde-f012-3456789abcde` | 2026-08-08T23:45:00.000Z | GATE/host_full_gate_passed | incident=`f0123456-789a-4bcd-ef01-23456789abcd` | lesson_key=`host-gate-closes-managed-containment-gap` | event_sha256=`db8dd5d22515c41a5e7277c1b40e1d68d850ae645d397eaf8b892dcc0db9b57a`
- #17: `01234567-89ab-4cde-f012-3456789abcde` | 2026-08-08T23:52:00.000Z | ERROR/registry_review_command_error | incident=`12345678-9abc-4def-0123-456789abcdef` | lesson_key=`review-live-registry-api` | event_sha256=`3a1abb9cc848674d0a2b9cf18dfd21c84e4895afcb752553755b6386025d9caf`
- #18: `23456789-abcd-4ef0-1234-56789abcdef0` | 2026-08-08T23:53:00.000Z | WASTE/review_scan_scope_error | incident=`3456789a-bcde-4f01-2345-6789abcdef01` | lesson_key=`review-scan-production-scope` | event_sha256=`7ba6a052a9d481d62001ed58fd0405c17d884a7876f41208d4aabb1778ccdd60`
- #19: `456789ab-cdef-4012-3456-789abcdef012` | 2026-08-08T23:54:00.000Z | REVIEW/p4_independent_self_review | incident=`56789abc-def0-4123-4567-89abcdef0123` | lesson_key=`p4-seam-review-boundary` | event_sha256=`da88b4680c2294d4ba15b3896aabf6286b1163eb6d9feb0e019ddde844e3c9d7`
- #20: `6789abcd-ef01-4234-5678-9abcdef01234` | 2026-08-08T23:55:00.000Z | ERROR/formal_review_event_rejected | incident=`789abcde-f012-4345-6789-abcdef012345` | lesson_key=`formal-event-vocabulary` | event_sha256=`84fe61f0140190abc7586e505c2fe9d56fe26632630be51b35cce548d6935d0a`
- #21: `89abcdef-0123-4456-789a-bcdef0123456` | 2026-08-08T23:57:00.000Z | GATE/p4_focused_relevant_green | incident=`9abcdef0-1234-4567-89ab-cdef01234567` | lesson_key=`p4-focused-gate-evidence` | event_sha256=`bf0f058cc60a1971428db87247695c9c4ffee2372713929c3e1bf93e6c193d23`
- #22: `abcdef01-2345-4678-9abc-def012345678` | 2026-08-08T23:58:00.000Z | STATE_CHANGE/p4_data_management_completed | incident=`bcdef012-3456-4789-abcd-ef0123456789` | lesson_key=`p4-closeout-evidence-boundary` | event_sha256=`611cb2d36fefd2b07b4c22ec5aa1876880de1744979b461d1b4a1ebc71d56eb0`
