# Retrospective — v1-8-3-capability-factory-scope

## Goal

# v1.8.3 Capability Factory 与双层领域记忆范围目标  **状态**：范围已批准；本文件用于冻结设计开发线，不代表产品能力已实现  **版本边界**：v1.8.3  ## 目标  在不扩大当前 B0 自定义能力运行时实现范围的前提下，为 v1.8.3 定义一套可长期扩展的 Agent 能力生产体系：  1. Agent 把用户目标、数据证据和所需输出解析为结构化 \`CapabilityRequirement\`； 2. 按“原生能力 → 已注册且已验证的第三方能力 → Agent 生成 Adapter → Agent 自研算法”的固定顺序解析实现； 3. 将依赖构建、能力验证、人工准入和分析运行彼此隔离； 4. 让不同来源的能力通过统一但非过度拟合的 capability profile、操作槽位、结果 facet、lineage 与 Artifact 边界进入 Workbench； 5. 复用现有 Agent Notebook 的推荐、并列、证据不足、备选项保留和确认后 materialize 契约； 6. 建立可显式开启或关闭的双层记忆：可重建的 Project/RunFamily 工作记忆，以及需用户批准提升的跨项目领域记忆； 7. 保证记忆只能影响候选检索与检查计划，不能提升统计证据、绕过验证、自动准入或替用户确认。  ## 本设计线交付  - \`README.md\`：v1.8.3 范围地图、文档权威关系和分阶段边界； - \`capability-factory-design.md\`：能力解析、解析顺序、Adapter、构建与运行隔离、证据与准入、Notebook 接入； - \`domain-memory-design.md\`：双层记忆、用户开关、提升流程、隔离、过期与冲突语义； - 对既有 B0 设计补充上游产品定位链接，但不改变其实现边界。  ## 明确不做  - 本设计线不实现产品代码、数据库迁移、API、UI 或 Agent operation； - 不在 Workbench 主环境中动态安装依赖； - 不让 Agent 生成的代码直接接触用户文件、宿主文件系统、网络或主进程； - 不把用户选择、一次成功运行、作者自测或记忆命中解释为统计正确； - 不为所有算法强制 \`fit/predict/diagnose/summarize/plot\` 全接口； - 不复制或重写现有 Notebook/Graph/Trace 契约； - 不承诺任一具体算法、数据集、软件格式或固定年份的兼容结果； - 不执行 push、PR、merge、tag 或发布操作。  ## 完成标准  - v1.8.3 文档明确区分运行时、能力工厂、Notebook 编排、领域记忆和消费者投影； - 能力来源、证据等级、准入状态与用户可见标签彼此独立； - 第三方 Adapter 与 Agent 自研算法拥有不同风险路径； - 构建阶段可联网，分析运行阶段默认断网且只读密封输入； - 推荐“首选”必须来自已注册的支配/比较协议；并列或不可比时不得伪造唯一首选； - Project/RunFamily 记忆是 Graph/Trace/Option 的可重建索引，不是隐藏事实源； - 跨项目记忆具有 provenance、作用域、修订、状态、冲突和显式用户批准； - 所有新增文档通过结构、链接、边界和反过拟合自审，正式 FMS 记录可验证。

## Final status

COMPLETED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=2; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/3)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- #2 2026-07-25T22:43:59.000Z `tag_normalization_rejection`; cause_status: `known`; cause: The first start invocation used v1.8.3 as a tag even though formal tags require normalized identifiers without dots.; resolution: `resolved`; lesson: Use normalized hyphenated identifiers such as v1-8-3 for formal tags.
- #3 2026-07-25T22:44:08.000Z `context_pack_filename_assumption`; cause_status: `known`; cause: The first read assumed legacy uppercase CONTEXT_PACK.md and manifest.json names instead of inspecting the generated formal line directory.; resolution: `resolved`; lesson: Inspect the generated line directory and use its actual formal filenames instead of relying on legacy naming from handoff prose.
- #5 2026-07-25T22:54:14.000Z `audit_redaction_wording_rejection`; cause_status: `known`; cause: The first review-event wording used a credential-associated English term and the formal redaction guard rejected the audit record.; resolution: `resolved`; lesson: Keep formal audit summaries free of credential-associated key names even when the design meaning is harmless.

## Root causes and solutions

- `audit-event-redaction-safe-wording`: occurrences=1; cause_status: `known`; root cause: The first review-event wording used a credential-associated English term and the formal redaction guard rejected the audit record.; solution: `resolved`
- `devline-tag-normalization`: occurrences=1; cause_status: `known`; root cause: The first start invocation used v1.8.3 as a tag even though formal tags require normalized identifiers without dots.; solution: `resolved`
- `inspect-generated-context-pack-filenames`: occurrences=1; cause_status: `known`; root cause: The first read assumed legacy uppercase CONTEXT_PACK.md and manifest.json names instead of inspecting the generated formal line directory.; solution: `resolved`

