# Retrospective — v1-8-6-crosscut-foundation

## Goal

# v1.8.6 S0 Cross-cutting Expansion Objective  基于已完成的 predictive-research foundation，先完成可追加的估计器注册面、模型族契约声明、 SampleSpec identity 接线和 legacy prediction 显式化。不得改变既有无权重模型数值。  ## 必须完成  1. 把 \`CORE_PACK\` 的注册与 handler/model-params 构造解耦；新增模型族只追加注册项。 2. 为 \`ModelFamilyContract\` 增加 \`allows_weights\` 与 \`supported_split_kinds\`，未声明能力    在拟合前 fail-closed。 3. 把 \`SampleSpecV1.content_hash()\` 接入 run identity、Graph identity 和缓存失效判定；    FeatureRecipe 结果 identity 不包含 SplitPlan，Evaluation/Prediction identity 必须包含。 4. 旧 \`run_prediction_model\` 明确标为历史重放 helper，显式声明 shuffle/cross-validation    语义，不再成为新 run 的隐式入口。  ## 可证伪验收  - 既有 golden 23 逐位 0-drift。 - 新模型族只需追加 registry entry 的结构测试通过。 - 未声明权重/split 的模型族稳定拒绝且不产生结果 artifact。 - 同一 SampleSpec 重复 identity 相同；改变 SplitPlan 参数产生新的评估 identity；改变无关   字段不会错误失效上游变换缓存。 - 旧 helper 的历史重放测试通过，新 run 路径没有调用它。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 11/26 (42.3%; 42.3 per 100 events)
- Repeat rate: 0/11 (0.0%)
- Recurrence rate: 0/11 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=8)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/6 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-03T09:42:07.000Z `tdd_red_s0_crosscut_contracts_identity_legacy`; cause_status: `known`; cause: The S0 red tests demonstrated three missing behaviors: ModelFamilyContract has no weight/split admission fields, SampleSpecV1 has no layered transformation/evaluation identity, and the legacy prediction helper has no explicit shuffle parameter or historical-only documentation.; resolution: `open`; lesson: For a cross-cutting refactor, write independent red tests for contract admission, identity layer semantics, and legacy entrypoint boundaries before editing production code.
- #3 2026-08-03T09:45:00.000Z `tdd_red_s0_packet_identity_not_persisted`; cause_status: `known`; cause: The packet-level red test showed that layered SampleSpec identity existed only as an in-memory contract and was not yet persisted into prediction/evaluation evidence payloads.; resolution: `open`; lesson: Identity contracts must be asserted at the persisted packet boundary, not only on their source dataclass properties.
- #4 2026-08-03T09:48:00.000Z `tdd_red_s0_graph_node_identity`; cause_status: `known`; cause: The graph identity red test showed that GraphRecorder and GraphStore had no node_hash field, so persisted lineage nodes could not carry the SampleSpec-derived identity needed for cache and evidence joins.; resolution: `open`; lesson: Lineage identity must be tested through the recorder and persistence boundary, including backward-compatible deserialization.
- #6 2026-08-03T09:52:00.000Z `tdd_red_s0_graph_identity_projection`; cause_status: `known`; cause: The prediction graph capture red test showed that layered packet identity was persisted but not projected onto any user-visible lineage node.; resolution: `open`; lesson: Persisted evidence and Graph projection are separate acceptance surfaces; test both before claiming identity is wired.
- #8 2026-08-03T09:58:00.000Z `tdd_red_s0_undeclared_capability_admission`; cause_status: `known`; cause: The contract declaration test showed that ModelFamilyContract exposed allows_weights and supported_split_kinds but validate_model_genesis_spec ignored declared weight_kind and split_kind fields, allowing undeclared capabilities through admission.; resolution: `open`; lesson: Adding capability fields to a contract is incomplete until the admission validator consumes them before execution.
- #10 2026-08-03T12:45:00.000Z `devline_rescope_validator_red`; cause_status: `known`; cause: The new governance test correctly failed because rescope_context rejected a concrete top-level backend/workbench Python file as too broad.; resolution: `resolved`; lesson: The governance validator must allow a concrete top-level Python file while continuing to reject broad backend/workbench directory scopes.

