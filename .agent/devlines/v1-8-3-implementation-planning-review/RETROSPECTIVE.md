# Retrospective — v1-8-3-implementation-planning-review

## Goal

# v1.8.3 Capability Factory 与双层领域记忆范围目标  **状态**：范围已批准；本文件用于冻结设计开发线，不代表产品能力已实现  **版本边界**：v1.8.3  ## 目标  在不扩大当前 B0 自定义能力运行时实现范围的前提下，为 v1.8.3 定义一套可长期扩展的 Agent 能力生产体系：  1. Agent 把用户目标、数据证据和所需输出解析为结构化 \`CapabilityRequirement\`； 2. 按“原生能力 → 已注册且已验证的第三方能力 → Agent 生成 Adapter → Agent 自研算法”的固定顺序解析实现； 3. 将依赖构建、能力验证、人工准入和分析运行彼此隔离； 4. 让不同来源的能力通过统一但非过度拟合的 capability profile、操作槽位、结果 facet、lineage 与 Artifact 边界进入 Workbench； 5. 复用现有 Agent Notebook 的推荐、并列、证据不足、备选项保留和确认后 materialize 契约； 6. 建立双层记忆：Project/RunFamily context index 始终是可重建事实索引；跨项目领域记忆的使用与迭代可由用户独立开启或关闭； 7. 保证记忆只能影响候选检索与检查计划，不能提升统计证据、绕过验证、自动准入或替用户确认。  ## 本设计线交付  - \`README.md\`：v1.8.3 范围地图、文档权威关系和分阶段边界； - \`capability-factory-design.md\`：能力解析、解析顺序、Adapter、构建与运行隔离、证据与准入、Notebook 接入； - \`domain-memory-design.md\`：双层记忆、用户开关、提升流程、隔离、过期与冲突语义； - 对既有 B0 设计补充上游产品定位链接，但不改变其实现边界。  ## 明确不做  - 本设计线不实现产品代码、数据库迁移、API、UI 或 Agent operation； - 不在 Workbench 主环境中动态安装依赖； - 不让 Agent 生成的代码直接接触用户文件、宿主文件系统、网络或主进程； - 不把用户选择、一次成功运行、作者自测或记忆命中解释为统计正确； - 不为所有算法强制 \`fit/predict/diagnose/summarize/plot\` 全接口； - 不复制或重写现有 Notebook/Graph/Trace 契约； - 不承诺任一具体算法、数据集、软件格式或固定年份的兼容结果； - 不执行 push、PR、merge、tag 或发布操作。  ## 完成标准  - v1.8.3 文档明确区分运行时、能力工厂、Notebook 编排、领域记忆和消费者投影； - 能力来源、证据等级、准入状态与用户可见标签彼此独立； - 第三方 Adapter 与 Agent 自研算法拥有不同风险路径； - 只有不执行不可信代码的依赖解析/获取平面可联网；组装、Adapter/算法验证和正式分析运行均断网； - 推荐“首选”必须来自已注册的支配/比较协议；并列或不可比时不得伪造唯一首选； - Project/RunFamily 记忆是 Graph/Trace/Option 的可重建索引，不是隐藏事实源； - 跨项目记忆具有 provenance、作用域、修订、状态、冲突和显式用户批准； - 所有新增文档通过结构、链接、边界和反过拟合自审，正式 FMS 记录可验证。

## Final status

COMPLETED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- #2 2026-07-26T03:11:00.000Z `plan_overfragmentation`; cause_status: `known`; cause: One executable program was split into twenty-three retained plan and objective documents, with repeated review beyond the real file-ownership boundaries.; resolution: `resolved`; lesson: Retain separate execution plans only where workers have independent state and disjoint file ownership.

## Root causes and solutions

- `plan-shards-require-real-concurrency`: occurrences=1; cause_status: `known`; root cause: One executable program was split into twenty-three retained plan and objective documents, with repeated review beyond the real file-ownership boundaries.; solution: `resolved`

## Added tests

- `tests/test_no_exercise_specific_naming.py`

## New rules

- `plan-shards-require-real-concurrency`: line experience occurrence(s)=1

## Future guidance

- Retain separate execution plans only where workers have independent state and disjoint file ownership.
- Scientific rigor is preserved by explicit gates; development efficiency is preserved by sharding only at independent ownership boundaries.

## Event index

- #1: `28d99458-06e8-4cb7-860e-2a687c633778` | 2026-07-25T23:36:40.057Z | STATE_CHANGE/line_started | incident=`d2807e06-d15a-4864-93a8-c40277c7fbcc` | lesson_key=`frozen-context-before-start` | event_sha256=`004b5101ed058fa5f7a24c05163241ee8195b812be22e71298295934ab94c161`
- #2: `8076ed64-9206-463a-821a-b31643d94122` | 2026-07-26T03:11:00.000Z | WASTE/plan_overfragmentation | incident=`1864b8d3-4805-40c9-bb8f-61c2b7b10251` | lesson_key=`plan-shards-require-real-concurrency` | event_sha256=`53ec1bb2717ac487254b5f2530025f51c3b23ef24710d7333c00ac40d186db67`
- #3: `3e1b74c1-7191-407a-a519-caef184151e9` | 2026-07-26T03:12:00.000Z | REVIEW/three_lane_plan_accepted | incident=`13dd0b58-f83f-4ce8-bd21-7c0aa50fb99c` | lesson_key=`rigor-with-bounded-parallelism` | event_sha256=`fe6983b62564c3c55a0c140073b5be918dfd757690a32e45815eec7dca27aff1`
- #4: `d132b1ea-6a6b-4182-8247-e90184ebb051` | 2026-07-26T03:13:00.000Z | GATE/planning_acceptance_passed | incident=`2df9aef0-41f6-4c55-adeb-3989de6971e7` | lesson_key=`planning-gates-match-planning-scope` | event_sha256=`c793b3ad67a54b936959dd67b64699a8ecf8c01da75514bb6a2be19e400cea09`
- #5: `fbeb20a6-6a53-451e-b2a2-08fa9cad1877` | 2026-07-26T03:14:00.000Z | STATE_CHANGE/planning_completed | incident=`1ac37e4b-a334-4cb4-a70d-d140c5e16b64` | lesson_key=`bounded-plan-ready-for-implementation` | event_sha256=`6743090263c70725b579de2eec71f1baa2ffbdf8a5e23010165160c7c5eef337`