## Added tests

- `tests/test_no_exercise_specific_naming.py`

## New rules

- `audit-event-redaction-safe-wording`: line experience occurrence(s)=1
- `devline-tag-normalization`: line experience occurrence(s)=1
- `inspect-generated-context-pack-filenames`: line experience occurrence(s)=1

## Future guidance

- Define negative state propagation and recoverable decision receipts with the same precision as successful paths.
- Independent review should continue until cross-layer contracts have no unresolved critical, important, or minor findings.
- Inspect the generated line directory and use its actual formal filenames instead of relying on legacy naming from handoff prose.
- Keep formal audit summaries free of credential-associated key names even when the design meaning is harmless.
- Separate network fetch from all untrusted execution, preserve the frozen B0 ABI, and version every cross-layer binding or execution approval instead of relying on implied state.
- Use normalized hyphenated identifiers such as v1-8-3 for formal tags.

## Event index

- #1: `45d0f905-45a0-4b79-a96d-5f287f70d62e` | 2026-07-25T22:37:40.094Z | STATE_CHANGE/line_started | incident=`77bed802-78ec-4e91-8dd4-1fd2185ac6b6` | lesson_key=`frozen-context-before-start` | event_sha256=`9d2851425b84d362d240b7b2ae5a8fb9599f83ab658f1dd10ae0a8c5d3cc4d11`
- #2: `74b58087-9994-49f8-acca-53942d9fcc03` | 2026-07-25T22:43:59.000Z | WASTE/tag_normalization_rejection | incident=`841f5a16-0a76-4bcf-98cf-fad1861044da` | lesson_key=`devline-tag-normalization` | event_sha256=`a4570c9fe266a180a8c14d5500d6521103b000fece0ce613e21b2e8ad45e287a`
- #3: `d9b8597b-190d-433c-ae9a-419c88418de0` | 2026-07-25T22:44:08.000Z | WASTE/context_pack_filename_assumption | incident=`fe193b2e-46f1-4628-841e-700715bc3d44` | lesson_key=`inspect-generated-context-pack-filenames` | event_sha256=`34d262b7bcb7fba2a96c76bdbf82c3dbb2236de0b7dea5baffa081a5dc1763c1`
- #4: `803b8557-a075-4239-8fa3-0bc0caf47ced` | 2026-07-25T22:54:14.000Z | REVIEW/changes_required | incident=`8426b43a-9e94-4a37-86c0-d5f258ab00db` | lesson_key=`capability-factory-cross-layer-separation` | event_sha256=`dfccdadfe028d518144f0751ab8669d600a08bed29b08178da78e7f8cdeacadc`
- #5: `cdc4da6d-702b-405e-a933-70fc7651757b` | 2026-07-25T22:54:14.000Z | WASTE/audit_redaction_wording_rejection | incident=`8dacad07-81bb-4dca-995f-37b1f21350c8` | lesson_key=`audit-event-redaction-safe-wording` | event_sha256=`db306a11943004c6c9859d8dd93696caa588e21d272db509e3b2dd92dc19e360`
- #6: `b638e0db-650f-4a31-8043-2024fc998c29` | 2026-07-25T23:00:17.000Z | REVIEW/changes_required | incident=`5fcb6571-f51e-4024-aecf-5ed4df759879` | lesson_key=`capability-negative-path-contracts` | event_sha256=`91ea149a151df65b4b219332ed8a1a3997efdf817cfd794d870b7af39e810d62`
- #7: `47ac136d-662d-40ce-a049-c0d365846875` | 2026-07-25T23:02:02.000Z | REVIEW/accepted | incident=`e42da1c6-da58-4c3b-bbef-b558bdd7e69f` | lesson_key=`review-until-cross-layer-ready` | event_sha256=`73b97d1b943d8e8a9da0ce82dbf5dba3acf23aa0491655683db4f03789396690`
- #8: `29fa213a-2b3d-4e1f-91a6-358506ba273b` | 2026-07-25T23:02:02.000Z | GATE/design_checks_passed | incident=`52e0bb8e-a763-40ee-a201-cf46b355845b` | lesson_key=`design-gate-separates-spec-from-product` | event_sha256=`99aac8e0535bccdfbe680bab5eb96d73ed2f5ba72efb9bdd51730595046dd72d`
- #9: `79473519-e562-4193-980e-6d07514548a1` | 2026-07-25T23:02:02.000Z | STATE_CHANGE/design_scope_completed | incident=`180a81b6-d11b-4640-bc28-823a77ffe2e3` | lesson_key=`capability-factory-design-completion` | event_sha256=`7422445be8bc30c6aa47387ceb55a2662f8f8dde9ce368cd145f5cdb403ac408`
