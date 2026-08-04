# Retrospective — v1-8-6-weights-crosscut

## Goal

# v1.8.6 S3 Weights Cross-cut Objective  在 S0 contract 基础上，把 sampling/analysis/frequency 三种权重语义贯通 API、service、 workflow contract、OLS/预测协议和可选 UI 字段；不支持的模型族必须拒绝。  ## 必须完成  1. API 请求、service、stage、typed packet 均保留三种权重字段，不互相替代。 2. \`frequency_weight\` 与 \`analysis_weight\` 接入 OLS；\`sampling_weight\` 在分层/PSU 语义未    完整实现前 fail-closed。 3. strata/PSU 复用既有 cluster 通道；模型族通过 \`allows_weights\` 声明准入。 4. 预测路径继续保留正 frequency weight 的 sample_weight 语义，并从真实 API 可达。  ## 可证伪验收  - HTTP/API 真实 Run 传入 frequency weight 后，prediction/OLS packet 记录列名和 executed 状态，   且结果与不加权结果不同。 - 全 1 frequency weight 与不传权重逐位一致。 - 未声明权重的模型族返回稳定错误码且不写结果 artifact。 - sampling_weight 的拒绝路径和下一步说明可见；UI 不伪装为已支持。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 2/16 (12.5%; 12.5 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: N/A (sample=0; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-03T10:08:00.000Z `tdd_red_s3_api_and_ols_weight_boundary`; cause_status: `known`; cause: The S3 red tests showed two missing boundaries: HTTP form fields for frequency/analysis/sampling weights were ignored, and OLS weights metadata was not executed or preserved as a typed executed state; all-one weights also lacked an explicit no-drift contract.; resolution: `open`; lesson: Weight work needs both the real HTTP dispatch seam and numerical estimator boundary in red tests before implementation.

## All errors

- None recorded.

## All gaps

- #11 2026-08-03T12:15:00.000Z `existing_line_scope_drift`; cause_status: `known`; cause: The frozen v1-8-6-weights-crosscut Context Pack records backend/workbench/prediction.py as affected but omits it from allowed_paths, so the formal scope does not fully describe the implementation already present.; resolution: `open`; lesson: When an existing line is extended, record the exact affected-versus-allowed mismatch and correct it only through the formal rescope command.

## All waste

- None recorded.

## Root causes and solutions

- `existing-line-scope-drift-audit`: occurrences=1; cause_status: `known`; root cause: The frozen v1-8-6-weights-crosscut Context Pack records backend/workbench/prediction.py as affected but omits it from allowed_paths, so the formal scope does not fully describe the implementation already present.; solution: `open`
- `weights-api-and-estimator-red-before-code`: occurrences=1; cause_status: `known`; root cause: The S3 red tests showed two missing boundaries: HTTP form fields for frequency/analysis/sampling weights were ignored, and OLS weights metadata was not executed or preserved as a typed executed state; all-one weights also lacked an explicit no-drift contract.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `existing-line-scope-drift-audit`: line experience occurrence(s)=1
- `weights-api-and-estimator-red-before-code`: line experience occurrence(s)=1

## Future guidance

- Weight work needs both the real HTTP dispatch seam and numerical estimator boundary in red tests before implementation.
- When an existing line is extended, record the exact affected-versus-allowed mismatch and correct it only through the formal rescope command.

## Event index

