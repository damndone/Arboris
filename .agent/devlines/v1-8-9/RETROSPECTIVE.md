# Retrospective — v1-8-9

## Goal

# v1.8.9 — 日常可用（重建版）  基线：\`f3836408\`（v1.8.8 发布提交 \`f564de63\` + v1.8.9 spec/plan 文档）。 零件库：tag \`archive/v1.8.9-codex-wip\`（\`214dee95\`），只按需移植，不整体合并。  ## 一句话目标  研究员不写代码、不看菜单，用中文完成"导入数据 → 整理变量 → 建模 → 读懂结果"， 且每个数字都可信、可追溯。  ## 为什么重建  Codex 的 integration 分支在主线上出现退化：Agent/Notebook 面板不再调用 LLM； v1.8.6 四个模型族的结果对 Agent/Report 不可读；证据读取比 v1.8.8 慢约 200 倍； full gate 未通过。数据层、分类 ML、抽样 GLM 等模块本身基本独立，可移植。  ## 范围（按顺序交付，每步单独提交并验收）  | # | 交付 | 来源 | 验收场景（浏览器内真实操作） | |---|---|---|---| | 1 | 修正后估计的模型族错配：非 OLS 模型不得做 OLS 联合 F / White / 二次驻点 | 新写 | Logit 模型后请求联合 F 检验 → 明确"不适用于 logit"，不产出数字 | | 2 | 恢复模型分支在 resume 时的绑定 | 参考零件库 P0-B | 模型后中断、重启 backend、继续 → 后续步骤绑定到同一模型 | | 3 | Agent 基线核查：v1.8.8 LLM Agent 用 DeepSeek 跑 10 条中文请求，记录成功率与失败类型 | 新写（评测脚本） | 基线数字写入本文件末尾，作为后续改动的对照 | | 4 | 变量元数据：变量标签、值标签、测量级别、缺失值定义 | 移植 \`metadata.py\` 等 | 在界面改 \`gender\` 的值标签，结果表与 Agent 回答使用新标签 | | 5 | \`.sav/.zsav/.dta\` 导入导出（含标签），不能保留的元数据明确提示 | 移植 \`data_interchange.py\` | 导入 .sav → 改标签 → 导出 .dta → 再导入，标签一致 | | 6 | 数据编辑器：数据视图 + 变量视图，数据操作（filter/sort/recode/split）以血缘节点记录 | 移植 \`data_operations.py\`、\`filter_ast.py\` + 新 UI | 在变量视图把 \`age\` 分三组 recode，生成新节点，可回溯 | | 7 | Agent 驱动以上全部能力：LLM 负责理解与组合；写操作经服务端校验 + 用户确认 | 在 v1.8.8 Agent 上扩展工具 | 用中文让 Agent 完成场景 4–6 与一次 Logit 建模，成功率不低于第 3 步基线 | | 8 | 外发管控 v1：内容来源处打标签、LLM 客户端唯一出口检查、原始行默认不外发、被拦截内容以占位说明替换 | 新写（参考 spec §7.7） | Agent 请求"把前 20 行发给我看"→ 本地显示，发往 DeepSeek 的请求中无原始行（审计日志可见） |  不在本版：分类 ML、抽样 GLM 扩展（v1.8.11 移植）、出版级表格与脚本导出（v1.8.10）、 P2 模型族、Codex 的分页/授权凭据/字节预算体系。  ## 硬约束  - 正确性：统计数字只由确定性代码产生；不适用的方法明确拒绝，不静默降级。 - 性能预算：读取单个结果 < 1 秒；后端测试总时长不超过 v1.8.8 的 1.5 倍。 - 不退化：v1.8.8 已有的 UI、Agent、模型族、结果展示全部保留，除非本文件列出替代。 - 每个交付完成即提交；不留跨天未提交改动。  ## 验证  - 每步：先写能复现问题的失败测试，再修；相关测试 + 前端 typecheck。 - 第 3、7 步：真实 DeepSeek 调用，结果与确定性测试分开记录。 - 发版前：宿主机 full gate（\`scripts/gate.sh --full\`），浏览器逐条走验收场景。  ## 已知门槛  - 仅本机 macOS 验证；Linux / 其他主机 / 云端为 NOT VERIFIED。 - 真实 LLM 质量只对 DeepSeek 负责。 - merge / tag / push 需用户单独授权。