## All errors

- #7 2026-08-03T09:55:00.000Z `formal_rescope_direct_module_rejected`; cause_status: `known`; cause: The formal rescope command rejected the exact direct module path backend/workbench/graph_store.py as a too-broad boundary, and a child allow-path could not be checked because graph_store.py is a file rather than a directory.; resolution: `open`; lesson: Direct backend module paths must be admitted at line creation or the formal rescope validator must support exact file boundaries; do not bypass the scope gate with a fabricated child path.

## All gaps

- #5 2026-08-03T09:49:00.000Z `s0_persistence_scope_gap`; cause_status: `known`; cause: The graph roundtrip fix necessarily crosses backend/workbench/graph_store.py, which was omitted from the initial S0 frozen allowlist even though the objective requires persisted Graph identity.; resolution: `open`; lesson: Audit dependency seams before implementation and use formal rescope when a required persistence boundary was omitted.
- #16 2026-08-03T14:05:42.000Z `existing_line_scope_drift`; cause_status: `known`; cause: The existing v1-8-6 implementation line recorded changes in eight shared API, service, and UI files outside the line's then-frozen allowlist: backend/workbench/http/runs_routes.py, backend/workbench/services/run_service.py, frontend/src/api.ts, frontend/src/api.test.ts, frontend/src/lineage/drafts/GenesisWizard.tsx, frontend/src/lineage/drafts/GenesisWizard.test.tsx, frontend/src/workbench/views/TableView.tsx, and tests/test_api_run_params.py.; resolution: `open`; lesson: Shared API, service, and consumer files must be assigned to an owning development line before implementation begins; a later test pass does not retroactively make a frozen allowlist accurate.
- #19 2026-08-03T14:12:12.000Z `existing_line_scope_drift_resolved`; cause_status: `known`; cause: The eight paths identified in the scope-audit GAP are now explicitly owned by the predictive-research integration, weights-crosscut, or consumer-entries Context Packs; the crosscut Context Pack was formally rescope-frozen before extension work continued.; resolution: `resolved`; lesson: Resolve frozen-scope drift by recording explicit ownership and a new manifest identity before relying on shared API, service, or consumer changes.
- #21 2026-08-03T15:20:00.000Z `v186_scope_overlap_and_unowned_seams`; cause_status: `known`; cause: A post-implementation ownership audit found multiple v1.8.6 Context Packs claiming the same shared files, while several required seam files had no exclusive owner. The implementation is testable, but the formal line boundary is not yet independently auditable.; resolution: `open`; lesson: Run an exclusive path-ownership audit before closing parallel feature lines, then rescope through the formal CLI with complete replacement scopes.

## All waste

- None recorded.

## Root causes and solutions

