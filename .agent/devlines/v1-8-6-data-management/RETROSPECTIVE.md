# Retrospective — v1-8-6-data-management

## Goal

# v1.8.6 S5 Data Management Objective  把已有 typed FeatureRecipe 与数据操作内核接入真实 API/UI/Graph，并提供可回溯、可拒绝的 merge/append/reshape/subset 工作流。  ## 必须完成  - FeatureRecipe 五个受限算子可从用户入口配置，产出 typed artifact、Graph 节点和 lineage。 - merge/append 对键冲突、多对多、异常行数膨胀 fail-closed。 - reshape 长宽转换显式记录输入、参数、行列变化和下游 identity 失效。 - subset 作为可追溯操作，不把临时 DataFrame 变成不可见状态。  ## 可证伪验收  - 真实 UI/API 链路：上传两表 → merge → reshape → derive → 建模，Graph 全链可见可回溯。 - merge 膨胀 fixture 被拒绝且给出可执行下一步。 - FeatureRecipe 节点点击不显示 \`missing_node_hash\`，并能下载/查看 typed payload。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 6/18 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=4; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-03T10:55:00.000Z `feature_recipe_entrypoint_red_before_implementation`; cause_status: `known`; cause: The initial S5 FeatureRecipe entrypoint test collected before the typed API and persistence seam existed.; resolution: `resolved`; lesson: Add the API/UI-facing typed operation test before implementing the data-management entrypoint.
- #6 2026-08-03T13:45:00.000Z `tdd_red_data_node_model_run_missing`; cause_status: `known`; cause: The S5 acceptance test exposed that data-operation nodes had no API endpoint capable of starting a real model run; the requested model-run path returned HTTP 404.; resolution: `open`; lesson: A data-operation Graph chain is not a model workflow until a typed user path dispatches the derived artifact into the existing run lifecycle and preserves source-node lineage.
- #9 2026-08-03T13:29:33.000Z `tdd_red_data_model_ui_missing`; cause_status: `known`; cause: The initial frontend red test showed that the new model-run API and data-node action were not yet exposed from the lineage data-operation drawer.; resolution: `resolved`; lesson: Every data-operation backend bridge needs a matching API contract test and Graph-node UI test before it can count as user-accessible.

## All errors

- #3 2026-08-03T12:45:10.000Z `pytest_collection_import_mismatch`; cause_status: `known`; cause: The default pytest collection mode found two v1.8.6 test modules with the same basename, so the quick gate stopped during collection before executing the backend suite.; resolution: `resolved`; lesson: Every pytest module added under nested test directories must have a repository-unique basename when the release gate uses default import mode.
- #7 2026-08-03T13:31:51.000Z `acceptance_fixture_below_model_minimum`; cause_status: `known`; cause: The expanded S5 Graph-chain acceptance initially dispatched only four reshape rows into the existing run lifecycle, which correctly blocked at the configured INSUFFICIENT_SAMPLE validation gate.; resolution: `resolved`; lesson: For acceptance tests that cross a real modeling lifecycle, satisfy the production sample gate and inspect the run errors artifact before changing production dispatch code.

## All gaps

- #10 2026-08-03T15:00:00.000Z `unowned_v186_data_test_paths`; cause_status: `known`; cause: The implementation added data-operation frontend and route tests, including a replacement of the legacy FeatureRecipe test, outside the frozen data-management allowlist.; resolution: `open`; lesson: A new data-operation test or replacement deletion must be assigned to the owning formal line before final verification.

## All waste

- None recorded.

## Root causes and solutions

- `data-bridge-needs-ui-entry`: occurrences=1; cause_status: `known`; root cause: The initial frontend red test showed that the new model-run API and data-node action were not yet exposed from the lineage data-operation drawer.; solution: `resolved`
- `data-chain-must-end-in-real-model-run`: occurrences=1; cause_status: `known`; root cause: The S5 acceptance test exposed that data-operation nodes had no API endpoint capable of starting a real model run; the requested model-run path returned HTTP 404.; solution: `open`
- `data-management-entrypoint-tdd`: occurrences=1; cause_status: `known`; root cause: The initial S5 FeatureRecipe entrypoint test collected before the typed API and persistence seam existed.; solution: `resolved`
- `data-test-paths-need-formal-owner`: occurrences=1; cause_status: `known`; root cause: The implementation added data-operation frontend and route tests, including a replacement of the legacy FeatureRecipe test, outside the frozen data-management allowlist.; solution: `open`
- `full-chain-fixture-must-clear-production-sample-gate`: occurrences=1; cause_status: `known`; root cause: The expanded S5 Graph-chain acceptance initially dispatched only four reshape rows into the existing run lifecycle, which correctly blocked at the configured INSUFFICIENT_SAMPLE validation gate.; solution: `resolved`
- `pytest-module-basenames-are-global`: occurrences=1; cause_status: `known`; root cause: The default pytest collection mode found two v1.8.6 test modules with the same basename, so the quick gate stopped during collection before executing the backend suite.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `data-bridge-needs-ui-entry`: line experience occurrence(s)=1
- `data-chain-must-end-in-real-model-run`: line experience occurrence(s)=1
- `data-management-entrypoint-tdd`: line experience occurrence(s)=1
- `data-test-paths-need-formal-owner`: line experience occurrence(s)=1
- `full-chain-fixture-must-clear-production-sample-gate`: line experience occurrence(s)=1
- `pytest-module-basenames-are-global`: line experience occurrence(s)=1

