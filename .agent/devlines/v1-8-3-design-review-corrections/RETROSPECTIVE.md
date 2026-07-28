# Retrospective — v1-8-3-design-review-corrections

## Goal

# v1.8.3 Capability Factory 与双层领域记忆范围目标  **状态**：范围已批准；本文件用于冻结设计开发线，不代表产品能力已实现  **版本边界**：v1.8.3  ## 目标  在不扩大当前 B0 自定义能力运行时实现范围的前提下，为 v1.8.3 定义一套可长期扩展的 Agent 能力生产体系：  1. Agent 把用户目标、数据证据和所需输出解析为结构化 \`CapabilityRequirement\`； 2. 按“原生能力 → 已注册且已验证的第三方能力 → Agent 生成 Adapter → Agent 自研算法”的固定顺序解析实现； 3. 将依赖构建、能力验证、人工准入和分析运行彼此隔离； 4. 让不同来源的能力通过统一但非过度拟合的 capability profile、操作槽位、结果 facet、lineage 与 Artifact 边界进入 Workbench； 5. 复用现有 Agent Notebook 的推荐、并列、证据不足、备选项保留和确认后 materialize 契约； 6. 建立双层记忆：Project/RunFamily context index 始终是可重建事实索引；跨项目领域记忆的使用与迭代可由用户独立开启或关闭； 7. 保证记忆只能影响候选检索与检查计划，不能提升统计证据、绕过验证、自动准入或替用户确认。  ## 本设计线交付  - \`README.md\`：v1.8.3 范围地图、文档权威关系和分阶段边界； - \`capability-factory-design.md\`：能力解析、解析顺序、Adapter、构建与运行隔离、证据与准入、Notebook 接入； - \`domain-memory-design.md\`：双层记忆、用户开关、提升流程、隔离、过期与冲突语义； - 对既有 B0 设计补充上游产品定位链接，但不改变其实现边界。  ## 明确不做  - 本设计线不实现产品代码、数据库迁移、API、UI 或 Agent operation； - 不在 Workbench 主环境中动态安装依赖； - 不让 Agent 生成的代码直接接触用户文件、宿主文件系统、网络或主进程； - 不把用户选择、一次成功运行、作者自测或记忆命中解释为统计正确； - 不为所有算法强制 \`fit/predict/diagnose/summarize/plot\` 全接口； - 不复制或重写现有 Notebook/Graph/Trace 契约； - 不承诺任一具体算法、数据集、软件格式或固定年份的兼容结果； - 不执行 push、PR、merge、tag 或发布操作。  ## 完成标准  - v1.8.3 文档明确区分运行时、能力工厂、Notebook 编排、领域记忆和消费者投影； - 能力来源、证据等级、准入状态与用户可见标签彼此独立； - 第三方 Adapter 与 Agent 自研算法拥有不同风险路径； - 只有不执行不可信代码的依赖解析/获取平面可联网；组装、Adapter/算法验证和正式分析运行均断网； - 推荐“首选”必须来自已注册的支配/比较协议；并列或不可比时不得伪造唯一首选； - Project/RunFamily 记忆是 Graph/Trace/Option 的可重建索引，不是隐藏事实源； - 跨项目记忆具有 provenance、作用域、修订、状态、冲突和显式用户批准； - 所有新增文档通过结构、链接、边界和反过拟合自审，正式 FMS 记录可验证。

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
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- `tests/test_no_exercise_specific_naming.py`

## New rules

- No rule candidate recorded.

## Future guidance

- Cross-slice completion criteria and mutable validity must be closed in authority design rather than deferred as plan notes.
- Object idempotency, process launch, revocation ordering, and aggregate commit identity require separate explicit contracts.
- Repeat independent review until architecture, safety, statistics, privacy, and recovery contracts converge on the same stable design.

## Event index

- #1: `a83334e6-db34-4ee2-8c21-be433d42f980` | 2026-07-25T23:49:51.839Z | STATE_CHANGE/line_started | incident=`799c8406-9f82-4a27-be5d-7c69c6172196` | lesson_key=`frozen-context-before-start` | event_sha256=`9c31cd71b0fc74a847633674d9d83e97b6c868d0141cd9e62cb27c6bd0307e01`
- #2: `bcbe2f02-8c01-4b25-9009-631b3fc48137` | 2026-07-26T00:27:24.000Z | REVIEW/changes_required | incident=`a6412ba0-1ae3-4279-bebb-21bc27688e81` | lesson_key=`correct-cross-slice-contracts-before-planning` | event_sha256=`c594e1dfae2681f672589dadf9ec6be51d568393145e89944a84e043efdf93fc`
- #3: `228e8cda-1f07-43b7-aac7-bd251ab83b50` | 2026-07-26T00:27:24.000Z | REVIEW/changes_required | incident=`35f9687b-f98f-434f-a745-2ddb9d48721f` | lesson_key=`separate-object-process-and-commit-identities` | event_sha256=`acc8c52cbe3538167ed65ac14bfe44a1257aa02190643a0caf987e6f75fc5db1`
- #4: `c37e982f-392f-4665-9b81-ceaab2c0f669` | 2026-07-26T00:27:24.000Z | REVIEW/accepted | incident=`e7473ece-6582-4062-b54c-4534472b5413` | lesson_key=`review-until-independent-contract-convergence` | event_sha256=`d8884d0a5166c05bcbb906a1dfd60bdf8e2c93cfa75834a5c393a63e34ffe63b`
- #5: `c44d1441-660c-4d95-aa2b-a29f1f5e6506` | 2026-07-26T00:27:24.000Z | GATE/design_checks_passed | incident=`8fa04031-2333-47aa-8810-1159090fb79f` | lesson_key=`separate-design-gates-from-product-acceptance` | event_sha256=`2c43ee702226c3c3c6bbe4f39fa2bfe27f53b231ff61f32ab1e29026162e613f`
- #6: `0d7ed432-6957-4b7e-8a74-3e9679f5f30d` | 2026-07-26T00:27:24.000Z | STATE_CHANGE/corrections_completed | incident=`f756b688-c53c-4b37-806a-038328173d38` | lesson_key=`close-design-before-dependent-refresh` | event_sha256=`0fc9b220726068b333f1239db6b3642bbd1fabff49f63d06f57aa9e7b5db4bd4`
