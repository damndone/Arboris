# v1.8.3 双层领域记忆设计

**状态**：详细设计已完成，等待用户复审；实现尚未开始

**范围入口**：[`README.md`](./README.md)

**Capability Factory**：[`capability-factory-design.md`](./capability-factory-design.md)

## 0. 决策摘要

Workbench 不把“Agent 记忆”实现成一个不断追加、默认跨项目可见的自由文本文件，也不把用户历史选择当作训练标签。

采用两层：

1. **Project/RunFamily 工作记忆**：Graph、Trace、Option、用户决策和验证结果的有界、可重建索引；
2. **跨项目领域记忆**：从有界 Trace 摘要产生候选，经用户显式批准后进入的版本化、带适用条件与 provenance 的知识条目。

用户拥有两个独立开关：

- **使用跨项目领域记忆**：是否在当前规划中检索已批准领域记忆；
- **跨项目记忆迭代**：是否允许分析完成后生成新的跨项目记忆候选。

关闭“跨项目记忆迭代”不删除旧记忆；关闭“使用跨项目领域记忆”立即停止检索，但不删除或改写条目。Project/RunFamily 层在实现中称为 `project_context_index`，它是规范事实的加速索引，不受跨项目记忆开关控制。删除、归档、恢复和重新批准都是单独的用户动作。

记忆只能帮助 Agent 更快找到候选、选择检查、提醒已知风险和复用经过审查的工作方式。它不能：

- 提升 capability evidence tier；
- 绕过输入可行性、验证、准入、Artifact Contract 或 Recommendation Validator；
- 自动安装依赖、执行代码、创建 Graph 分支或推进 active head；
- 把“用户曾选过”解释成“统计上正确”；
- 自动把个人偏好推广为领域规则。

## 1. 为什么是双层

一个分析项目内已经有强事实对象：Dataset、Graph、Draft、Run、Artifact、Diagnostic、Compare、Notebook Option 和 Core Trace。再写一份自由文本“记忆”会形成不可重建的第二事实源。

但跨项目复用确有价值，例如：

- 某领域常见数据条件需要先做哪些检查；
- 某类输入约束经常阻塞哪些候选；
- 某 capability 在什么条件下适用或容易失败；
- 用户稳定、明确表达过的工作偏好；
- 已通过复核的分析流程经验。

因此项目内层强调**重建和事实引用**，跨项目层强调**批准、适用范围、版本和冲突**。两层存储、权限和生命周期必须分开。

## 2. 状态所有权

### 2.1 规范事实

以下对象保持权威：

| 事实 | 权威来源 |
|---|---|
| 数据与分析 lineage | Dataset / Graph |
| 待执行方案 | PipelineDraft |
| 执行结果 | Run / Artifact / Diagnostic |
| 未 materialize 意图 | Notebook Option / RecommendationDecision |
| 用户选择与确认 | append-only decision records / Core Trace |
| capability 证据与准入 | Capability Registry / Evidence / Admission |
| 当时 Agent 看到什么 | Context manifest / compiled context hash |

记忆只引用这些对象，不覆盖它们。

### 2.2 Project/RunFamily 工作记忆

这是一个 materialized index/cache，不是新的事实存储。删除后必须能从规范事实重建。

它可以包含：

- 当前目标和已确认约束的引用；
- Graph/RunFamily 演化摘要；
- 已执行检查与有效 evidence refs；
- Option 状态、deferred 方案和 stale 原因；
- capability 解析、失败和验证结果；
- 用户在当前项目中的显式决策；
- 尚未解决的假设、警告和后续问题。

它不得包含：

- 原始行数据的副本；
- 未经脱敏的长自由文本；
- 项目外身份或路径；
- 由模型猜出的用户偏好；
- “该方案正确”之类没有权威证据的结论。

### 2.3 跨项目领域记忆

跨项目条目是用户拥有的、版本化的检索资产。它不是项目事实，也不是模型参数更新。

条目只有在：

- 有可解析 source trace refs；
- 经过有界候选生成；
- 通过 schema、隐私、冲突和证据检查；
- 用户明确批准；

之后才可处于 `active` 并被检索。

## 3. 用户控制

