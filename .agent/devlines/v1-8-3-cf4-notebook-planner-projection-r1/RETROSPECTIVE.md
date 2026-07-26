# Retrospective — v1-8-3-cf4-notebook-planner-projection-r1

## Goal

# v1.8.3 CF4 Notebook planner projection  让真实 Notebook planner 能读取服务器拥有的、已准入 capability 的最小只读声明， 而不是只读取原生 \`build_capabilities()\`；同一份声明同时提供 capability 的 bounded artifact vocabulary，供 NotebookPlanningAgent 和 NotebookService 使用。  CapabilityBindingCatalog 只输出 server-owned planner projection：capability id、 受限 planner metadata 和 artifact id/type，不输出 raw binding、entrypoint、路径、 依赖包或 authority 内部记录。projection 必须在生成前经过当前 binding verifier 和 scope 检查；binding 无效时不得出现在 planner catalog。Agent 仍只能提出 typed option， service 仍必须再次解析并钉住 binding；\`materialize_only\`、execution_allowed=false、 proposal/risk authorization 和既有原生路径保持不变。  完成标准：  - custom capability 可通过受信 projection 出现在真实 planner catalog； - planner 的 artifact contract 与 service 的 artifact validation 使用同一 bounded projection； - projection 缺失、越界、失效或伪造字段 fail closed； - 原生 capability、旧 Notebook contract、HTTP route 和命名 gate 不回归； - 不新增 HTTP 注册、依赖安装、代码执行、confirm_and_execute 或自动执行面。

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/15 (26.7%; 26.7 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=4; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-07-26T22:50:00.000Z `tdd_red_before_planner_projection`; cause_status: `known`; cause: The real planner projection test requires the not-yet-created server-owned planner_projection registration seam.; resolution: `resolved`; lesson: Write the real planner projection test before adding dynamic declarations or artifact vocabulary.
- #4 2026-07-26T22:58:01.000Z `planner_projection_input_normalization`; cause_status: `known`; cause: A malformed planner projection adapter list escaped the validator as a native TypeError, and nested parameter values were initially accepted without a strict DTO boundary.; resolution: `resolved`; lesson: Normalize every Agent-facing projection input into a small bounded DTO and convert malformed values into the catalog's typed rejection.
- #5 2026-07-26T22:59:01.000Z `revalidation_skipped_current_binding`; cause_status: `known`; cause: The Notebook revalidation path prepared a bound option without resolving and comparing its current server-owned binding first, and dynamic artifact lookup did not carry Notebook scope.; resolution: `resolved`; lesson: Revalidation must preserve the same current binding identity and pass the Notebook scope through every dynamic capability lookup.
- #12 2026-07-26T23:12:01.000Z `consumer_admission_fixture_mismatch`; cause_status: `known`; cause: Adding the explicit Notebook option planner consumer slot correctly rejected an admission fixture whose Adapter declared only report projection support.; resolution: `resolved`; lesson: A consumer admission grant must be declared consistently by the profile, implementation, adapter, and scoped admission; never bypass the mismatch in tests or runtime.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `bounded-planner-projection-inputs`: occurrences=1; cause_status: `known`; root cause: A malformed planner projection adapter list escaped the validator as a native TypeError, and nested parameter values were initially accepted without a strict DTO boundary.; solution: `resolved`
- `consumer-admission-facts-align-across-contracts`: occurrences=1; cause_status: `known`; root cause: Adding the explicit Notebook option planner consumer slot correctly rejected an admission fixture whose Adapter declared only report projection support.; solution: `resolved`
- `scope-aware-bound-option-revalidation`: occurrences=1; cause_status: `known`; root cause: The Notebook revalidation path prepared a bound option without resolving and comparing its current server-owned binding first, and dynamic artifact lookup did not carry Notebook scope.; solution: `resolved`
- `tdd-red-before-planner-projection`: occurrences=1; cause_status: `known`; root cause: The real planner projection test requires the not-yet-created server-owned planner_projection registration seam.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `bounded-planner-projection-inputs`: line experience occurrence(s)=1
- `consumer-admission-facts-align-across-contracts`: line experience occurrence(s)=1
- `scope-aware-bound-option-revalidation`: line experience occurrence(s)=1
- `tdd-red-before-planner-projection`: line experience occurrence(s)=1

## Future guidance

- A consumer admission grant must be declared consistently by the profile, implementation, adapter, and scoped admission; never bypass the mismatch in tests or runtime.
- Agent-facing capability metadata must be a strict DTO and every planner, artifact, and revalidation lookup must recheck current scope and permission facts.
- Close a planner consumer seam only after both discovery and write-time paths enforce the same authority, scope, consumer, identity, and artifact facts.
- Normalize every Agent-facing projection input into a small bounded DTO and convert malformed values into the catalog's typed rejection.
- Revalidation must preserve the same current binding identity and pass the Notebook scope through every dynamic capability lookup.
- Write the real planner projection test before adding dynamic declarations or artifact vocabulary.

## Event index

- #1: `f7c1d99a-ba56-48d0-8672-cc4088bac43b` | 2026-07-26T22:39:55.943Z | STATE_CHANGE/line_started | incident=`2c99cdc2-46ab-4d6d-95fc-fb88bf65a985` | lesson_key=`frozen-context-before-start` | event_sha256=`5b22fd3d661ce131685eda0eeb6ae6a0366ebd571544c887cddc9116f48a6e06`
- #2: `1e6b4c8d-2f70-4a59-b3c1-7d8e0f5a9246` | 2026-07-26T22:50:00.000Z | FAILURE/tdd_red_before_planner_projection | incident=`a4c8e2f6-9b1d-47e5-80c3-6f7a2d9e5b14` | lesson_key=`tdd-red-before-planner-projection` | event_sha256=`c6698cef461cc86251d6ede463fe162785749c82e3d6f2216a0a5932de418f3d`
- #3: `2d1b6a0f-cc86-47ca-89c0-2e0cce91f6de` | 2026-07-26T22:57:01.000Z | REVIEW/planner_projection_security_gaps | incident=`71a019d6-1715-49e1-97b4-df7d16aa7c8e` | lesson_key=`strict-planner-projection-authority-boundary` | event_sha256=`669ebb8635efc1a02808b338d76a8af3be24ccf859e728a62af1bf82225142d1`
- #4: `3a7f0fd9-b19b-4d6b-a1dc-77ad14fa56f0` | 2026-07-26T22:58:01.000Z | FAILURE/planner_projection_input_normalization | incident=`420405d2-2cb4-486f-95ea-278f14a5fce6` | lesson_key=`bounded-planner-projection-inputs` | event_sha256=`a405600264020a678f6002630790a9f7a2883378ee7f8ef837bcb5b77b981729`
- #5: `83ebf263-0b7f-485f-b91f-0b4870e49d2a` | 2026-07-26T22:59:01.000Z | FAILURE/revalidation_skipped_current_binding | incident=`f262b513-9e13-41c0-bba2-ae16454428d8` | lesson_key=`scope-aware-bound-option-revalidation` | event_sha256=`aafc13ba2553f25c2d598f40bd836c88d35143a32927e6404d31bd4ee77bda35`
- #6: `1212fe85-aa4e-4609-a507-bc4b2a6e7532` | 2026-07-26T23:07:24.120Z | STATE_CHANGE/context_rescope_required | incident=`fdc5e997-5b00-45f0-93e3-37595fc80733` | lesson_key=`context-pack-rescope` | event_sha256=`8d62c512e123893d47dbf9ded5d65bf816b5cf82f8d5cc987071267e6095798d`
- #7: `8bb7263f-29e5-415a-8f9e-5e1d24cda708` | 2026-07-26T23:07:24.125Z | STATE_CHANGE/context_rescoped | incident=`3d85ed15-0c48-4472-857c-5cc1958cc73a` | lesson_key=`context-pack-rescope` | event_sha256=`9cec9eb1d82be1ced600f329d5f2c1853affc82f7e00f2ee0c38ba29a4074741`
- #8: `ecd469cb-d8b5-4e58-911d-6699ec4941f7` | 2026-07-26T23:07:39.450Z | STATE_CHANGE/context_rescope_required | incident=`ebce8d3b-cba6-4d4c-b9b0-ef844639c803` | lesson_key=`context-pack-rescope` | event_sha256=`b23772e6e433c0228823732f552b4467462f662f8d10ff9a203a41506cda69d1`
- #9: `b0b67fb9-5b3f-4d35-9654-0b155c5df7ec` | 2026-07-26T23:07:39.456Z | STATE_CHANGE/context_rescoped | incident=`47102dd7-7298-4a44-b4ea-11f71bab5a85` | lesson_key=`context-pack-rescope` | event_sha256=`022230c344ee988c90ff6698f1fdddbf3783fc357a390c0980f9b6cd6749c38e`
- #10: `19c0b42a-d8d6-4db1-b212-a344fa1df8f3` | 2026-07-26T23:09:42.206Z | STATE_CHANGE/context_rescope_required | incident=`f7fa416e-4e3b-4b4d-b60d-3800b80479b6` | lesson_key=`context-pack-rescope` | event_sha256=`c81e824c6b77da33a9f6f073f07e449de14d24834f9e9472497ca6fdde443edb`
- #11: `c0d6fc59-8f73-4b6c-9f77-1e1b912c0669` | 2026-07-26T23:09:42.212Z | STATE_CHANGE/context_rescoped | incident=`fc494aac-6673-4d23-a737-06e8a4d96bbe` | lesson_key=`context-pack-rescope` | event_sha256=`bb4780c743121ffae5e22caed62e0f1e4747877a24b0f1751f2dd1c0da810de5`
- #12: `1ab3f91e-2f49-4be4-8f0d-0b5e72b7d4b9` | 2026-07-26T23:12:01.000Z | FAILURE/consumer_admission_fixture_mismatch | incident=`9d90bcb4-509f-4e0c-a18f-daa6df3aaf2a` | lesson_key=`consumer-admission-facts-align-across-contracts` | event_sha256=`0140f733ae44644babbfb46ff0332ad3a7b059bca4f2d36569c9d174f4b3d9e0`
- #13: `f3e2c1b0-8a79-46d5-b4c3-2e1f0a9d8c7b` | 2026-07-26T23:14:01.000Z | REVIEW/planner_projection_review_accepted | incident=`6c5b4a39-2817-4e0d-9f8a-7b6c5d4e3f2a` | lesson_key=`planner-consumer-seam-reviewed` | event_sha256=`80b26c168127958199738e19f6be39c8f4649f75f4ec503ddc6e798c93334793`
- #14: `a9b8c7d6-e5f4-4321-9a8b-7c6d5e4f3a2b` | 2026-07-26T23:15:01.000Z | GATE/planner_projection_targeted_gate | incident=`b8c7d6e5-f4a3-4210-9b8c-7d6e5f4a3b2c` | lesson_key=`planner-projection-focused-gate` | event_sha256=`f2cd3660df91002680c4b2bb6dae93b170d5c3e6c169db600759502606711637`
- #15: `c7d6e5f4-a3b2-4109-8c7d-6e5f4a3b2c1d` | 2026-07-26T23:16:01.000Z | STATE_CHANGE/planner_projection_completed | incident=`d6e5f4a3-b2c1-4098-7d6e-5f4a3b2c1d0e` | lesson_key=`planner-projection-slice-boundary` | event_sha256=`597cb4cc9c0bb9dfd5cef98954c3d5dc1429c542e7ff22e1029baf4992844fad`