- `concrete-top-level-scope-is-explicit`: occurrences=1; cause_status: `known`; root cause: The new governance test correctly failed because rescope_context rejected a concrete top-level backend/workbench Python file as too broad.; solution: `resolved`
- `formal-rescope-direct-module-boundary`: occurrences=1; cause_status: `known`; root cause: The formal rescope command rejected the exact direct module path backend/workbench/graph_store.py as a too-broad boundary, and a child allow-path could not be checked because graph_store.py is a file rather than a directory.; solution: `open`
- `s0-contract-fields-must-drive-admission`: occurrences=1; cause_status: `known`; root cause: The contract declaration test showed that ModelFamilyContract exposed allows_weights and supported_split_kinds but validate_model_genesis_spec ignored declared weight_kind and split_kind fields, allowing undeclared capabilities through admission.; solution: `open`
- `s0-graph-node-identity-roundtrip`: occurrences=1; cause_status: `known`; root cause: The graph identity red test showed that GraphRecorder and GraphStore had no node_hash field, so persisted lineage nodes could not carry the SampleSpec-derived identity needed for cache and evidence joins.; solution: `open`
- `s0-graph-projection-identity`: occurrences=1; cause_status: `known`; root cause: The prediction graph capture red test showed that layered packet identity was persisted but not projected onto any user-visible lineage node.; solution: `open`
- `s0-persist-layered-identity-at-packet-boundary`: occurrences=1; cause_status: `known`; root cause: The packet-level red test showed that layered SampleSpec identity existed only as an in-memory contract and was not yet persisted into prediction/evaluation evidence payloads.; solution: `open`
- `s0-red-tests-before-crosscut-code`: occurrences=1; cause_status: `known`; root cause: The S0 red tests demonstrated three missing behaviors: ModelFamilyContract has no weight/split admission fields, SampleSpecV1 has no layered transformation/evaluation identity, and the legacy prediction helper has no explicit shuffle parameter or historical-only documentation.; solution: `open`
- `s0-rescope-persistence-boundary`: occurrences=1; cause_status: `known`; root cause: The graph roundtrip fix necessarily crosses backend/workbench/graph_store.py, which was omitted from the initial S0 frozen allowlist even though the objective requires persisted Graph identity.; solution: `open`
- `scope-ownership-audit-closed-before-implementation`: occurrences=1; cause_status: `known`; root cause: The eight paths identified in the scope-audit GAP are now explicitly owned by the predictive-research integration, weights-crosscut, or consumer-entries Context Packs; the crosscut Context Pack was formally rescope-frozen before extension work continued.; solution: `resolved`
- `scope-ownership-before-shared-file-edit`: occurrences=1; cause_status: `known`; root cause: The existing v1-8-6 implementation line recorded changes in eight shared API, service, and UI files outside the line's then-frozen allowlist: backend/workbench/http/runs_routes.py, backend/workbench/services/run_service.py, frontend/src/api.ts, frontend/src/api.test.ts, frontend/src/lineage/drafts/GenesisWizard.tsx, frontend/src/lineage/drafts/GenesisWizard.test.tsx, frontend/src/workbench/views/TableView.tsx, and tests/test_api_run_params.py.; solution: `open`
- `v186-exclusive-path-ownership-audit`: occurrences=1; cause_status: `known`; root cause: A post-implementation ownership audit found multiple v1.8.6 Context Packs claiming the same shared files, while several required seam files had no exclusive owner. The implementation is testable, but the formal line boundary is not yet independently auditable.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `concrete-top-level-scope-is-explicit`: line experience occurrence(s)=1
- `formal-rescope-direct-module-boundary`: line experience occurrence(s)=1
- `s0-contract-fields-must-drive-admission`: line experience occurrence(s)=1
- `s0-graph-node-identity-roundtrip`: line experience occurrence(s)=1
- `s0-graph-projection-identity`: line experience occurrence(s)=1
- `s0-persist-layered-identity-at-packet-boundary`: line experience occurrence(s)=1
- `s0-red-tests-before-crosscut-code`: line experience occurrence(s)=1
- `s0-rescope-persistence-boundary`: line experience occurrence(s)=1
- `scope-ownership-audit-closed-before-implementation`: line experience occurrence(s)=1
- `scope-ownership-before-shared-file-edit`: line experience occurrence(s)=1
- `v186-exclusive-path-ownership-audit`: line experience occurrence(s)=1

## Future guidance

