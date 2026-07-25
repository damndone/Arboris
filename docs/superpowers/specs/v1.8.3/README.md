# Workbench v1.8.3：Capability Factory 与双层领域记忆

**状态**：版本范围已批准；详细设计已写成，等待用户复审；产品实现尚未开始

**范围目标**：[`scope-objective.md`](./scope-objective.md)

## 1. 版本主张

v1.8.3 不把 `model.custom` 做成“缺包就安装、写几行代码、直接跑用户数据”的快捷入口。它建立一套 **Capability Factory**：把能力需求、实现来源、依赖构建、Adapter、算法验证、人工准入、Notebook 推荐、Graph 执行和领域记忆放进同一套可审计边界。

目标不是让 Agent 无限制写代码，而是让 Workbench 在现有算法不足时，仍能安全、可复现地扩展，同时不为某一个模型、作业、数据列、软件输出或固定样例过拟合。

```text
用户目标 + 数据证据
        ↓
CapabilityRequirement
        ↓
可信实现解析
        ↓
构建 / Adapter / 算法验证
        ↓
证据等级 + 人工准入
        ↓
Notebook AnalysisOption
        ↓ 用户确认
Draft → Graph → Run → Artifact → Trace
        ↓
可审计的记忆候选
```

## 2. 权威文档地图

| 层 | 权威文档 | 本版本中的职责 |
|---|---|---|
| B0 通用运行时 | [`../2026-07-25-model-custom-contract-design.md`](../2026-07-25-model-custom-contract-design.md) | 密封 input/output bundle、通用 facets、bundle identity、证据等级、严格隔离 |
| Capability Factory | [`capability-factory-design.md`](./capability-factory-design.md) | 能力需求、实现解析、Adapter、依赖构建、验证、准入、Notebook 接入 |
| 双层领域记忆 | [`domain-memory-design.md`](./domain-memory-design.md) | Project/RunFamily 可重建索引、跨项目领域记忆、用户开关、提升与冲突 |
| Notebook Option | [`../2026-07-22-v1.8.1-agent-notebook-analysis-option.md`](../2026-07-22-v1.8.1-agent-notebook-analysis-option.md) | Option 修订、推荐决策、确认与 materialize |
| Graph-first 投影 | [`../2026-07-23-v1.8.1-graph-first-notebook-projection-design.md`](../2026-07-23-v1.8.1-graph-first-notebook-projection-design.md) | Graph/Run/Artifact 事实源、证据门控推荐、deferred Option |
| 通用 workflow 词表 | `WORKFLOW_STEP_SPEC_CONTRACTS` 所在产品模块 | 已准入操作的单一协议来源；不得被自定义代码或自由 JSON 绕过 |

这些文档不是平行实现。B0 是执行地基，Capability Factory 是能力控制面，Notebook 是用户决策面，Graph/Trace 是事实与审计面，领域记忆只是受控的检索辅助。

## 3. 不可破坏的不变量

1. **Graph/Run/Artifact/Trace 是事实源。** Notebook 和记忆都不能复制一套隐藏执行状态。
2. **获取、组装、验证与分析运行分平面。** 只有不执行不可信代码的解析/获取平面可以联网；组装、Adapter/算法验证和正式分析都断网。
3. **Workbench 主环境不可动态安装依赖。** Agent 不得调用主环境的 `pip`、`conda`、系统包管理器或等价入口。
4. **固定实现优先级。** 原生能力 → 已注册且已验证的第三方能力 → Agent 生成 Adapter → Agent 自研算法。后一级只在前一级不能满足结构化需求时进入。
5. **证据与准入分轴。** `evidence_tier` 描述已有证据，`admission_state` 描述是否获准在某作用域使用；用户授权不能把 E1 变成 E2。
6. **推荐不等于列表排序。** 只有注册的支配或比较协议证明一个方案胜过所有可行备选时，Notebook 才能显示唯一首推。
7. **备选项仍是 typed Option。** 未选方案保留为 deferred Option，不预建 Graph 分支，也不退化成自然语言备注。
8. **记忆不产生统计事实。** 记忆可影响候选检索和检查计划，不能提升证据、自动准入、替代验证或替用户确认。
9. **接口按能力声明。** 能力只实现其 profile 要求的 operation slots；不强迫所有算法伪造 `fit/predict/diagnose/summarize/plot` 全套行为。
10. **消费者显式适配。** 可运行不等于可 Compare、可画图、可报告、可作下游 source。

## 4. v1.8.3 分阶段范围

版本范围是一组独立验收的切片，不是一条无限扩张的开发线。

### B0 — 通用自定义能力运行时

现有独立开发线，保持原边界：

- 通用输入角色与输出 facets；
- 服务端身份与 observation identity；
- exact / numeric / statistical 可复现性；
- E0–E3 证据派生；
- `untrusted_capability_v1` 严格隔离。

