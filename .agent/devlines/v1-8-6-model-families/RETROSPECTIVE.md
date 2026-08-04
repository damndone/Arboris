# Retrospective — v1-8-6-model-families

## Goal

# v1.8.6 S6/S7/S8 Model Families Objective  在 S0 可追加 registry 上增加 ordinal/nominal y_type、有序/多项 logit、生存分析和分位数 回归；每族独立契约、pack、诊断和 evidence，不改变既有三种 y_type。  ## 可证伪验收  - ordinal/nominal 真实 Run 分别产出预测概率、优势比/相对风险比、边际效应；有序模型有平行线诊断。 - Kaplan–Meier、log-rank、Cox 与 Schoenfeld 诊断使用独立 survival contract，risk set/censoring   证据可追溯。 - QuantReg 支持多个 quantile、区间/bootstrap 和跨 quantile 比较。 - 既有 golden 23 逐位 0-drift；Stata/R oracle 验证等级如实记录，不能以内部测试冒充外部一致。 - Graph/Report/Table/Agent 读取新增 packet 的精确数值，不只显示 artifact metadata。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 5/20 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-03T11:14:39.000Z `model_family_contract_red`; cause_status: `known`; cause: The new v1.8.6 contract tests correctly failed because the four model families were not yet admitted and model_options was not in the model.genesis step vocabulary.; resolution: `resolved`; lesson: For a new model family, lock the family-owned option vocabulary and model_params projection before exposing Agent admission.
- #18 2026-08-03T18:59:01.000Z `multinomial_base_category_label_mismatch`; cause_status: `known`; cause: An independent R nnet::multinom comparison exposed that statsmodels MNLogit labels its first coded category as the reference, while the runtime had treated the last public category as the reference.; resolution: `resolved`; lesson: Multinomial coefficients and relative-risk ratios must be labeled from the declared reference category, not from public category sort order alone.

## All errors

- #20 2026-08-03T19:01:22.000Z `fms_event_file_path_rejected`; cause_status: `known`; cause: The first append attempts supplied absolute temporary event-file paths; the formal CLI requires a repository-relative event-file path.; resolution: `resolved`; lesson: Use repository-relative temporary event files when invoking devline_control.py append and verify the returned event IDs before continuing.

## All gaps

- #5 2026-08-03T12:18:00.000Z `existing_line_scope_drift`; cause_status: `known`; cause: The frozen v1-8-6-model-families Context Pack was rescope-reduced to backend/workbench/agent/context_tools.py, while the S6/S7/S8 implementation and tests span model packs, contracts, orchestration, capabilities, frontend controls, and tests.; resolution: `open`; lesson: A model-family line must freeze the complete family-owned implementation and test paths, not only the final Agent reader seam.
- #9 2026-08-03T14:24:00.000Z `model_family_scope_extension`; cause_status: `known`; cause: The S6 acceptance requires ordinal and nominal y-type detection at the ordinary auto-routing boundary, but router.py and the y-type stage were not in the frozen model-family allowlist.; resolution: `open`; lesson: Record an allowlist gap before extending ordinary y-type routing beyond the model pack files.

## All waste

- None recorded.

## Root causes and solutions

- `fms-event-relative-path`: occurrences=1; cause_status: `known`; root cause: The first append attempts supplied absolute temporary event-file paths; the formal CLI requires a repository-relative event-file path.; solution: `resolved`
- `mnlogit-base-category-labels`: occurrences=1; cause_status: `known`; root cause: An independent R nnet::multinom comparison exposed that statsmodels MNLogit labels its first coded category as the reference, while the runtime had treated the last public category as the reference.; solution: `resolved`
- `model-family-contract-before-admission`: occurrences=1; cause_status: `known`; root cause: The new v1.8.6 contract tests correctly failed because the four model families were not yet admitted and model_options was not in the model.genesis step vocabulary.; solution: `resolved`
- `model-family-scope-must-cover-implementation`: occurrences=1; cause_status: `known`; root cause: The frozen v1-8-6-model-families Context Pack was rescope-reduced to backend/workbench/agent/context_tools.py, while the S6/S7/S8 implementation and tests span model packs, contracts, orchestration, capabilities, frontend controls, and tests.; solution: `open`
- `ytype-routing-scope-gap`: occurrences=1; cause_status: `known`; root cause: The S6 acceptance requires ordinal and nominal y-type detection at the ordinary auto-routing boundary, but router.py and the y-type stage were not in the frozen model-family allowlist.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `fms-event-relative-path`: line experience occurrence(s)=1
- `mnlogit-base-category-labels`: line experience occurrence(s)=1
- `model-family-contract-before-admission`: line experience occurrence(s)=1
- `model-family-scope-must-cover-implementation`: line experience occurrence(s)=1
- `ytype-routing-scope-gap`: line experience occurrence(s)=1