## Final status

RELEASED

## Metrics

- Failure frequency: 12/23 (52.2%; 52.2 per 100 events)
- Repeat rate: 0/12 (0.0%)
- Recurrence rate: 0/12 (0.0%)
- MTTR: median=0 ms (sample=11; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-09-25T19:14:51.000Z `ols_post_estimation_on_glm_branch`; cause_status: `known`; cause: Joint F, White and quadratic stationary point refit every upstream branch by OLS without checking the declared model_family.; resolution: `resolved`; lesson: OLS-only post-estimation must check the upstream family at the shared refit entry; 9 RED cases (3 families x 3 operations) now pass.
- #3 2026-09-25T20:31:20.000Z `model_branches_lost_on_resume`; cause_status: `known`; cause: Workflow state persisted only produced_dataset; model steps publish their fitted branches under payload branches, which were dropped from the state record.; resolution: `resolved`; lesson: Every output a later step binds to through depends_on must be persisted in step state, not only declared dataset bindings.
- #5 2026-09-25T21:11:44.000Z `rerun_without_model_effect`; cause_status: `known`; cause: model.rerun accepted a labels-only patch naming columns outside the model, and the Agent RerunService lacked the absent-column guard that only the HTTP route applied.; resolution: `resolved`; lesson: Validation shared by multiple execution paths must live in the shared service and also run at proposal time.
- #6 2026-09-25T21:11:44.000Z `genesis_labels_encoded_as_text`; cause_status: `known`; cause: execute_genesis_draft JSON-encoded all dict model params, turning labels into text rejected downstream.; resolution: `resolved`; lesson: Form synthesis must use the one shared field encoder rather than a local re-implementation.
- #8 2026-09-26T04:15:52.000Z `rerun_labels_replaced_wholesale`; cause_status: `known`; cause: merge_form_overrides replaced the parent's labels object with the patch, dropping every declaration the patch did not repeat.; resolution: `resolved`; lesson: Metadata patches must merge per field and column; replacing structured declarations silently changes the estimation sample.
- #10 2026-09-26T07:28:15.000Z `real_stata_files_exposed_interchange_gaps`; cause_status: `known`; cause: Synthetic fixtures never produced a Stata integer column with missing values (read as object/text) or integer-typed value-label keys (SPSS export failure).; resolution: `resolved`; lesson: Interchange must be validated on real user files, not only on files the same library wrote.
- #12 2026-09-26T10:38:56.000Z `unexecutable_direct_step_proposals`; cause_status: `known`; cause: Six workflow-step identities were offered as direct Agent proposals although they require a workflow/step id and have no standalone executor.; resolution: `resolved`; lesson: What the Agent is offered must be checked against what can execute, by a test, not by convention.
- #19 2026-09-27T20:50:00.000Z `release_acceptance_defects`; cause_status: `known`; cause: Browser acceptance of the eight objective scenarios after the gate: the project Agent's overview was frozen at session creation; workflow proposals made with a model node selected carried that node's fingerprint and were always rejected as stale; Agent exports skipped the ledger; the loop guard fired on the first repeated inspection.; resolution: `resolved`; lesson: A passing gate and a passing live eval do not cover the UI states people actually use (a model node selected, a long-lived session): walk the acceptance scenarios in the browser on the release candidate before calling it done.
- #21 2026-09-28T19:30:00.000Z `anti_fragility_defects`; cause_status: `known`; cause: Anti-fragility round on the gated candidate: provider faults injected into real Agent turns, two turns sent to one session at once, and adversarial users. Found: failure banner not clearing after recovery and cut-off replies standing unmarked; the provider stream closed only by garbage collection; concurrent writes to one session losing entries (per-request instance locks) and a non-atomic in-progress check; a repeated identical test failing with 'artifact path is occupied'; scientific notation read as two numbers by the numeric check; a refusal that withheld the true value it could have fetched.; resolution: `resolved`; lesson: Deterministic tests and a clean-network live eval do not exercise failure and recovery: inject provider faults and concurrency into real turns, and check that the same session works after a failure, not only that the failure is reported.

## All errors

- None recorded.

## All gaps

- #4 2026-09-25T20:55:14.000Z `agent_live_baseline_defects`; cause_status: `known`; cause: Real DeepSeek evaluation of the v1.8.8 chain Agent (20 turns, 7 confirmed executions) exposed contract and UX gaps not covered by deterministic tests.; resolution: `open`; lesson: Deterministic planner scores do not reveal silent no-op effects; confirmed execution must be checked against the declared expected effect.
- #16 2026-09-27T01:30:00.000Z `agent_numeric_grounding`; cause_status: `known`; cause: Agent replies were checked for numbers only by prompt rules; the model rounded and subtracted in its head (0.09849 -> 0.099). Verifying the new numeric check live exposed three more defects: DeepSeek thinking mode rejects (HTTP 400) a second answer inside a tool-using turn; grouped statistics reached the Agent as '[omitted: nesting limit]'; tool-bearing requests were never retried on transient provider failures.; resolution: `resolved`; lesson: A rule the model is told is not a rule the product enforces. Enforce it in code at one checkpoint, then verify the enforcement path itself live: the first live run of the repair path failed for a provider-specific reason no scripted test could show.
- #17 2026-09-27T07:00:00.000Z `manual_walkthrough_findings`; cause_status: `known`; cause: Writing the user manual from the live interface on a real SPSS file exercised the default import path end to end for the first time this version.; resolution: `resolved`; lesson: Walk the default path in the product with real data before documenting it; the manual is an acceptance test of the interface.

## All waste

- None recorded.

## Root causes and solutions

- `acceptance-in-the-real-ui-state`: occurrences=1; cause_status: `known`; root cause: Browser acceptance of the eight objective scenarios after the gate: the project Agent's overview was frozen at session creation; workflow proposals made with a model node selected carried that node's fingerprint and were always rejected as stale; Agent exports skipped the ledger; the loop guard fired on the first repeated inspection.; solution: `resolved`
- `document-from-the-live-default-path`: occurrences=1; cause_status: `known`; root cause: Writing the user manual from the live interface on a real SPSS file exercised the default import path end to end for the first time this version.; solution: `resolved`
- `enforce-model-rules-in-code-and-live-test-the-enforcement`: occurrences=1; cause_status: `known`; root cause: Agent replies were checked for numbers only by prompt rules; the model rounded and subtracted in its head (0.09849 -> 0.099). Verifying the new numeric check live exposed three more defects: DeepSeek thinking mode rejects (HTTP 400) a second answer inside a tool-using turn; grouped statistics reached the Agent as '[omitted: nesting limit]'; tool-bearing requests were never retried on transient provider failures.; solution: `resolved`
- `genesis-form-must-use-shared-encoder`: occurrences=1; cause_status: `known`; root cause: execute_genesis_draft JSON-encoded all dict model params, turning labels into text rejected downstream.; solution: `resolved`
- `inject-faults-and-check-recovery`: occurrences=1; cause_status: `known`; root cause: Anti-fragility round on the gated candidate: provider faults injected into real Agent turns, two turns sent to one session at once, and adversarial users. Found: failure banner not clearing after recovery and cut-off replies standing unmarked; the provider stream closed only by garbage collection; concurrent writes to one session losing entries (per-request instance locks) and a non-atomic in-progress check; a repeated identical test failing with 'artifact path is occupied'; scientific notation read as two numbers by the numeric check; a refusal that withheld the true value it could have fetched.; solution: `resolved`
- `label-patches-must-merge-not-replace`: occurrences=1; cause_status: `known`; root cause: merge_form_overrides replaced the parent's labels object with the patch, dropping every declaration the patch did not repeat.; solution: `resolved`
- `live-agent-eval-must-verify-executed-effect`: occurrences=1; cause_status: `known`; root cause: Real DeepSeek evaluation of the v1.8.8 chain Agent (20 turns, 7 confirmed executions) exposed contract and UX gaps not covered by deterministic tests.; solution: `open`
- `offered-operations-must-be-executable`: occurrences=1; cause_status: `known`; root cause: Six workflow-step identities were offered as direct Agent proposals although they require a workflow/step id and have no standalone executor.; solution: `resolved`
- `ols-post-estimation-requires-ols-family`: occurrences=1; cause_status: `known`; root cause: Joint F, White and quadratic stationary point refit every upstream branch by OLS without checking the declared model_family.; solution: `resolved`
- `rerun-must-reject-changes-without-model-effect`: occurrences=1; cause_status: `known`; root cause: model.rerun accepted a labels-only patch naming columns outside the model, and the Agent RerunService lacked the absent-column guard that only the HTTP route applied.; solution: `resolved`
- `resume-must-persist-every-bound-step-output`: occurrences=1; cause_status: `known`; root cause: Workflow state persisted only produced_dataset; model steps publish their fitted branches under payload branches, which were dropped from the state record.; solution: `resolved`
- `validate-interchange-on-real-user-files`: occurrences=1; cause_status: `known`; root cause: Synthetic fixtures never produced a Stata integer column with missing values (read as object/text) or integer-typed value-label keys (SPSS export failure).; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `acceptance-in-the-real-ui-state`: line experience occurrence(s)=1
- `document-from-the-live-default-path`: line experience occurrence(s)=1
- `enforce-model-rules-in-code-and-live-test-the-enforcement`: line experience occurrence(s)=1
- `genesis-form-must-use-shared-encoder`: line experience occurrence(s)=1
- `inject-faults-and-check-recovery`: line experience occurrence(s)=1
- `label-patches-must-merge-not-replace`: line experience occurrence(s)=1
- `live-agent-eval-must-verify-executed-effect`: line experience occurrence(s)=1
- `offered-operations-must-be-executable`: line experience occurrence(s)=1
- `ols-post-estimation-requires-ols-family`: line experience occurrence(s)=1
- `rerun-must-reject-changes-without-model-effect`: line experience occurrence(s)=1
- `resume-must-persist-every-bound-step-output`: line experience occurrence(s)=1
- `validate-interchange-on-real-user-files`: line experience occurrence(s)=1

## Future guidance

- A passing gate and a passing live eval do not cover the UI states people actually use (a model node selected, a long-lived session): walk the acceptance scenarios in the browser on the release candidate before calling it done.
- A rule the model is told is not a rule the product enforces. Enforce it in code at one checkpoint, then verify the enforcement path itself live: the first live run of the repair path failed for a provider-specific reason no scripted test could show.
- Deterministic planner scores do not reveal silent no-op effects; confirmed execution must be checked against the declared expected effect.
- Deterministic tests and a clean-network live eval do not exercise failure and recovery: inject provider faults and concurrency into real turns, and check that the same session works after a failure, not only that the failure is reported.
- Every output a later step binds to through depends_on must be persisted in step state, not only declared dataset bindings.
- Form synthesis must use the one shared field encoder rather than a local re-implementation.
- Interchange must be validated on real user files, not only on files the same library wrote.
- Metadata patches must merge per field and column; replacing structured declarations silently changes the estimation sample.
- OLS-only post-estimation must check the upstream family at the shared refit entry; 9 RED cases (3 families x 3 operations) now pass.
- Validation shared by multiple execution paths must live in the shared service and also run at proposal time.
- Walk the default path in the product with real data before documenting it; the manual is an acceptance test of the interface.
- What the Agent is offered must be checked against what can execute, by a test, not by convention.

## Event index

- #1: `7bcb1489-b6df-4db0-81ed-2793f0502c66` | 2026-09-25T19:11:31.903Z | STATE_CHANGE/line_started | incident=`d8430bd4-d887-43cb-8a00-357030610149` | lesson_key=`frozen-context-before-start` | event_sha256=`cd178a32507adbe6680ee05de1e50266cc41a614ee76dd133b703bab39a12df2`
- #2: `6597ba4d-1570-4616-bb9c-6bbca4813c5e` | 2026-09-25T19:14:51.000Z | FAILURE/ols_post_estimation_on_glm_branch | incident=`fa492956-daf6-4a2d-bef2-ae6d29544c4d` | lesson_key=`ols-post-estimation-requires-ols-family` | event_sha256=`a85354d8cdb34d15b04b5c1f4e4146430c3e5fcf02b9880855ef2fdbc71698b2`
- #3: `c2c46850-c141-409f-90ba-50136278300d` | 2026-09-25T20:31:20.000Z | FAILURE/model_branches_lost_on_resume | incident=`66c07152-b9bf-4547-9484-a88d09184673` | lesson_key=`resume-must-persist-every-bound-step-output` | event_sha256=`944ec44e3ab0217a5e1d45c7a980d0075c6aeb493631fe84d46cf5f3f811e9ec`
- #4: `e7702a54-7db1-48ba-bd1f-1bdfb1e3c1e0` | 2026-09-25T20:55:14.000Z | GAP/agent_live_baseline_defects | incident=`2f60cdcb-e3e1-4055-97a1-c56ac28aecf3` | lesson_key=`live-agent-eval-must-verify-executed-effect` | event_sha256=`97e9d99119e8103ce7b70b1437830e2bb06841d4dce4a2abf0a19f48a7d831f6`
- #5: `2226178d-9a06-45c3-8fc8-93672c3e518d` | 2026-09-25T21:11:44.000Z | FAILURE/rerun_without_model_effect | incident=`1949a082-0075-410a-8d61-5c3fc3ed5efc` | lesson_key=`rerun-must-reject-changes-without-model-effect` | event_sha256=`196b98dd86f59c33a0e7896c711dfabcd1aa6b970e56b88d51bd9c44176402ce`
- #6: `3f8f7dc5-553c-4670-a012-3c7f24b9399c` | 2026-09-25T21:11:44.000Z | FAILURE/genesis_labels_encoded_as_text | incident=`5ad5e7cc-ca2e-402d-9405-6e6c61258ccf` | lesson_key=`genesis-form-must-use-shared-encoder` | event_sha256=`c09331e2279f624cc6e0a4c4c37837c5758e9af53785c0c2c7292d14de6e5ad6`
- #7: `d702e207-92cd-418e-804c-db1658e269df` | 2026-09-25T21:50:01.000Z | STATE_CHANGE/step4_variable_metadata_completed | incident=`8eb3ae5b-46d8-44f9-8ef5-223906404539` | lesson_key=`agent-tool-refusals-must-be-visible` | event_sha256=`692dc505ca890d97416414d519fbe53796cfe5c2610be9f6ee660dbc3ae1c63e`
- #8: `31d3842f-416d-4278-b8f6-42ddea3e68ce` | 2026-09-26T04:15:52.000Z | FAILURE/rerun_labels_replaced_wholesale | incident=`c3884279-6afa-4d2e-9162-b741876e87d5` | lesson_key=`label-patches-must-merge-not-replace` | event_sha256=`324e37b2eada34bdb6f91089a28093d426f4de0fcdb59b5b08e84d4c0c2d8da5`
- #9: `0c0f6f55-d6ee-4a38-8bf0-46e2788fda4f` | 2026-09-26T04:15:52.000Z | STATE_CHANGE/step5_statistical_interchange_completed | incident=`dd03da5f-be27-4254-9549-46a04f4c5527` | lesson_key=`interchange-needs-independent-reader-and-round-trip` | event_sha256=`d737d195682ef2f38fba0340163159bdc109aabf2385bd265739dddfdcbc5b0c`
- #10: `e92afdf1-3353-4b39-b507-5bf35a956479` | 2026-09-26T07:28:15.000Z | FAILURE/real_stata_files_exposed_interchange_gaps | incident=`7248ff62-14cb-4173-b616-177c5162b9e0` | lesson_key=`validate-interchange-on-real-user-files` | event_sha256=`2294d21e51c019e67f528db7021088feab53a241eaf9d2e251a3e05f40235686`
- #11: `5ece04bb-87d1-4d81-bc0b-919349745e0e` | 2026-09-26T07:28:15.000Z | STATE_CHANGE/step6_data_editor_completed | incident=`f2980229-c778-4add-95ee-0c113c3cb3f1` | lesson_key=`browser-acceptance-on-real-data-finds-state-bugs` | event_sha256=`a0cb2c62efcc0e5689ee933743a1fcdc410cd250920dfa681ce602cdab80285c`
- #12: `92006648-4194-411e-8ac8-2ffefe3f3dc7` | 2026-09-26T10:38:56.000Z | FAILURE/unexecutable_direct_step_proposals | incident=`641fb61b-627a-4ed2-8ca6-412caef5a66e` | lesson_key=`offered-operations-must-be-executable` | event_sha256=`2cf65a2f6f8e700f6935055c2ce91205ec76f4de42e297290e9d3c3e144b81e0`
- #13: `8cafb2d3-0c84-4cee-bb0a-995ccfc25fe0` | 2026-09-26T10:38:56.000Z | STATE_CHANGE/step7_agent_drives_capabilities | incident=`dcde7e94-3852-4b90-b443-330b95873882` | lesson_key=`verify-agent-executions-independently` | event_sha256=`73bf7230ffcd45358aa2088553795965ed47e0f1b842315a7a426b3223c270db`
- #14: `20a25742-8344-4cac-84b9-ffd088cbcda5` | 2026-09-26T13:30:00.000Z | STATE_CHANGE/step8_egress_control_v1 | incident=`993ae5c0-7621-40b6-bcc8-97052c4b61b5` | lesson_key=`egress-filter-must-not-hide-failures` | event_sha256=`d062f8fd04792bf8a294bbc6e84293a5fa9394f04a05e27eb0edda98a84f9a62`
- #15: `6760405c-44ad-4e46-bd9c-b51c482f6201` | 2026-09-26T22:30:00.000Z | STATE_CHANGE/trust_usability_round | incident=`218acab8-ccc2-406e-9792-37e31042dde2` | lesson_key=`oracle-on-full-data-and-repeat-live-runs` | event_sha256=`5c9f5859e7f3173daa6f081fd840e54a175848ee9a21a22b187dac6a7dff9445`
- #16: `13699462-4717-48d2-a51d-f39ca73031f0` | 2026-09-27T01:30:00.000Z | GAP/agent_numeric_grounding | incident=`3246e96c-0fcf-4864-8c11-cd033ea0de4f` | lesson_key=`enforce-model-rules-in-code-and-live-test-the-enforcement` | event_sha256=`17b55911cad4adf1bf6fe42eb38bec432d35bf226a6204312dc632d455859ef9`
- #17: `a6f98309-8d5a-4e25-9fff-543a34c231c5` | 2026-09-27T07:00:00.000Z | GAP/manual_walkthrough_findings | incident=`b88beb98-81d6-4eae-86da-b12df246570d` | lesson_key=`document-from-the-live-default-path` | event_sha256=`882d3558ca309b0af1cc0bd9e2f586571b757d451280ff607a6961f6d920202c`
- #18: `d0216d81-4f3d-4a19-9dd8-37fe2a4aafbc` | 2026-09-27T19:41:11.000Z | GATE/host_full_gate | incident=`4bdc352e-98f6-47d4-9997-2b6cb5345eb6` | lesson_key=`host-gate-with-recorded-log` | event_sha256=`ae2daf5893f4f3ad369d4c2a2ea09df8fa372508654299bf3bcb626949f34807`
- #19: `1172aab5-372c-44b2-8536-17c1a748af7b` | 2026-09-27T20:50:00.000Z | FAILURE/release_acceptance_defects | incident=`f275115e-25f7-432c-a096-e33588137719` | lesson_key=`acceptance-in-the-real-ui-state` | event_sha256=`ff3d1b9d96526014e8c414d0134802ce8f3aaad70777cbb54dba1031dba926eb`
- #20: `3426fb92-43e6-4c27-b699-9e337da9a0b3` | 2026-09-27T21:15:11.000Z | GATE/host_full_gate | incident=`f43e1e5c-a5f7-482f-b89f-465d7e4f5ccb` | lesson_key=`regate-after-acceptance-fixes` | event_sha256=`a9bf7d209faf6708c8a91399f31b589f27d833ad644069d124b3aa6cac9ee472`
- #21: `134ba3b1-f2ce-4b02-a577-17616992aaba` | 2026-09-28T19:30:00.000Z | FAILURE/anti_fragility_defects | incident=`52043da3-5e83-4892-a412-1ff2c61c5f6d` | lesson_key=`inject-faults-and-check-recovery` | event_sha256=`e7bcfc6a80737bab5efce60623b4df9dfca1b8400c4bfb86f4a69ab21390964d`
- #22: `fc84b62f-47b0-47c1-bed0-5034b40d090c` | 2026-09-28T18:28:46.000Z | GATE/host_full_gate | incident=`5e8b464d-5611-4427-890a-0e2ac6fd5ade` | lesson_key=`regate-after-acceptance-fixes` | event_sha256=`939e1746fed350a5c722b87293467f4230b90e4104fa4f916f732d1b6a8f1db1`
- #23: `839504b0-6e2b-477c-ac64-a059b90163c7` | 2026-09-28T19:00:00.000Z | STATE_CHANGE/release_approved | incident=`ff1a48e8-2a79-4ad6-806c-777e8f17c2b2` | lesson_key=`fetch-and-inspect-main-before-release-merge` | event_sha256=`cc9af85be8737e1c77f51c7346ab2518c85064e5216d57cfcda07c3d925e1a92`