### 3.1 两个独立开关

```json
{
  "cross_project_domain_memory_use": false,
  "cross_project_domain_memory_iteration": false
}
```

默认建议均为关闭，直到用户在产品中主动设置。项目或组织策略可以进一步禁止，但不能静默替用户开启。

`cross_project_domain_memory_use=false`：

- 不查询跨项目 store；
- 不把领域记忆加入 compiled context；
- 不影响 Project/RunFamily 工作索引；
- Trace 记录“未使用跨项目领域记忆”，便于解释当时上下文。

`cross_project_domain_memory_iteration=false`：

- 不在分析后启动跨项目候选生成；
- 不自动删除现有 active/stale/archived 条目；
- 项目内可重建索引仍可更新，因为它只是事实投影。

### 3.2 单次覆盖

用户可对一次规划临时选择“本次不使用跨项目领域记忆”或“本次不生成跨项目候选”。单次覆盖写入 Trace，但不永久改变全局偏好。

### 3.3 可见性

若使用了记忆，Notebook 必须显示有界来源摘要：

- 使用了哪些 memory revision；
- 为什么满足适用谓词；
- 影响了哪个候选或检查；
- 是否存在冲突、过期或低置信提示。

不能只显示“基于你的历史”而隐藏实际条目。

## 4. 领域记忆契约

示意结构：

```json
{
  "contract_version": "domain_memory_entry_v1",
  "memory_id": "server-issued-stable-id",
  "revision": 4,
  "namespace_id": "server-owned-namespace",
  "owner_scope": {
    "kind": "user",
    "owner_ref": "server-owned-subject"
  },
  "visibility_scope": "private",
  "promotion_scope": "user",
  "domain_tags": ["registered-domain-tag"],
  "memory_kind": "workflow_lesson",
  "applicability_predicates": [
    {
      "predicate_id": "registered-predicate-id",
      "operator": "registered-operator",
      "value": "bounded-typed-value"
    }
  ],
  "compact_lesson": "Bounded, reviewed text.",
  "recommended_effect": {
    "kind": "candidate_retrieval_hint",
    "target_refs": ["registered-capability-or-inspection-id"]
  },
  "source_trace_refs": [
    {
      "project_pseudonym": "scoped-reference",
      "trace_summary_hash": "sha256",
      "evidence_refs": ["content-addressed-ref"]
    }
  ],
  "evidence_status": "observed_repeatedly",
  "approved_by": "user-or-authority-ref",
  "approved_at": "timestamp",
  "approval_signature_ref": "server-owned-approval-record",
  "status": "active",
  "valid_from": "timestamp",
  "review_after": "timestamp",
  "supersedes_revision": 3,
  "conflicts_with": ["memory-id@revision"],
  "created_by": "memory-curator-version",
  "content_hash": "sha256"
}
```

### 4.1 必需语义

- `memory_id` 稳定，修订 append-only；
- `namespace_id`、`owner_scope`、`visibility_scope` 和 `promotion_scope` 由服务端独占，进入 entry identity 与 content hash；
- `domain_tags` 来自版本化词表，不能替代适用谓词；
- `applicability_predicates` 是检索 hard gate，不只是一段文本；
- `compact_lesson` 有字数与敏感信息上限；
- `recommended_effect` 只能使用注册的有限 effect 类型；
- `source_trace_refs` 必须能回到有界证据摘要；
- `evidence_status` 只描述记忆材料，不等于 capability E0–E3；
- `status` 为 `active | stale | archived`；
- `conflicts_with` 显式表达不能同时无条件应用的条目；
- 任一语义字段变化产生新 revision 和 content hash。

`content_hash` 覆盖待批准内容、作用域和 provenance，但排除 `approved_by`、`approved_at` 与 `approval_signature_ref`，避免循环身份；批准记录签署 `content_hash + revision + scope + approver + timestamp`。扩大 visibility 或 promotion scope 必须产生新 revision，并在目标 scope 通过独立授权。复制相同正文到更宽 namespace 不能复用原批准签名。

### 4.2 首版 `memory_kind`