- #1: `31114f32-b8e5-4773-bd6c-af507c4f0717` | 2026-08-03T09:59:41.602Z | STATE_CHANGE/line_started | incident=`377487d4-5834-4a1a-afef-d99555503047` | lesson_key=`frozen-context-before-start` | event_sha256=`a67cf72c894957bfa8cae49fe383c1ebe6d76e2b7f6f069184536e8548048655`
- #2: `456789ab-cdef-4012-3456-789abcdef012` | 2026-08-03T10:08:00.000Z | FAILURE/tdd_red_s3_api_and_ols_weight_boundary | incident=`56789abc-def0-4123-4567-89abcdef0123` | lesson_key=`weights-api-and-estimator-red-before-code` | event_sha256=`b7be4c8a209899023f10cf670012e5ca758fef6a4410558c10b97ba7780c6360`
- #3: `f9c8cf4b-34f0-497a-8966-f628bbbd9dfe` | 2026-08-03T10:02:51.171Z | STATE_CHANGE/context_rescope_required | incident=`31c21e1e-2c8c-40df-a3cb-bd44bd18641d` | lesson_key=`context-pack-rescope` | event_sha256=`e61e791ed9640c3e75cf292e9444deff5eb84a1e985911045d220e8caefb2595`
- #4: `a9aa4167-e29b-408e-a1f0-ac37f0dcf27b` | 2026-08-03T10:02:51.176Z | STATE_CHANGE/context_rescoped | incident=`6535900b-24ed-4c01-9bb8-66eb51cc1599` | lesson_key=`context-pack-rescope` | event_sha256=`46c3227ad3ec778e52fc8f82a75dc918391361f4d9a286e4859cd389a9b4ae14`
- #5: `24ac9fe2-abf1-4f27-96db-8709bd922821` | 2026-08-03T10:06:45.673Z | STATE_CHANGE/context_rescope_required | incident=`d23e6e29-1529-4d35-ad3f-fa5d87d81135` | lesson_key=`context-pack-rescope` | event_sha256=`625400838fa73c7b4c0ae054f99a42f6258c5c819c5f627f027d7f401c723338`
- #6: `f0844ea6-2387-4d15-a5ee-ab1ee7fadf64` | 2026-08-03T10:06:45.678Z | STATE_CHANGE/context_rescoped | incident=`712de2c2-0414-4bcb-8c6c-0f60dcdd44fe` | lesson_key=`context-pack-rescope` | event_sha256=`ff83ac58738f93f61b25b3d463655e73195d44b85f09bece5f5b4c5bbfc50587`
- #7: `6d3cdffd-6aca-4bee-bcac-706e2e2d1393` | 2026-08-03T10:09:20.223Z | STATE_CHANGE/context_rescope_required | incident=`bd47a815-fe90-493f-98be-32ad611b9337` | lesson_key=`context-pack-rescope` | event_sha256=`2e5f830125725ac8ff21db9620352c047d7c130d5b5e4c4e9024ecf811f2fe7f`
- #8: `6f9355f1-427e-44bd-9fad-b8260c62cf5c` | 2026-08-03T10:09:20.230Z | STATE_CHANGE/context_rescoped | incident=`ed7e36ed-f898-4289-a26e-af71a156a44b` | lesson_key=`context-pack-rescope` | event_sha256=`111ec1ae6b34440defc56cc4f73ab05b7e8fab6229c656186285c99c92eec783`
- #9: `a2e4c6d8-1f30-4b52-9a74-0e6c8d2f4b91` | 2026-08-03T10:20:00.000Z | GATE/s3_weights_crosscut_green | incident=`b3f5d7e9-2a41-4c63-8b95-1f7d9e3c5a02` | lesson_key=`weights-crosscut-needs-multi-boundary-gate` | event_sha256=`68c5d3ef1b36bdcb173c3bf2604e0c4a8ffb0813b4dea4f55329b2439b116297`
- #10: `c4f6a8b0-3d52-4e74-9c16-2a8e0f4b6d93` | 2026-08-03T10:30:00.000Z | GATE/s3_weight_admission_green | incident=`d5a7c9e1-4b63-5f85-0a27-3c9e1b5d7f04` | lesson_key=`weight-admission-needs-runtime-negative-test` | event_sha256=`7bdc1fd7253687959923e9b8f45a98bffaceef0b569d074c4a4d9d829f3e2887`
- #11: `f30a5b1c-3ad5-4e93-8ac3-1cb1b4a8c701` | 2026-08-03T12:15:00.000Z | GAP/existing_line_scope_drift | incident=`a9c4d1f0-3e7b-4a19-9b52-6c8d0f1e4a23` | lesson_key=`existing-line-scope-drift-audit` | event_sha256=`3f388f0ed7a16af56d0ccea5fad263d9045a56cc5f4b298294dfec05f9632979`
- #12: `fa827edc-f5a1-41d4-87f5-fc6d69ab4b8e` | 2026-08-03T13:18:05.173Z | STATE_CHANGE/context_rescope_required | incident=`f4335b21-fe25-450a-837e-ecaaa1169c7a` | lesson_key=`context-pack-rescope` | event_sha256=`6b5f6dfd4048ddfb4f44002fc3aaa8b0248f21ffdbd5357601d188c911f0ba67`
- #13: `757903cd-aa25-4b45-b4e6-6d97e957e2b1` | 2026-08-03T13:18:05.183Z | STATE_CHANGE/context_rescoped | incident=`76806487-75b0-41ab-9eae-6f2db59dc4e4` | lesson_key=`context-pack-rescope` | event_sha256=`03702c370c87d5d21ac826f745c743440a2e340b783cc043860207c02446da98`
- #14: `a9b0c1d2-e3f4-4567-8901-abcdef012357` | 2026-08-03T15:21:06.000Z | GATE/weights_gate_passed | incident=`b0c1d2e3-f4a5-4678-9012-abcdef012358` | lesson_key=`weight-semantics-boundary` | event_sha256=`05ad405f55affec1db6e1c795f413724dd2a55a3405f5fa1eb0bff9bee506919`
- #15: `5ee38e6c-51e6-48a7-ab3a-bdd41674a193` | 2026-08-03T15:49:29.301Z | STATE_CHANGE/context_rescope_required | incident=`8bf9b6e4-955f-44f6-b003-cb8f99ec8d3e` | lesson_key=`context-pack-rescope` | event_sha256=`f019244123a08e0364952b4c89c11d77f14877277b79b047bd01e677a72f93d4`
- #16: `0734674d-922a-41b2-861b-ebbd86668990` | 2026-08-03T15:49:29.312Z | STATE_CHANGE/context_rescoped | incident=`abe9f1ad-4174-4dea-82c1-963d33cc76c1` | lesson_key=`context-pack-rescope` | event_sha256=`a6ad3411d8ffb4a15270940cfc8ef4192c482730a41dca568ce46549a135bd63`