## Future guidance

- A model-family line must freeze the complete family-owned implementation and test paths, not only the final Agent reader seam.
- External numerical validation must preserve the exact fixture, cleaning rule, tie method, compared fields, and declared floating-point tolerance.
- For a new model family, lock the family-owned option vocabulary and model_params projection before exposing Agent admission.
- Model-family browser acceptance must cover both a successful family result and the family-specific fail-closed contract boundary.
- Multinomial coefficients and relative-risk ratios must be labeled from the declared reference category, not from public category sort order alone.
- Record an allowlist gap before extending ordinary y-type routing beyond the model pack files.
- Use repository-relative temporary event files when invoking devline_control.py append and verify the returned event IDs before continuing.

## Event index

- #1: `4acb0418-e887-4f33-ac81-193940e684fb` | 2026-08-03T11:03:44.045Z | STATE_CHANGE/line_started | incident=`ddbbd924-be14-4660-ba75-bfcbecda7bdd` | lesson_key=`frozen-context-before-start` | event_sha256=`37f836c586ac50192fb3bea6bbb459d6abc32ef233aa6c311569b53377ad205f`
- #2: `916473c6-d28b-424d-baee-e04f46c874f3` | 2026-08-03T11:14:18.367Z | STATE_CHANGE/context_rescope_required | incident=`ceea60e7-371e-45db-9b61-b7de8c354541` | lesson_key=`context-pack-rescope` | event_sha256=`e7b879fec2b99bc87a62a80003cacc3f1884e904181d84676ec05c4575a2a597`
- #3: `14628979-7de9-4245-b4e0-361680a98e56` | 2026-08-03T11:14:18.370Z | STATE_CHANGE/context_rescoped | incident=`3ed28bdb-bab2-4769-92e4-8463e8e8ee51` | lesson_key=`context-pack-rescope` | event_sha256=`302e6dbbce902dd2779b901e067e6f6b919f7a6e71ddbd7ed3085d2837ba3318`
- #4: `2f4169a6-6dbe-4d9a-8a0d-9bc0b8a8e8b1` | 2026-08-03T11:14:39.000Z | FAILURE/model_family_contract_red | incident=`c63a4c58-f31c-43f5-9ae6-0ef0c0e48c43` | lesson_key=`model-family-contract-before-admission` | event_sha256=`a3456f6eae47bac67cf7e5811562d56730a86f6076ed9b31e61498055db4d43d`
- #5: `64e38b0f-1a92-4f7e-8d55-0c2b9e6a741d` | 2026-08-03T12:18:00.000Z | GAP/existing_line_scope_drift | incident=`b8f0d2c4-6a19-4e53-9c71-0f8b2d5e6a34` | lesson_key=`model-family-scope-must-cover-implementation` | event_sha256=`917334e383bb0116e45b994d4c039d965787b61773c2467aa7eb9e955038985e`
- #6: `ef006af5-93ad-4a8f-97cb-b07b9d0022be` | 2026-08-03T13:17:50.377Z | STATE_CHANGE/context_rescope_required | incident=`0fbd2f3c-334d-4828-91e7-e36d81a71229` | lesson_key=`context-pack-rescope` | event_sha256=`d8cf64620c0c53032190bb987fea9008d8b219f93001750e524a049898453ec7`
- #7: `8664e0ca-313f-41e5-87a2-f30429a109de` | 2026-08-03T13:17:50.383Z | STATE_CHANGE/context_rescoped | incident=`33d5f675-f9e1-4fc1-bdab-edb45b550aa3` | lesson_key=`context-pack-rescope` | event_sha256=`bd8bc390b8a3b3aa047c5de79248c438edaa6e23c73242f642a5076437fc69e8`
- #8: `c0d1e2f3-a4b5-4678-9012-3456789abcde` | 2026-08-03T14:00:31.000Z | GATE/model_family_browser_acceptance | incident=`d1e2f3a4-b5c6-4789-0123-456789abcdef` | lesson_key=`separate-browser-and-oracle-acceptance` | event_sha256=`bf1db7423cece682714535d1654148c290f16b32aa97a738c1537839731ea3c2`
- #9: `0a1b2c3d-4e5f-6789-0123-456789abcdef` | 2026-08-03T14:24:00.000Z | GAP/model_family_scope_extension | incident=`1b2c3d4e-5f67-8901-2345-6789abcdef01` | lesson_key=`ytype-routing-scope-gap` | event_sha256=`b643f49099e40382c98cadbb7282376f3dbc1c7a7a1b845ed45d0fe8fb2bc87e`
- #10: `e02dea44-9ca1-4d9a-972c-ce538fbdbfd5` | 2026-08-03T14:34:25.720Z | STATE_CHANGE/context_rescope_required | incident=`c797fd1d-f072-4919-b13d-7fdb5e73dd6d` | lesson_key=`context-pack-rescope` | event_sha256=`340ed54ce2449ebca0b5722a4d5f9467b7699f75c71d63e636e2e1d512bb99ee`
- #11: `bb51ae97-7269-48f8-aed5-53d18ba81d90` | 2026-08-03T14:34:25.726Z | STATE_CHANGE/context_rescoped | incident=`aa0306d9-c6e4-4f60-a682-ebfdef201187` | lesson_key=`context-pack-rescope` | event_sha256=`15af454b805ec67643286abaee95a4358f4123089c08729df703eb5c46762f50`
- #12: `a3b4c5d6-e7f8-4901-2345-abcdef012351` | 2026-08-03T15:21:03.000Z | GATE/model_family_gate_passed | incident=`b4c5d6e7-f8a9-4012-3456-abcdef012352` | lesson_key=`model-family-oracle-boundary` | event_sha256=`d749dcfce304a93f15b64440cf66d28fea39484b15536dec8d01a55cab24b870`
- #13: `e899dde3-f52d-4cd3-a515-551f0992a3eb` | 2026-08-03T15:29:03.037Z | STATE_CHANGE/context_rescope_required | incident=`eecd0061-fee5-48fa-b4c1-5dff392ad879` | lesson_key=`context-pack-rescope` | event_sha256=`a295a544b2cb89fc3dc14a68a4d268c55a93e0d366e63c66410220c0255940b6`
- #14: `942a85fb-168d-4e25-929d-2573fd4af3f4` | 2026-08-03T15:29:03.060Z | STATE_CHANGE/context_rescoped | incident=`64480531-657c-42eb-b314-5af708ef9dcc` | lesson_key=`context-pack-rescope` | event_sha256=`6833febc54940c43cc3023a96609d34972f355ab25bc9d33b7d5fc4b8affffd9`
- #15: `c0838d98-19e8-4dd6-8954-c1290e98f893` | 2026-08-03T15:49:29.737Z | STATE_CHANGE/context_rescope_required | incident=`d5906873-0695-4de0-b69a-3a0c6e2b77ad` | lesson_key=`context-pack-rescope` | event_sha256=`dcd7d217ab682974d968f2036f5721316c7e74f22375729eb9ed97390eec27b9`
- #16: `174d37ce-18ba-461f-a6f2-79502fa02078` | 2026-08-03T15:49:29.749Z | STATE_CHANGE/context_rescoped | incident=`c7ddf30c-8639-4961-974d-e66c8f6f1d07` | lesson_key=`context-pack-rescope` | event_sha256=`bdfbadafecddc68659261365adda8a795c69098f5d8f3549bfd1393cd97b8908`
- #17: `2d3e4f5a-6b7c-8901-abcd-ef0123456789` | 2026-08-03T18:20:00.000Z | REVIEW/native_browser_model_family_review | incident=`3e4f5a6b-7c8d-9012-abcd-ef0123456789` | lesson_key=`v186-browser-model-families-verified` | event_sha256=`931df68a3dd87b9ddda00b5eb607d29348fa2662f610f3685cd177437d674249`
- #18: `4a5b6c7d-8e9f-4012-a3b4-c5d6e7f80910` | 2026-08-03T18:59:01.000Z | FAILURE/multinomial_base_category_label_mismatch | incident=`5b6c7d8e-9f01-4123-b4c5-d6e7f8091021` | lesson_key=`mnlogit-base-category-labels` | event_sha256=`1fd2406aa7ff5d371db6273fae69c9f8c07a5df50c5f3d7ba4cdd47759b26d5c`
- #19: `6c7d8e9f-0123-4234-a5b6-c7d8e9f01234` | 2026-08-03T18:59:01.000Z | REVIEW/survival_r_oracle_verified | incident=`7d8e9f01-2345-4345-b6c7-d8e9f0123456` | lesson_key=`survival-external-oracle` | event_sha256=`ac5f339e7671a345faa2f161986d76b1f4ac378367140345633aa5b558aaee8c`
- #20: `a0123456-789a-4678-b9c0-123456789abc` | 2026-08-03T19:01:22.000Z | ERROR/fms_event_file_path_rejected | incident=`b1234567-89ab-4789-c012-3456789abcde` | lesson_key=`fms-event-relative-path` | event_sha256=`2369202c18714c3c87a08a44d9019d4fea3c8719776f655a3e3589b07c14e675`