- `workflow_lesson`：在某条件下建议的分析顺序或检查；
- `capability_caveat`：能力适用限制或已知失败模式；
- `inspection_hint`：候选生成前值得执行的注册检查；
- `user_working_preference`：用户明确表达、且不改变统计门槛的工作偏好；
- `reporting_preference`：输出呈现偏好。

以下内容不得作为领域记忆：

- 原始数据、识别符或自由文本样本；
- 密钥、路径、环境变量或内部凭证；
- 未经批准的 dependency/code；
- “永远使用某算法”等无适用谓词的绝对规则；
- capability evidence tier 或 admission 的复制品；
- 用户选择自动推断出的隐性人格、敏感属性或偏好。

## 5. Project/RunFamily 工作索引

### 5.1 构建

索引器读取规范对象的有界投影：

```text
Graph/Run/Artifact summaries
+ Notebook Option/Decision revisions
+ Core Trace events
+ Capability validation/admission refs
→ project_context_index_v1
```

索引记录 `source_manifest`、每个来源 hash、构建器版本、预算和 omissions。相同输入必须产生确定性索引 hash。

### 5.2 使用

Context Compiler 可以从索引获取当前项目的相关事实摘要，但仍要：

- 验证 source refs 和 freshness；
- 应用项目访问控制；
- 在预算内选取；
- 把所见内容写入 context manifest；
- 关键 omission 导致 `insufficient_evidence`，不能让记忆补猜。

### 5.3 失效与重建

Graph head、Option revision、用户目标、capability revision 或上游 evidence 变化时，只重建受影响分区。索引损坏或 schema 升级时可整体删除并重建；不得以“重建困难”为由把它升级为隐藏权威数据。

索引 stale、损坏或重建失败时，唯一允许的 fallback 是由 Context Compiler 直接从 Graph、Trace、Option 和其他规范对象编译当前上下文，并使用相同的访问控制、freshness、预算和 omission manifest。不得继续使用旧索引冒充当前事实；若直接编译也失败，则显式返回 context failure 或 `insufficient_evidence`。

## 6. 跨项目候选生成

### 6.1 触发条件

只有同时满足：

- `cross_project_domain_memory_iteration=true`；
- 当前分析达到明确的审阅点；
- Trace summary 完整且未被关键 omission 阻塞；
- 项目策略允许生成候选；

才可创建 `MemoryCandidate`。

适合的审阅点包括：

- 一次分析路径完成或被明确放弃；
- capability 验证或 admission 审查完成；
- 同类失败重复出现；
- 用户主动选择“总结为领域经验”。

### 6.2 后台审阅器边界

后台审阅器只能读取：

- bounded Core Trace summary；
- 去敏的 context/evidence manifest；
- capability profile、错误码和验证摘要；
- 用户显式标注的经验候选。

它不能：

- 读取原始数据行；
- 获取 shell、网络、包管理器或 capability runtime；
- 扫描项目目录或其他项目；
- 执行分析；
- 修改 Graph、Option、Run、Artifact、capability 或正式 memory store；
- 自己批准候选。

它的唯一写入是有界 `MemoryCandidate`，进入待审队列。

### 6.3 候选不是记忆

候选状态：

```text
proposed → needs_review → approved | rejected | expired
```

用户可编辑 compact lesson、适用谓词、领域标签和作用范围。编辑后重新校验并形成候选 revision。只有 `approved` 动作才创建或修订正式 memory entry。

## 7. 检索与上下文注入

### 7.1 检索顺序

当 `cross_project_domain_memory_use=true`：

1. 按用户、组织、项目策略和 store namespace 做硬隔离；
2. 只取 `active` 且未过 review/expiry gate 的 revision；
3. 计算 applicability predicates；
4. 排除与当前事实冲突或依赖已撤销能力的条目；
5. 检测 `conflicts_with` 和同主题互斥规则；
6. 在固定预算内排序；
7. 输出条目 revision、命中理由、冲突和 omission；
8. Context Compiler 将实际注入内容写入 manifest/hash。

结构化适用谓词是 hard gate。语义检索或全文检索只可在通过 hard gate 的集合内帮助排序，不能把不适用条目拉进上下文。

### 7.2 排序信号

可使用：