不接 Agent、不下载依赖、不改 workflow、不实现动态 registry。

### CF1 — Capability Requirement 与可信 Registry

- 结构化能力需求；
- capability profile 和 operation vocabulary；
- 实现来源、适用条件、消费者能力、比较协议；
- 确定性可行性过滤与固定优先级解析；
- 同级实现并列时保存 ResolutionSet，并由独立实现选择决议产生唯一 binding；
- 证据等级和准入状态分轴。

### CF2 — 依赖构建与 Bundle Admission

- `dependency.request`；
- 版本、哈希、平台和传递依赖锁定；
- 许可证、漏洞、来源和 SBOM 检查；
- 隔离构建、CAS bundle、离线适配测试；
- 明确的人类批准与撤销。

### CF3 — Adapter Factory 与算法验证

- Agent 为已批准依赖生成 Adapter；
- 没有可信实现时，才允许 Agent 提交自研算法候选；
- 合成真值、边界、性质、数值稳定性、独立对照、随机性和性能测试；
- 失败只产生验证证据，不产生已准入能力。

### CF4 — Notebook、`model.custom` 与 Graph 接入

- `model.custom` 作为首个可信类型化适配器；
- 复用现有 RecommendationDecision，并以版本化 Notebook Option/执行授权扩展接入；
- 已准入能力可在一次普通“确认并运行”中走完受限全流程；
- 组合授权使用原子 receipt、唯一 Run intent 和可恢复重放语义；
- dependency、作者代码、准入和 promotion 继续使用独立高风险确认；
- materialize 后仍走 Draft → Run → Artifact，不建立 Notebook 执行器。

### MEM1 — Project/RunFamily context index

- 从 Graph、Trace、Option、用户决策和验证结果生成可重建索引；
- 只在当前项目/RunFamily 作用域内使用；
- 删除索引后可从规范事实重建；
- 不持有原始行数据，不把选择记录解释成正确答案。

### MEM2 — 跨项目领域记忆存储与用户控制

- 用户分别显式开启“使用跨项目领域记忆”和“跨项目记忆迭代”；
- 定义 namespace、entry、candidate、revision、provenance 和适用谓词；
- 支持手动创建、批准、归档、删除和有界检索；
- 扩大作用域需要新 revision 和独立批准。

### MEM3 — 受限后台审阅与记忆治理

- 后台审阅器只读取有界 Trace 摘要并产生候选；
- 用户批准后才提升为可检索领域条目；
- 增加冲突、`review_after`、stale、撤销和使用记录；
- 审阅器无 raw data、shell、network 或 capability runtime。

## 5. 跨切片确认语义

必须区分四种行为：

| 行为 | 最低确认边界 |
|---|---|
| 对已准入能力生成 Notebook Option | 不执行，只记录 typed proposal |
| 对已准入、低风险、作用域匹配的 1.2 Option 执行 | 可选择版本化“确认并运行”组合授权；内部仍经过 Draft/Run/Artifact gates，失败后不自动重试 |
| 下载依赖、接受 lock manifest、运行作者代码验证 | 独立高风险确认，不得打包进普通多步操作 |
| 将能力或领域记忆提升到更宽作用域 | 独立人工审查与批准，可撤销 |

用户选择 Option 只记录方案决策；只有明确的 materialize 或 execute 授权才允许推进相应状态。任何选择或授权都不表示认可算法正确、批准依赖、提升证据或永久记忆。

## 6. 与 `WORKFLOW_STEP_SPEC_CONTRACTS` 的关系

`WORKFLOW_STEP_SPEC_CONTRACTS` 继续是通用 workflow 的单一协议来源，统一生成：

- 校验器允许的 step type 与字段；
- 拒绝消息中的合法词表；
- 发布给 Agent 的协议提示。

Capability Factory 不建立平行的自由 step 入口。只有已经准入、具有稳定 operation contract、风险边界和服务端 dispatcher 的能力，才可在后续切片中通过修改这一处进入通用 workflow。

以下对象永远不能作为普通 workflow step 的自由 payload：

- 源代码；
- dependency request 或 lock manifest；
- admission / promotion 指令；
- 未准入 bundle；
- 跨项目记忆写入或批准。

## 7. 版本完成定义

v1.8.3 的“设计完成”与“产品完成”必须分开报告。

本目录完成只表示：

- 范围、契约、状态机、安全边界和分阶段验收已形成；
- 与 B0、Notebook、Graph、Trace、workflow 的权威关系清楚；
- 没有为某一示例结果或单一算法收窄根契约。

产品完成仍需每个切片各自建立正式开发线、实现、测试、隔离验证、浏览器验收（如有 UI）和发布授权。任何切片通过都不能代替其他切片的验收。