- Adding capability fields to a contract is incomplete until the admission validator consumes them before execution.
- Audit dependency seams before implementation and use formal rescope when a required persistence boundary was omitted.
- Direct backend module paths must be admitted at line creation or the formal rescope validator must support exact file boundaries; do not bypass the scope gate with a fabricated child path.
- For a cross-cutting refactor, write independent red tests for contract admission, identity layer semantics, and legacy entrypoint boundaries before editing production code.
- Identity contracts must be asserted at the persisted packet boundary, not only on their source dataclass properties.
- Lineage identity must be tested through the recorder and persistence boundary, including backward-compatible deserialization.
- Persisted evidence and Graph projection are separate acceptance surfaces; test both before claiming identity is wired.
- Resolve frozen-scope drift by recording explicit ownership and a new manifest identity before relying on shared API, service, or consumer changes.
- Run an exclusive path-ownership audit before closing parallel feature lines, then rescope through the formal CLI with complete replacement scopes.
- Shared API, service, and consumer files must be assigned to an owning development line before implementation begins; a later test pass does not retroactively make a frozen allowlist accurate.
- The governance validator must allow a concrete top-level Python file while continuing to reject broad backend/workbench directory scopes.

## Event index

- #1: `16ab850c-cbb4-46e1-a792-f5dab3461de5` | 2026-08-03T09:39:14.231Z | STATE_CHANGE/line_started | incident=`70375217-7841-4718-9216-3583ff381868` | lesson_key=`frozen-context-before-start` | event_sha256=`a6399d4e8a90643dcb3b2c80b998e46c5c3ff48c91e86d6042712bd81b0c64a4`
- #2: `9abcdef0-1234-4567-89ab-cdef01234567` | 2026-08-03T09:42:07.000Z | FAILURE/tdd_red_s0_crosscut_contracts_identity_legacy | incident=`abcdef01-2345-4678-9abc-def012345678` | lesson_key=`s0-red-tests-before-crosscut-code` | event_sha256=`d0724fbce6920607a671b008ab8c392f8c8fcfd998f290e2d6e9f53ed165aa3f`
- #3: `bcdef012-3456-4789-abcd-ef0123456789` | 2026-08-03T09:45:00.000Z | FAILURE/tdd_red_s0_packet_identity_not_persisted | incident=`cdef0123-4567-489a-bcde-f0123456789a` | lesson_key=`s0-persist-layered-identity-at-packet-boundary` | event_sha256=`eec7bcf8645ffc313712158427be131c05dd8538710924ce211429c6686ce1bb`
- #4: `cdef0123-4567-489a-bcde-f0123456789a` | 2026-08-03T09:48:00.000Z | FAILURE/tdd_red_s0_graph_node_identity | incident=`def01234-5678-49ab-cdef-0123456789ab` | lesson_key=`s0-graph-node-identity-roundtrip` | event_sha256=`9d67fbb22acaca6ea9d82d99e1bd580860283c8fc893a7a265dcbe93d33f164a`
- #5: `def01234-5678-49ab-cdef-0123456789ab` | 2026-08-03T09:49:00.000Z | GAP/s0_persistence_scope_gap | incident=`ef012345-6789-4abc-def0-123456789abc` | lesson_key=`s0-rescope-persistence-boundary` | event_sha256=`b6f8112761ed96cc740f63428e39fec0969154cf6248f3163650df73bc9f37a2`
- #6: `ef012345-6789-4abc-def0-123456789abc` | 2026-08-03T09:52:00.000Z | FAILURE/tdd_red_s0_graph_identity_projection | incident=`f0123456-789a-4bcd-ef01-23456789abcd` | lesson_key=`s0-graph-projection-identity` | event_sha256=`fd6461379380308644817775921d77861e26e7a99926d6f6e8a10d2c344f9dbe`
- #7: `f0123456-789a-4bcd-ef01-23456789abcd` | 2026-08-03T09:55:00.000Z | ERROR/formal_rescope_direct_module_rejected | incident=`01234567-89ab-4cde-f012-3456789abcde` | lesson_key=`formal-rescope-direct-module-boundary` | event_sha256=`b874cb5887594025f922319c41d483ced6e8658d690e8a9c81ceab2920fbb828`
- #8: `01234567-89ab-4cde-f012-3456789abcde` | 2026-08-03T09:58:00.000Z | FAILURE/tdd_red_s0_undeclared_capability_admission | incident=`12345678-9abc-4def-0123-456789abcdef` | lesson_key=`s0-contract-fields-must-drive-admission` | event_sha256=`64d7408a5df4644cf5f05a38980addc2fba39df4bf537538234c6ee193510100`
- #9: `3456789a-bcde-4f01-2345-6789abcdef01` | 2026-08-03T10:02:00.000Z | GATE/s0_crosscut_green | incident=`abcdef01-2345-4678-9abc-def012345678` | lesson_key=`s0-crosscut-foundation-green` | event_sha256=`ce9888f80f97fc5d025bd865a2fe0410a9ab3fd01d59c6fd7a34e847a338e7d0`
- #10: `a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c` | 2026-08-03T12:45:00.000Z | FAILURE/devline_rescope_validator_red | incident=`b2c3d4e5-f6a7-48b9-0c1d-2e3f4a5b6c7d` | lesson_key=`concrete-top-level-scope-is-explicit` | event_sha256=`52ffdf41f66a3d12985575a6339007cfdecb713b2fbb7c1e9f9ec5b9654f8f56`
- #11: `f6a7b8c9-d0e1-42f3-a4b5-c6d7e8f90123` | 2026-08-03T13:20:00.000Z | GATE/quick_gate_host_sandbox_unavailable | incident=`a7b8c9d0-e1f2-43a4-b5c6-d7e8f9012345` | lesson_key=`sandbox-discovery-is-not-launch-verification` | event_sha256=`09b49ec4b16a3cbc5ed049bc56f5c87d4a65eb2945ea5096806e8120a257a4f4`
- #12: `a8b9c0d1-e2f3-44a5-b6c7-d8e9f0123456` | 2026-08-03T13:35:00.000Z | GATE/sandbox_containment_host_reverified | incident=`b9c0d1e2-f3a4-45b6-c7d8-e9f012345678` | lesson_key=`host-containment-gate-must-be-supported-host-verified` | event_sha256=`b9737a5cc25718769cec56091f19b40b732957f7213610ba12e31a6c19b5c773`
- #13: `9718e6f7-7af3-456b-b30a-b16ad7d69691` | 2026-08-03T13:17:27.276Z | STATE_CHANGE/context_rescope_required | incident=`2c61780f-ef25-4f4a-aef2-dabe1561e48e` | lesson_key=`context-pack-rescope` | event_sha256=`5a567a1e1a7c6426480b1dc2c64f17c975f672b0dc654f1017ae770665b69cca`
- #14: `552d1161-0fb2-4126-b76d-169f36929a01` | 2026-08-03T13:17:27.285Z | STATE_CHANGE/context_rescoped | incident=`4e12970b-dc93-4355-8ecd-59ad34bbf88d` | lesson_key=`context-pack-rescope` | event_sha256=`bc82950409fb681066e1f95ab1be1829c0d956b2b242d571a78219bb3851ce27`
- #15: `b8c9d0e1-f2a3-4456-7890-abcdef012345` | 2026-08-03T13:58:00.000Z | GATE/final_host_gate_green | incident=`c9d0e1f2-a3b4-4567-8901-23456789abcd` | lesson_key=`final-host-gate-is-current-release-evidence` | event_sha256=`9242a3ca7bf3b61e5ec6a22567ccc4de2a2f297049164214ac249b43e2706023`
- #16: `e1f2a3b4-c5d6-4789-0123-456789abcdef` | 2026-08-03T14:05:42.000Z | GAP/existing_line_scope_drift | incident=`f2a3b4c5-d6e7-4890-1234-56789abcdef0` | lesson_key=`scope-ownership-before-shared-file-edit` | event_sha256=`5b6967b6a1042a5662ed5b7f9971baf8708a9709882a1962becfc38e4a92c191`
- #17: `3cefd29a-d30b-4c89-8651-8a1c72a6b043` | 2026-08-03T14:07:17.553Z | STATE_CHANGE/context_rescope_required | incident=`264f8bfa-2f31-4603-9756-6fb502860bf5` | lesson_key=`context-pack-rescope` | event_sha256=`f5233c4485d444d435f358c4dacac447029ebc68d721f481418af2248c0bbe60`
- #18: `709663f6-e291-4180-bde8-1c9709404c09` | 2026-08-03T14:07:17.566Z | STATE_CHANGE/context_rescoped | incident=`5a925a15-ce60-43b6-9e65-697983797864` | lesson_key=`context-pack-rescope` | event_sha256=`223f410f246a58a98d4aebf66ff094d84641e3e7c1ec71cc6bed6c1e430fa271`
- #19: `f4a5b6c7-d8e9-4012-3456-789abcdef012` | 2026-08-03T14:12:12.000Z | GAP/existing_line_scope_drift_resolved | incident=`a5b6c7d8-e9f0-4123-4567-89abcdef0123` | lesson_key=`scope-ownership-audit-closed-before-implementation` | event_sha256=`c095746f857fa6de87ef84aaf6ed4716675528b172e0e8f43222bcdf2c416ff1`
- #20: `b7c8d9e0-f1a2-4345-6789-abcdef012345` | 2026-08-03T15:21:00.000Z | GATE/full_gate_passed | incident=`c8d9e0f1-a2b3-4456-7890-abcdef012346` | lesson_key=`full-gate-evidence-separate` | event_sha256=`6de2222a3fb07ce59ab1264d05f56847155ae0bded32b1126c88fef8123402dc`
- #21: `42c2335e-c128-42d0-9257-82c1b05bd1bb` | 2026-08-03T15:20:00.000Z | GAP/v186_scope_overlap_and_unowned_seams | incident=`825600fe-f5b4-4393-941d-a51aac493d83` | lesson_key=`v186-exclusive-path-ownership-audit` | event_sha256=`dc39c359d65d0307ef59d0fa00ea30acefb9466997ea0e43e9814869cd29fca7`
- #22: `a6eeb13b-f328-4c68-9cdf-953a953088b0` | 2026-08-03T15:49:28.691Z | STATE_CHANGE/context_rescope_required | incident=`504bb74d-68c2-4544-8053-28eb717d3120` | lesson_key=`context-pack-rescope` | event_sha256=`3a6af14884f51c32231b3d8bae92a0f1bfb709cc55ee8cc1ee35da084ac13aba`
- #23: `857dc520-ddd6-415c-a11e-e773d4834005` | 2026-08-03T15:49:28.705Z | STATE_CHANGE/context_rescoped | incident=`eb0ac5aa-8473-41d6-a578-b772b907e771` | lesson_key=`context-pack-rescope` | event_sha256=`dba142dbe29682efc8b2f6ba83fd8d9345160e1b24b4e841f53ad471ef383e9b`
- #24: `490c9dbf-5261-459a-b98e-f9ee17a389a2` | 2026-08-03T15:50:05.154Z | STATE_CHANGE/context_rescope_required | incident=`8076b38a-6dce-4cba-9d03-63fcd914bb23` | lesson_key=`context-pack-rescope` | event_sha256=`843cdb78245aab1b9762544b2e27a375b8b1b9ee6ce3fda2ad58f3af9c91edd3`
- #25: `e21110af-c65c-4aef-ae6a-bbf0da951fc2` | 2026-08-03T15:50:05.170Z | STATE_CHANGE/context_rescoped | incident=`22092069-896a-4763-ad77-29d02692f4e9` | lesson_key=`context-pack-rescope` | event_sha256=`79360e9d0f7ab9b2dc924432d404e946203fbbd90e530000053e240cb4046253`
- #26: `f9a6b7c8-d901-4e23-8567-9a0b1c2d3e4f` | 2026-08-03T18:31:52.300Z | GATE/full_gate_passed_after_collection_fix | incident=`0a1b2c3d-4e5f-6789-abcd-ef0123456789` | lesson_key=`v186-full-gate-after-collection-fix` | event_sha256=`7daab66399835ebbd22e8cc3779ddd1dbe481b5f3040bfbe15eaac63e4e72e21`