- predicate specificity；
- domain tag 与当前 goal 的匹配；
- source diversity；
- 最近复审时间；
- repeated observation 数量；
- 用户显式 pin；
- 当前 capability/inspection 的直接引用。

不得使用：

- “用户以前选过”作为正确性分数；
- 未解释的模型置信度；
- capability evidence tier 的替代推断；
- 跨 namespace 的热门程度；
- 原始结果好坏而没有可比协议。

### 7.3 对 Agent 的影响

允许的 `recommended_effect.kind` 首版仅包括：

- `candidate_retrieval_hint`
- `inspection_plan_hint`
- `assumption_check_hint`
- `known_caveat`
- `reporting_preference`

记忆不得直接产生：

- `recommended` RecommendationDecision；
- capability admission；
- dependency approval；
- Draft/Run/Artifact；
- source eligibility；
- evidence tier。

Agent 必须把记忆当作待当前项目证据验证的提示。

## 8. 冲突、陈旧与撤销

### 8.1 状态

```text
active → stale → active
active | stale → archived
archived → new revision under explicit restore
```

`stale` 表示可能仍有历史价值，但不能自动注入正常规划。触发条件包括：

- 引用的 capability、protocol 或 vocabulary 被 supersede/revoke；
- 到达 `review_after`；
- 新证据与条目冲突；
- 适用谓词 schema 变化；
- 来源 Trace 或 evidence 被依法删除；
- 用户标记不再适用。

### 8.2 冲突处理

冲突不通过“较新覆盖较旧”静默解决。系统：

- 保留两个 revision；
- 标记冲突关系和证据来源；
- 默认不把冲突条目作为自动 hint；
- 允许用户审阅后归档、收窄谓词或创建综合新 revision。

### 8.3 删除与保留

用户可归档或请求删除跨项目条目。若审计政策要求保留批准/撤销事实，可保留最小 tombstone 和内容 hash，但不保留 compact lesson 或源摘要。历史 Run 仍保留“当时使用了哪个 memory revision”的引用；若正文已删除，显示不可用而不伪造内容。

## 9. 隐私与隔离

- namespace 必须使用显式 `owner_id / organization_id / profile_id` 等 scope key，不能依赖目录路径碰巧隔开；
- 每次查询都带 scope predicate，store 层拒绝无 scope 查询；
- 项目 pseudonym 不能反推出本地路径、客户名或原始标识；
- source summary 在候选生成前执行敏感信息扫描和预算限制；
- 跨项目条目默认不携带具体数值，确有必要时使用去标识、带单位和适用范围的有界统计；
- 组织共享需要独立的提升和撤销授权，个人批准不能自动变成组织记忆；
- 导出、删除、停用、查看 provenance 和查看使用记录是用户可操作能力。

## 10. 与 Capability Factory 的边界

记忆可使 Agent 更早想到一个已注册 capability 或 inspection，但 Resolver 仍按固定优先级和当前 Requirement 运行。

例如：

```text
memory hit
→ add candidate or inspection hint
→ current-data feasibility
→ current capability evidence/admission
→ registered comparison protocol
→ Notebook decision
```

不能变成：

```text
memory says it worked before
→ skip checks
→ install or execute
→ recommend
```

如果记忆引用的 capability 已撤销、bundle 不可用或当前输入谓词不满足，该 hint 被拒绝并写入 Trace。

## 11. 参考 Hermes Agent 时采用与不采用的部分

本设计参考 Hermes Agent 的公开实现与文档，但不复制其存储结构。

采用的思路：

- memory provider 与 Agent 主循环分离；
- 可配置的 memory enable 开关；
- 写入前批准；
- profile/作用域概念；
- active、stale、archive 类生命周期；
- 后台 curator 只提交候选。

Workbench 增加更强边界：

- 项目事实与跨项目知识分层；
- store 查询必须带 scope key；
- Trace/evidence provenance；
- applicability predicates；
- 记忆与统计证据、capability admission、Notebook recommendation 分轴；
- 无 raw data、无 shell/network/runtime 的后台审阅器。

参考：