## Future guidance

- A data-operation Graph chain is not a model workflow until a typed user path dispatches the derived artifact into the existing run lifecycle and preserves source-node lineage.
- A new data-operation test or replacement deletion must be assigned to the owning formal line before final verification.
- Add the API/UI-facing typed operation test before implementing the data-management entrypoint.
- Data-operation acceptance must prove both the visible child-node chain and the downstream model rerun, not only preview/confirm API responses.
- Every data-operation backend bridge needs a matching API contract test and Graph-node UI test before it can count as user-accessible.
- Every pytest module added under nested test directories must have a repository-unique basename when the release gate uses default import mode.
- For acceptance tests that cross a real modeling lifecycle, satisfy the production sample gate and inspect the run errors artifact before changing production dispatch code.

## Event index

- #1: `141c0978-49cf-462b-b1cb-0afc29b3050a` | 2026-08-03T10:46:03.325Z | STATE_CHANGE/line_started | incident=`11334ccc-750c-4b64-8bc8-cf3b7dc7d7c1` | lesson_key=`frozen-context-before-start` | event_sha256=`41cc333908086dbf8e289ab95dde0f3f9295ad9c126cb8486374f0f2b1f074f6`
- #2: `c0d5f258-ab1d-4c3b-8e77-9a0f1b2c3d4e` | 2026-08-03T10:55:00.000Z | FAILURE/feature_recipe_entrypoint_red_before_implementation | incident=`d0c5f258-ab1d-4c3b-8e77-9a0f1b2c3d4e` | lesson_key=`data-management-entrypoint-tdd` | event_sha256=`355e057fae8fac58c69f5d84e9741d9e55bc5763b610b0e3a6f5803b893108de`
- #3: `c3d4e5f6-a7b8-49c0-1d2e-3f4a5b6c7d8e` | 2026-08-03T12:45:10.000Z | ERROR/pytest_collection_import_mismatch | incident=`d4e5f6a7-b8c9-40d1-2e3f-4a5b6c7d8e9f` | lesson_key=`pytest-module-basenames-are-global` | event_sha256=`9c6ed291ba6fb061b12f7cb2e465876e7e84285912c5ddb21bc020b7e20f6873`
- #4: `0c1bcb71-5e7f-4307-9f46-acf90eb85818` | 2026-08-03T13:18:14.906Z | STATE_CHANGE/context_rescope_required | incident=`3ac26612-810e-41fc-a1f1-397e222d8840` | lesson_key=`context-pack-rescope` | event_sha256=`f98a6a11f59aa3f053c08c5c56d4ba3881ba8ebe9e6e0fe72ebc7156a8f70d0d`
- #5: `c8ccd223-319e-4765-ab6c-96873ecbcb7b` | 2026-08-03T13:18:14.911Z | STATE_CHANGE/context_rescoped | incident=`1980bf67-eb0c-4b60-b371-be1e02551f38` | lesson_key=`context-pack-rescope` | event_sha256=`ef374c73a502d732e5c5b6601ac832bdd4795959430ccceccc77c9a145ce720c`
- #6: `d0e1f2a3-b4c5-46d7-e8f9-0123456789ab` | 2026-08-03T13:45:00.000Z | FAILURE/tdd_red_data_node_model_run_missing | incident=`e1f2a3b4-c5d6-47e8-f901-23456789abcd` | lesson_key=`data-chain-must-end-in-real-model-run` | event_sha256=`dea6966369d7815ee5116d98eb02db1e7191bc03270cd2e8b2930c0016aae097`
- #7: `e2f3a4b5-c6d7-48e9-9012-3456789abcde` | 2026-08-03T13:31:51.000Z | ERROR/acceptance_fixture_below_model_minimum | incident=`f3a4b5c6-d7e8-4901-2345-6789abcdef01` | lesson_key=`full-chain-fixture-must-clear-production-sample-gate` | event_sha256=`c2547ee63f13d1ba22f94c0269afbf7f48309e82569625017bdd0ed23de4c035`
- #8: `f4a5b6c7-d8e9-4012-3456-789abcdef012` | 2026-08-03T13:34:30.000Z | GATE/data_chain_model_green | incident=`a5b6c7d8-e9f0-4123-4567-89abcdef0123` | lesson_key=`full-data-chain-model-acceptance` | event_sha256=`9ef2665acc033aeabf67a7caee3183e7262e853d225d40552503e5ff9616aab4`
- #9: `a6b7c8d9-e0f1-4234-5678-9abcdef01234` | 2026-08-03T13:29:33.000Z | FAILURE/tdd_red_data_model_ui_missing | incident=`b7c8d9e0-f1a2-4345-6789-abcdef012345` | lesson_key=`data-bridge-needs-ui-entry` | event_sha256=`51ad597921209a80dd7dd43eff84c6eed2f47dc73163a9a47033953d40425910`
- #10: `b1c2d3e4-f5a6-4789-0123-456789abcdef` | 2026-08-03T15:00:00.000Z | GAP/unowned_v186_data_test_paths | incident=`c2d3e4f5-a6b7-4890-1234-56789abcdef0` | lesson_key=`data-test-paths-need-formal-owner` | event_sha256=`d27a399ff39171ab98f29255f7d9b08b687d2957852a4e31999d58f4cdacb483`
- #11: `b358a7c8-95fa-4b2d-a2f5-b9bd49c72b9a` | 2026-08-03T15:04:26.151Z | STATE_CHANGE/context_rescope_required | incident=`b904c5da-13da-4ab6-8cc0-c718fbd61067` | lesson_key=`context-pack-rescope` | event_sha256=`7fb7de6757e2b9e937334600efb13aa0071800184009b4072b74868dfe07e336`
- #12: `3caa352c-4c39-43cf-a8c3-0856b2664abd` | 2026-08-03T15:04:26.159Z | STATE_CHANGE/context_rescoped | incident=`ededc15f-43cd-4e33-8ae1-4c6db589b81b` | lesson_key=`context-pack-rescope` | event_sha256=`e61e3c358046d0f2f9ee42620ed5bac1eba79b788807f4854c9060e2a785d01c`
- #13: `48200392-cd47-46fb-82e1-f4ce7d669154` | 2026-08-03T15:05:55.422Z | STATE_CHANGE/context_rescope_required | incident=`eb9b7d48-e48e-4336-a678-326cf2b39610` | lesson_key=`context-pack-rescope` | event_sha256=`2c9c159d1e70fc51d13b5dc751fe9519b8cc1e90cc9d73a1d8e9a6f027019cb6`
- #14: `6f390cdf-370f-4e16-80cb-1a4019f9c54a` | 2026-08-03T15:05:55.431Z | STATE_CHANGE/context_rescoped | incident=`4431e3f7-2a91-40aa-b379-98ecbd1a76c9` | lesson_key=`context-pack-rescope` | event_sha256=`d07d958c782023fa89428476115265d22832883f8f389220b4efe8d7912cad84`
- #15: `f1a2b3c4-d5e6-4789-0123-abcdef012349` | 2026-08-03T15:21:02.000Z | GATE/data_operations_gate_passed | incident=`a2b3c4d5-e6f7-4890-1234-abcdef012350` | lesson_key=`data-browser-evidence-bounded` | event_sha256=`1d6578bd4b9717b1fce99dc13143624d0d4d5d8d5218b6512554ba2b0be21b0d`
- #16: `8be39474-072b-4ae6-ad51-99b871a6d3cc` | 2026-08-03T15:49:29.448Z | STATE_CHANGE/context_rescope_required | incident=`26d53d53-f48e-4f94-81be-9e1e5987789f` | lesson_key=`context-pack-rescope` | event_sha256=`3e2f7a851de3634136357a7310b9c2547a59a03bcea71a1a5718a073310200ef`
- #17: `7d944777-a10d-4027-a284-42a868657e92` | 2026-08-03T15:49:29.458Z | STATE_CHANGE/context_rescoped | incident=`7011bba5-7f2c-4253-816d-e53d68a88922` | lesson_key=`context-pack-rescope` | event_sha256=`1c5613353a1366db6161f8b6ddb4a4cd73141e14b55ebad7f0ed01050a76c050`
- #18: `0b1c2d3e-4f5a-6789-abcd-ef0123456789` | 2026-08-03T18:20:00.000Z | REVIEW/native_browser_data_chain_review | incident=`1c2d3e4f-5a6b-7890-abcd-ef0123456789` | lesson_key=`v186-browser-data-chain-verified` | event_sha256=`78ff65deb08cfd785cd10f6901c89df0fe6f35b6b40535eeae1aa57791250af0`