- [Hermes MemoryManager source](https://github.com/NousResearch/hermes-agent/blob/main/agent/memory_manager.py)
- [Hermes configuration documentation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/configuration.md)
- [Hermes profiles documentation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/profiles.md)
- [Hermes profile memory isolation issue #10376](https://github.com/NousResearch/hermes-agent/issues/10376)

最后一项说明仅依赖路径或 profile 目录做隔离存在泄漏风险。Workbench 把它当作边界测试输入，不把公开 issue 当成 Hermes 全部版本都必然存在同一缺陷的证明。

## 12. 失败语义

稳定错误类别：

- `PROJECT_MEMORY_INDEX_STALE`
- `PROJECT_MEMORY_INDEX_REBUILD_FAILED`
- `DOMAIN_MEMORY_DISABLED`
- `DOMAIN_MEMORY_SCOPE_REQUIRED`
- `DOMAIN_MEMORY_SCOPE_MISMATCH`
- `DOMAIN_MEMORY_ENTRY_INVALID`
- `DOMAIN_MEMORY_ENTRY_STALE`
- `DOMAIN_MEMORY_ENTRY_CONFLICTED`
- `DOMAIN_MEMORY_SOURCE_UNAVAILABLE`
- `DOMAIN_MEMORY_CANDIDATE_REDACTION_FAILED`
- `DOMAIN_MEMORY_APPROVAL_REQUIRED`
- `DOMAIN_MEMORY_BUDGET_EXCEEDED`
- `DOMAIN_MEMORY_EFFECT_FORBIDDEN`

跨项目领域记忆失败不应阻止用户在关闭该能力后继续合法分析；但系统必须显式记录“本次未使用跨项目领域记忆”及原因，不能静默假装已利用历史经验。Project context index 失败则按 §5.3 从规范对象直接编译，不能被领域记忆 fallback 掩盖。

## 13. 测试与验收

### 13.1 Project/RunFamily 层

- 删除索引后从相同规范事实重建出相同 hash；
- Graph/Option/evidence 变化只使相关分区 stale；
- 索引不含 raw rows、宿主路径或自由敏感文本；
- stale/omission 不会被当作完整证据；
- Notebook/Graph 事实与索引冲突时，权威事实获胜。

### 13.2 跨项目层

- 两个跨项目开关完全独立；
- `cross_project_domain_memory_iteration` 关闭时不生成候选；
- `cross_project_domain_memory_use` 关闭时 context manifest 不含领域条目；
- 未批准候选不能被检索；
- revision append-only，旧 revision 可追踪；
- active/stale/archived 转换与恢复有明确授权；
- scope 缺失或不匹配 fail closed；
- path/profile 名相同不能造成跨 namespace 泄漏；
- source refs 缺失、删除或冲突时条目 stale；
- 预算、敏感信息和过长文本被拒绝而非静默截断成错误结论。

### 13.3 不越权

- 记忆命中不能改变 E0–E3；
- 记忆命中不能创建 admission；
- 记忆命中不能把 tied 变成 recommended；
- 记忆命中不能跳过当前数据 inspection；
- 记忆命中不能触发 dependency、代码、Draft 或 Run；
- 用户选择 Option 不自动产生领域记忆；
- 后台审阅器不能读取 raw data、联网或调用 capability runtime。

## 14. 分阶段实施

### MEM1

- 定义 `project_context_index` schema；
- 从现有 Graph/Trace/Option 构建确定性有界索引；
- 接入 Context Compiler；
- 完成重建、freshness、预算和 no-raw-data 测试。

### MEM2

- 定义 domain entry、candidate、revision 和 store scope；
- 实现两个用户开关；
- 实现手动创建/批准/归档/删除；
- 实现有 provenance 的 bounded retrieval；
- 完成跨 namespace 隔离测试。

### MEM3

- 增加无 shell/network/raw-data 的后台审阅器；
- 只提交候选；
- 增加冲突检测、review_after 和 stale workflow；
- 增加用户可见的来源与使用记录。

### 后续而非 v1.8.3 默认范围

- 组织级共享和治理；
- 更复杂的语义检索；
- 自动质量评分；
- 跨用户聚合经验；
- 任何形式的模型权重训练或微调。

这些能力需要独立隐私、治理和评估设计，不能从“记忆迭代”四个字直接推导为已授权。
