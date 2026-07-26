# v1.8.3 Capability Factory 设计

**状态**：详细设计已完成，等待用户复审；实现尚未开始

**范围入口**：[`README.md`](./README.md)

**运行时地基**：[`../2026-07-25-model-custom-contract-design.md`](../2026-07-25-model-custom-contract-design.md)

## 0. 决策摘要

Capability Factory 是 Workbench 的**能力控制面**，不是一台能在主环境里任意装包和执行代码的 Agent。

它接受结构化能力需求，先寻找可信现成实现；没有匹配时才生成 Adapter；没有可用依赖时才允许提交自研算法候选。所有非原生实现先构建、验证、获得限定作用域准入，然后才能被 Notebook 作为候选方案提出，并沿现有 Draft → Graph → Run → Artifact 路径执行。

```text
CapabilityRequirement
  → feasibility filter
  → implementation resolver
  → build / adapt / author
  → validate
  → evidence_tier
  → admission decision
  → AnalysisOption
  → user confirmation
  → Draft / Run / Artifact / Trace
```

核心决策：

- `model.custom` 是第一个 Workbench 类型化适配器，不是通用根契约；
- Adapter 的操作槽位按 capability profile 声明，不强制全接口；
- 可信控制面负责输入校验、调用、结果 envelope、序列化和输出验证；
- 作者代码只能实现已声明的 operation entrypoint，不能声明自己已验证、已准入或可作为下游 source；
- `evidence_tier` 与 `admission_state` 是两条正交轴；
- “首推方案”由 Notebook Recommendation Validator 判定，不由能力解析器或 Agent 自报；
- 只有不执行不可信代码的依赖解析/获取平面可联网；组装、Adapter/算法验证和正式分析运行均断网；
- 能力记忆和用户历史不能绕过 feasibility、evidence 或 admission。

## 1. 目标与非目标

### 1.1 目标

- 支持模型、统计检验、诊断、变换、优化、预测及后续未知分析类别，而不把根契约写成某一类估计器。
- 让原生实现、已验证第三方实现、Agent 生成 Adapter 和 Agent 自研算法进入同一 Graph/Trace/Artifact 体系。
- 以能力语义和输出要求解析实现，不以包名、函数名或软件菜单名作为根身份。
- 对依赖、Adapter、算法代码、运行环境和验证材料形成可复现 bundle identity。
- 允许用户保留备选分析路径，并在以后重新验证后选择。
- 让能力被撤销、过期或升级时，不破坏历史 Run 的可解释性和 rerun 身份。

### 1.2 非目标

- 不提供任意 shell、包管理器、网络或宿主文件系统访问。
- 不保证 Agent 能实现所有数学上可描述的算法。
- 不把“运行成功”“结果看起来接近”“用户同意”当作统计正确。
- 不自动把新能力注册到全局进程内 handler registry。
- 不自动授予报告、图表、诊断、Compare、下游 source 或 promotion 能力。
- 不用单一综合分数强排本质上不可比的分析方案。
- 不复制 Notebook、Graph、Run、Artifact、Trace 或 workflow 的既有状态机。

## 2. 分层架构

### 2.1 可信控制面

可信 Workbench 代码独占：

- `CapabilityRequirement` 校验；
- Registry 查询与可行性过滤；
- 解析优先级与风险策略；
- 输入角色绑定、数据作用域和 observation identity；
- bundle、实现、环境、证据、准入和授权身份；
- 沙箱调用、资源预算和结果 envelope；
- Artifact Contract、lineage、Trace、rerun 与 consumer admission；
- 用户确认和撤销。

这些字段不能由作者代码返回，也不能从自由文本推断后直接持久化。

### 2.2 通用自定义能力运行时

B0 运行时只理解：

```text
sealed input bundle
+ capability operation spec
+ immutable handler bundle
→ bounded output bundle
```

它不理解某个具体算法，也不决定 Notebook 是否推荐、结果能否 Compare 或能力能否被提升。

### 2.3 Capability Factory

Factory 负责：

- 解析需求；
- 查找和筛选实现；
- 提议依赖或作者代码；
- 生成 Adapter；
- 组装验证计划；
- 产生 evidence packet；
- 提交 admission proposal。

Factory 不直接执行用户的正式分析，也不推进 Graph active head。

### 2.4 Workbench 类型化适配器

类型化适配器把领域语义映射到通用运行时。例如 `model.custom` 可负责：

- 模型输入角色；
- `fit`、`predict` 等已声明操作；
- 模型结果 facets；
- 模型消费者能力；
- 模型级 recommendation protocol。

未来其他 capability kind 使用自己的可信适配器，不必伪装成模型。

## 3. `CapabilityRequirement`

Agent 先把用户目标和有界数据证据转换为版本化需求，而不是先猜一个包。

示意结构：

```json
{
  "contract_version": "capability_requirement_v1",
  "requirement_id": "server-issued",
  "requirement_revision": 1,
  "capability_kind": "model",
  "goal_ref": "project-scoped-user-goal",
  "data_context_refs": ["compiled-context-hash", "evidence-pack-hash"],
  "input_roles": [
    {
      "role_id": "response",
      "semantic_type": "registered-vocabulary-id",
      "cardinality": {"min": 1, "max": 1},
      "constraints": ["registered-predicate-id"]
    }
  ],
  "required_operations": ["fit", "summarize"],
  "optional_operations": ["predict", "diagnose"],
  "required_output_facets": ["parameter_table", "metric_set"],
  "required_consumer_capabilities": {
    "report_projection": true,
    "compare_adapter": false
  },
  "statistical_assumptions": ["registered-assumption-id"],
  "reproducibility_requirement": "numeric",
  "resource_budget_ref": "capability-budget-v1",
  "requested_constraints": {
    "maximum_source_tier": "registered-third-party",
    "minimum_evidence_tier": "E2"
  },
  "omissions": []
}
```

### 3.1 根字段的语义

- `capability_kind` 是可扩展的版本化词表，不是任意字符串。
- `input_roles` 描述语义角色和约束，不固定为某几个列名。
- `required_operations` 是解析硬条件；`optional_operations` 不得被伪造成已支持。
- `required_output_facets` 描述下游真正需要的结果，不要求所有模型输出同一表。
- `required_consumer_capabilities` 把“可运行”与“可进入报告/Compare”等能力分开。
- `requested_constraints` 只是 Agent 或用户提出的收紧条件，不能放宽服务端政策。
- `omissions` 明确记录因预算、隐私或数据条件无法获得的关键上下文。

### 3.2 需求修订

需求不可就地修改。用户目标、数据 fingerprint、输出要求、风险上限或关键假设变化时创建新 revision。后续 candidate、evidence、Option 和 Run 都钉住确切 revision。

### 3.3 服务端 `ResolutionPolicySnapshot`

Agent 不拥有有效风险上限、证据下限或允许来源。服务端为每次解析生成不可变 `ResolutionPolicySnapshot`，至少包含：

- 用户、项目、组织和 operation policy 的版本引用；
- `effective_maximum_source_tier`；
- `effective_minimum_evidence_tier`；
- 允许的 implementation sources；
- dependency/code 确认要求；
- 资源与数据暴露上限；
- runtime policy；
- 计算这些有效值的规则版本和 hash。

有效政策取所有适用政策与 `requested_constraints` 的**最严格交集**。Agent 只能请求更严格限制；缺失字段、未知政策或不能形成交集时 fail closed。Resolver、Option 和 Run 都钉住该 snapshot。

## 4. 实现解析协议

### 4.1 固定优先顺序

解析顺序固定为：

1. Workbench 原生 Analysis Pack；
2. 已注册、已验证且当前作用域已准入的第三方能力；
3. 基于已批准依赖由 Agent 生成的 Adapter；
4. Agent 自研算法候选。

“优先”不表示原生实现无条件获胜。每一级先经过结构化可行性检查；不能满足 required operation、输入约束、输出 facet、消费者要求、资源上限或证据下限的实现，不属于可行候选。

只有当前一级没有可行候选时，解析器才进入下一级。不得仅因 Agent 更熟悉某个库、记忆中曾用过某种方法或生成代码更方便而跳级。

### 4.2 可行性先于排序

解析器先做 hard filter：

- profile 与 requirement 版本兼容；
- 输入角色和数据约束可满足；
- required operation 全部存在；
- required output facets 与 Artifact Contract 可满足；
- 独立 `EvidenceAssessment` 满足 policy snapshot 的 evidence floor，且其最新服务端 validity record 仍为 `valid`；
- 不可变 `ScopedAdmissionDecision` 的 outcome 为 `admitted`，其最新 append-only `AdmissionValidityRecord` 在当前作用域为 `valid`，且依赖的 assessment、bundle 和 runtime policy 均未失效；
- 不可变 `ImplementationBundleRevision` 的最新 `ImplementationBundleValidityRecord` 为 `valid`；
- bundle 与 runtime policy 当前可执行；
- 当前宿主具有 identity 一致的不可变 `HostContainmentAssessment`，且最新 `HostContainmentValidityRecord=valid`；
- capability 未撤销、未过期、未受阻；
- 风险不超过用户和项目策略；
- 资源预算在硬上限内。

过滤后：

- 同一优先级只有一个可行候选：服务端生成 `ImplementationSelectionDecision(reason=sole_feasible_candidate)`；
- 同一优先级有多个候选：使用该 cohort 注册的 implementation-selection protocol；
- 没有共同 protocol 或证据不足：返回 `selection_required`，不让 Agent 任意选一个；
- 所有级别都无可行候选：返回 capability gap，再决定是否提议构建。

### 4.3 两种“推荐”不能混为一谈

Capability Resolver 选择“用哪个实现满足同一个 capability requirement”。

Notebook Recommendation Validator 选择“用户目标下哪个分析方案具有压倒性证据”。

前者不能把某个实现解析成功写成分析首推；后者也不能把一个未准入实现变成可执行能力。

### 4.4 同级实现并列

每次解析先生成不可变 `CapabilityResolutionSet@1.0`：

- requirement 与 policy snapshot；
- 当前最高可行来源层级；
- 完整 candidate implementation refs；
- 每个候选的 profile、bundle、evidence、admission 与 freshness；
- hard-filter 通过/拒绝理由；
- implementation-selection protocol 及结果；
- `outcome = resolved | selection_required | gap`。

最高可行层级只有一个候选时，服务端仍写 `ImplementationSelectionDecision@1.0`，`reason=sole_feasible_candidate`，钉住完整 ResolutionSet，且不得伪造 comparison protocol。这样每条 resolved path 都有同一种 binding identity。

有多个候选且注册协议能唯一选择时，服务端写 `ImplementationSelectionDecision@1.0(reason=registered_protocol)` 并生成最终 binding。

无共同协议、协议结果并列或实现间存在不可约取舍时：

1. Factory 返回 `selection_required`，展示实现来源、证据、资源、许可证、限制和不可比原因；
2. 用户可显式选择一个实现，或取消/要求进一步检查；
3. 选择写入独立 `ImplementationSelectionDecision@1.0`；
4. 服务端随后生成唯一 `CapabilityResolutionBinding@1.0`。

实现选择不借用 Notebook `RecommendationDecision`。前者解决“同一 capability 用哪个实现”，后者解决“用户目标下选择哪个分析方案”。所有 resolved path 都必须有 selection decision；没有时不生成可执行 Option。

## 5. Capability Profile 与 Adapter

### 5.1 `CapabilitySemanticProfileRevision`

每个能力注册一个不携带动态信任状态的语义 profile：

```json
{
  "profile_version": "capability_semantic_profile_v1",
  "capability_id": "stable-server-id",
  "capability_revision": 3,
  "capability_kind": "model",
  "applicability_predicates": ["registered-predicate-id"],
  "operations": {
    "fit": {"required_inputs": ["response", "features"]},
    "predict": {"required_inputs": ["new_features"], "optional": true}
  },
  "output_facets_by_operation": {
    "fit": ["parameter_table", "metric_set"],
    "predict": ["indexed_series"]
  },
  "consumer_capabilities": {
    "report_projection": "registered-adapter-id",
    "diagnostic_adapter": null,
    "figure_provider": null,
    "compare_adapter": "registered-adapter-id",
    "downstream_source": null,
    "rerun": "registered-adapter-id"
  },
  "recommendation_protocol_refs": []
}
```

Profile 可在实现和验证前存在，用于表达 requirement、validation plan 和候选语义。它不保存“当前 evidence”“当前 admission”或 handler bundle。未知字段、未知 operation 或未知 consumer adapter fail closed。

每个非 null consumer slot 必须解析到不可变 `ConsumerAdapterRevision`，其中至少钉住：

- slot kind、adapter contract version、实现 code/release digest；
- 接受的 operation、facet kind、facet schema/version 和 semantic predicates；
- 生成的 Artifact/projection schema 与 validator revision；
- 对 sample/index、estimand、scale、horizon 和 comparability 的要求；
- adapter evidence、admission scope 和 supersede 关系。

`ConsumerAdapterRevision` 只能由受信任代码实现，不执行 bundle 自带 UI/report 代码。没有显式 `downstream_source` 或 `rerun` slot 时，该结果分别不得成为后续分析 source 或历史 rerun 入口；缺任何 source 所需 slot 时服务端强制 `source_eligible=false`，不能从“fit 成功”推断。CF4 统一通过 `ArtifactContractValidation@1.1` 校验实际 payload schema，不能只检查 adapter id 非空。

`ArtifactContractValidation@1.1` 是 custom capability 唯一成功 commit gate。它是内容寻址的不可变 aggregate，必须钉住：

- Option id/revision、authorization/receipt、Run id 与 `ExecutionAttemptRecord`；
- `CapabilityResolutionBinding` 与 Artifact Contract revision；
- 确切且有序的 `ConsumerAdapterRevision` 集合；
- produced Artifact manifest hash（覆盖每个 artifact identity/type/payload hash）；
- 每个 payload/sample/index/scale/estimand sub-validation ref 及其 hash；
- 最终 source/rerun eligibility decisions、outcome 与 validator revision。

validator 逐项验证 sub-validation 的 adapter/attempt/binding/manifest identity，拒绝跨 adapter、跨 attempt 或跨 Run 混配。sub-validation 只是 aggregate 的证据，不可独立把 Option 标成 completed。只有 aggregate `passed` 且其 Option/Run/attempt 与当前执行一致，才允许 Option execution completed、active head 推进和 source eligibility；任一 payload/consumer failure 保留失败 Artifact 事实但不推进。既有 1.0 gate 继续服务旧 Option，不获得 1.1 语义。

### 5.2 不可变实现对象与独立有效性

同一个可解析实现由四类不可变对象组成：

1. `CapabilitySemanticProfileRevision`：能力语义、操作、输入、输出和消费者；
2. `ImplementationBundleRevision`：实现来源、Adapter、代码、依赖、环境和 handler bundle digest；
3. `EvidenceAssessment`：绑定确切 profile/bundle/validation material 后由服务端派生的 E0–E3；
4. `ScopedAdmissionDecision`：绑定前三者、runtime policy、确切使用作用域和当时审查结论的不可变决定。

可变有效性不写回以上对象。服务端分别追加 `EvidenceAssessmentValidityRecord` 与 `AdmissionValidityRecord`；后者具有单调 `validity_revision`、`effective_at`、reason 和 evidence refs，状态只允许：

```text
valid → expired | revoked | superseded
```

被撤销后重新准入必须产生新的 `ScopedAdmissionDecision`，不能把旧 validity 改回 `valid`。Decision 的 outcome 也可为 `rejected`，但 rejected 决定不创建 valid admission validity。

CF2 为每个不可变 bundle 维护 append-only `ImplementationBundleValidityRecord`，包含单调 `validity_revision`、`effective_control_sequence`、authority、reason 和 supply-chain evidence refs：

```text
valid → quarantined | revoked | superseded
```

终态不恢复；重新组装或重新审查产生新 bundle revision。Resolver/runner 必须直接检查 bundle validity，不能等待 project admission 的异步传播。

切片所有权为：CF1 冻结通用 bundle-validity schema/freshness interface，并为 release builtin backfill 初始 valid records；CF2 实现第三方 bundle 的 supply-chain producer、quarantine/revoke/supersede 状态与 runner gate。CF1 可用 release builtin fixture 独立验收，不要求 CF2 已存在；CF2 只消费已冻结接口。

所有会影响执行的 validity/authorization subject（host、bundle、evidence、admission、runtime policy、authorization）都投影为统一 `ControlSubjectCursor`：

```text
subject_kind / subject_ref / validity_revision
status / control_sequence / effective_at / optional expires_at
authority / reason / source_record_ref
```

CF1 交付专用 `ExecutionControlStore` 与 serializable `compare_cursors_and_append(...)` primitive：在一个事务中读取多个 subject 的最新 cursor、比较 expected revisions/status/expiry，并分配单调 control sequence 追加调用方提供的不可变 record。CF1 用 synthetic reservation 测试 revocation-before/after-CAS 的线性化，不实现 Run 或 DispatchReservation。CF4 是唯一真实 dispatch consumer，并用同一 primitive 写 `DispatchReservation`；各领域 validity record 仍保留自己的不可变内容，但其 execution-control projection 必须与 source record 原子/可验证关联。

ResolutionSet 已唯一解析，或用户/注册协议产生 `ImplementationSelectionDecision` 后，服务端生成内容寻址的 `CapabilityResolutionBinding@1.0`，钉住：

- resolution set 与 implementation-selection decision；
- requirement revision；
- resolution policy snapshot；
- semantic profile revision；
- implementation bundle revision；
- 被观察到的 implementation bundle validity revision；
- evidence assessment；
- scoped admission decision 与被观察到的 admission validity revision；
- 每个已声明 consumer slot 的 `ConsumerAdapterRevision`；
- 被观察到的 `HostContainmentAssessment` identity/validity revision；
- resolver/protocol revision；
- 解析时间和 freshness dependencies。

Option、materialization 和 Run 引用 binding，而不是从 Registry 的“当前状态”重新拼接身份。

Resolver、authorization claim 和 sandbox dispatch 使用同一 freshness contract：调用方提交预期的 host/bundle/evidence/admission validity revisions，服务端检查“仍为最新且 valid”。claim 后不得用“检查一次再启动”的非原子序列；CF4 必须在共享 control stream 中原子比较全部 validity cursors 并写 `DispatchReservation`。先提交的撤销阻止 reservation，先提交的 reservation 获得唯一启动权；已越过该序列化点的历史 Run 不被改写，紧急终止由独立运行安全策略处理。

### 5.3 不强制全接口

不要求每个 capability 实现以下全部方法：

```text
fit
predict
diagnose
summarize
render_artifacts
```

能力只实现 profile 声明的 operation slots。`fit` 甚至不应是所有 capability kind 的默认入口。

首版可注册的高层 operation vocabulary 包含 `fit | predict | diagnose | summarize`，但它是可版本化词表；增加新 operation 必须同时定义输入、输出、风险和消费者语义，不能只加入一个字符串。

B0 v1 输入 vocabulary 只接受 `column | columns | scalar`。要求 graph、tensor、sparse matrix、event stream，或 `test | transform | solve` 等未注册 operation 时，Requirement/Resolver 返回类型化 capability gap；不得把输入压平、把 operation 改名或伪造 `fit/predict`。后续扩展必须同时版本化 requirement、B0 input contract、operation vocabulary、dispatcher、evidence protocol 与消费者 schema。

`serialize` 不属于作者 operation：可信运行时负责 envelope 和持久化。

`render_artifacts` 不由不可信代码直接操作 Workbench UI：作者只返回已声明 facet；可信 consumer adapter 将 facet 投影为 Artifact。

### 5.4 B0 作者入口不变

Capability operation dispatch 由可信类型化适配器完成。适配器将选定 operation 及其已校验参数编码进 `capability_spec`，然后继续调用 B0 已冻结的固定作者入口：

```python
def run(input_bundle, capability_spec):
    ...
    return output_bundle
```

不得为 Capability Factory 定义第二个 harness ABI，也不得要求 B0 扩大根契约。作者入口只能接收服务端已绑定、已密封的输入，且只能返回 B0 允许的有界 facets。作者不能：

- 打开用户文件或扫描目录；
- 请求网络或安装依赖；
- 创建可信身份；
- 声明 evidence tier、admission 或 source eligibility；
- 写 Graph、Run、Artifact、Trace 或 memory；
- 调用未声明 operation；
- 让自由 JSON 自动成为 UI 或报告组件。

## 6. 实现来源

### 6.1 原生能力

原生能力继续通过 Workbench 受信任实现运行，并注册 semantic profile。它们也必须显式声明适用条件、操作、输出、消费者和比较协议；“原生”不免除契约。

发布流程为原生实现生成服务端持有的：

- `ImplementationBundleRevision` 或等价 release bundle identity；
- 初始 `ImplementationBundleValidityRecord(valid)`；
- 基于产品测试、数值验收、版本和平台证据的 `EvidenceAssessment`；
- `scope_kind=release_builtin` 的 `ScopedAdmissionDecision` 与初始 `AdmissionValidityRecord`；
- 对应的撤销、supersede 和兼容范围。

既有 Analysis Pack 在进入 Resolver 前必须一次性 backfill 这些记录。Resolver 不得通过 `if native: allow` 之类隐藏豁免绕过 evidence/admission hard filter。

### 6.2 已注册第三方能力

第三方能力只能引用已有的不可变 dependency bundle 和已审查 Adapter。包的新版本、平台变化、锁文件变化、Adapter 修改或 runtime policy 变化都会产生新 bundle/revision，并重新走所需验证。

### 6.3 Agent 生成 Adapter

仅当：

- 依赖已通过 dependency admission；
- 依赖 API 与 requirement 存在可验证映射；
- 运行时能提供所需隔离；
- 用户批准生成和验证作者代码；

Agent 才能生成 Adapter 候选。

Adapter 验证必须覆盖输入角色、缺失值、类别编码、权重/组/时间等声明语义、输出映射、异常传播、随机性、序列索引和 Artifact facets。几行“调用库函数”的代码不构成适配完成。

### 6.4 Agent 自研算法

自研算法是最后一级。进入前必须记录：

- 为什么原生、已注册第三方和可适配依赖都不能满足需求；
- 数学或算法定义；
- 统计假设与适用范围；
- 数值方法、终止条件和失败判定；
- 验证计划与独立性来源；
- 预期性能和资源上限；
- 不能验证的部分。

Agent 生成代码后只得到候选 bundle。它不能因自测通过而进入正常推荐列表。

## 7. 依赖构建与运行隔离

### 7.1 三平面供应链流程

不可信代码在任何阶段都不能同时拥有网络。依赖流拆成三个隔离平面：

#### A. 联网解析与获取

```text
dependency proposal
→ deterministic resolution
→ user approves exact lock manifest
→ fetch artifacts to quarantine
→ hash / provenance / license / vulnerability checks
```

该平面不执行第三方模块、Adapter、作者 hook、安装脚本或算法代码，不接收用户数据、凭证、项目路径或可写宿主目录。它只产生内容寻址的下载对象和审计材料。

#### B. 断网 quarantine 安装与组装

只接收 A 平面已校验的 CAS 对象，在断网、低权限、无用户数据环境中组装只读 dependency tree，生成安装 manifest、SBOM 和 bundle candidate。首版默认只接受固定版本、固定索引、完整传递哈希且平台匹配的 wheel；VCS、任意 URL、本地路径、未固定版本和源码构建均拒绝。

wheel admission 必须把 index project、PEP 503 规范名、filename、METADATA、RECORD、版本和 compatibility tag 交叉校验并纳入审计。拒绝规范名碰撞、同一 distribution 重复/遮蔽、路径穿越、绝对路径、symlink/hardlink、`.pth`、site hooks、安装脚本及未声明文件。解包必须 no-follow、有文件数/尺寸/压缩比上限；组装后从磁盘重新计算 installation-tree manifest，不信任下载阶段的文件列表。任何 resolver、lock、wheel、平台、安装树或策略漂移都产生新 revision，并重新取得对应批准。

#### C. 断网 Adapter / 算法验证

使用 `untrusted_capability_v1` 或更严格 profile，在密封 fixtures、holdout 和资源预算下执行 Adapter 与作者代码测试。该平面不继承 A/B 的网络、凭证、临时目录或可写状态；只接收不可变 bundle candidate 和验证输入，成功后产生 evidence packet 与 immutable CAS bundle revision。

三个平面之间只传内容寻址对象和有界 manifest。任何身份、哈希、平台或 policy 不一致都重新开始对应阶段，不能把可联网工作目录直接带入验证或正式运行。

许可证或漏洞检查是准入输入，不是“检查过就安全”的证明。策略必须能阻止、要求例外批准或在以后撤销。

### 7.2 分析运行平面

正式分析运行：

- 无网络；
- 只读挂载不可变解释器、依赖、harness 和 input bundle；
- 私有、有界 output；
- 无宿主目录、仓库、home、凭证或其他项目可见性；
- 固定环境变量、线程、RNG 和 runtime policy；
- 进程树级 CPU、内存、PID、墙钟和输出上限；
- 运行前后校验 bundle identity。
- 运行前重验 `HostContainmentAssessment` 的 OS/kernel/backend/profile/mount-policy identity 与 validity。

运行环境不能提供声明保证时 fail closed，不能回退到 Workbench 主环境。

## 8. 验证与证据

### 8.1 验证套件

根据 capability profile 组合：

- 契约和 schema 测试；
- 合成数据已知真值或参数回收；
- 边界条件、异常输入和退化情形；
- 与可信独立实现或 oracle 对照；
- invariant、property 和 metamorphic tests；
- 数值稳定性与条件数敏感性；
- 随机种子、重复执行和 statistical profile；
- 小样本、大样本、极端参数与资源上限；
- 输出 facet、Artifact Contract 和消费者适配；
- 性能、内存、超时与失败清理；
- 隔离、网络、文件、子进程和输出 canary。

并非每项适合每种能力；profile 必须解释选择和遗漏，遗漏不能被“通过”状态掩盖。

### 8.2 证据等级

沿用 B0 的服务端派生语义：

| `evidence_tier` | 含义 | 用户可见标签 |
|---|---|---|
| E0 | 契约与隔离边界通过 | 实验性 |
| E1 | 作者自测通过 | 实验性 |
| E2 | 独立 oracle / 实现或充分独立证据通过 | 已验证候选 |
| E3 | 多案例、对抗、性质、模拟校准及独立复核通过 | 可提交更宽准入审查 |

不能把用户名、审批按钮、运行次数或记忆命中写进 evidence tier 派生。

E2/E3 还要求服务端验证 evidence provenance DAG。共享作者、代码生成会话、源码、expected 来源、关键依赖或隐藏 fixture 的材料不能冒充独立 oracle。最终 holdout 隔离、轮换、限制尝试次数并只返回粗粒度反馈；泄漏或自适应探测会追加 invalid validity record。

statistical profile 的 seed/stream 生成、最小重复数、区间/MCSE、coverage/power、最大误接受率、允许失败率和 tolerance ceiling 由注册的服务端 protocol revision 固定。作者不能提供更宽松阈值；缺失协议或样本不足不得得到通过 assessment。

验证开始前，服务端根据 semantic profile、claim kind、算法谱系和风险级别选择并冻结 protocol eligibility/mapping；作者不能通过改写 profile 文案在多个 protocol 中挑最容易通过者。服务端维护跨 `ImplementationBundleRevision` 的 `ValidationAttemptLedger`，identity 至少覆盖作者/生成会话谱系、semantic claim family、算法/源码 lineage、protocol family 与 holdout family。注释、包装、bundle hash 或非语义 manifest 变化不能重置尝试预算。

重复提交使用预注册的 multiplicity/alpha-spending 或等价 family-wise false-accept 控制；预算耗尽、protocol shopping、未声明内部 seed search、忽略服务端 seed/stream 或通过反馈自适应修改候选，均使本轮失败并可使相关 assessment validity 失效。更换 semantic claim 或算法谱系必须由服务端审查其是否真是新 family，不能由作者自报。

### 8.3 Evidence validity 与负面传播

`EvidenceAssessment` 内容不可变；服务端用 append-only `EvidenceAssessmentValidityRecord` 表达：

```text
valid → superseded | invalid
```

每条 validity record 绑定 assessment、规则版本、生效时间、原因和证据引用。证据撤回、独立性失效、验证规则废止、blocking regression 或 bundle identity 问题必须产生 `invalid` 或 `superseded` 记录。

负面传播 fail closed，但 producer 与 consumer 的验收边界分开：

1. Resolver 和执行前 freshness gate 直接读取最新 validity record，不能因旧 E2/E3 assessment 仍存在而放行；
2. 服务端追加新的 `AdmissionValidityRecord(expired|revoked|superseded)`，不修改 admission decision；
3. 引用该 assessment/admission 的 `CapabilityResolutionBinding` freshness 校验失败；
4. CF1 只需证明 binding/freshness API 对旧 revision fail closed；
5. CF4 才负责证明已生成 Option 变 stale、已 materialize Draft 在 execute gate 被拒绝且不创建新 Run；
6. 历史 Run 继续引用当时 assessment、admission decision 与 validity snapshot，不改写历史结果。

即使 admission 状态传播暂时未完成，Resolver/execute 对 assessment validity 的直接检查也必须阻止新运行。

## 9. 准入状态与作用域

admission decision、admission validity 与 `evidence_tier` 分开：

```text
review → ScopedAdmissionDecision(outcome=admitted|rejected)
admitted decision + AdmissionValidityRecord(valid)
valid → expired | revoked | superseded
```

每个不可变 `ScopedAdmissionDecision` 绑定：

- capability revision；
- handler bundle digest；
- evidence packet；
- runtime policy；
- 允许的 project / RunFamily / organization / release scope；
- 允许的 operation 和 consumer capabilities；
- 风险策略；
- 批准人、时间和理由；
- 过期、复查和撤销条件；
- decision content hash 和 decision revision。

“approved”是用户界面的审查结果，不是证据等级。一个 E1 能力即使被允许做受控实验，也必须显示“实验性”，不能伪装成“已验证”。普通推荐列表默认只包含满足该分析所需 evidence floor 且当前已准入的能力。

每条 `AdmissionValidityRecord` 绑定 decision id、单调 revision、状态、生效时间、原因、authority 与 evidence refs。状态不能从 invalid terminal 恢复；重新允许使用必须新建 decision。历史 Run 保留当时 decision/validity snapshot 和 bundle identity。撤销阻止新执行，不改写历史事实。

Admission 是按作用域独立的决定和有效性流。同一 bundle 可以同时在一个项目中具有有效 admitted decision、在另一个作用域中具有 rejected decision，并保留已 expired 的历史 validity；不存在覆盖所有作用域的单一“当前准入状态”。

## 10. Notebook 与全流程自动执行

### 10.1 复用现有 Option 契约

Factory 不新建推荐系统。Agent 读取有界 Notebook context 和 Data Evidence Pack，提出最多三个 typed AnalysisOptions：

- 最多一个 evidence-gated recommended；
- 至多两个 alternatives；
- 允许 `tied` 或 `insufficient_evidence`，此时没有首推；
- 未选方案保留为 deferred；
- 未确认前不创建 Graph branch。

自定义 capability 方案通过正式的 `NotebookOptionRevision@1.2` 扩展接入，不向严格的 1.1 键集静默加字段。1.2 增加：

- `capability_resolution_binding_ref`：指向不可变 `CapabilityResolutionBinding@1.0`；
- `execution_modes`：`materialize_only`，以及满足下节条件时的 `confirm_and_execute`；
- 既有 recommendation、expected Artifact、source context 与 freshness 字段保持原语义。

旧 1.0/1.1 Option 继续按既有规则读取；需要使用 Capability Factory 时必须针对当前 context 重新验证并写出 1.2 revision，不能就地升级。Materialization、execution authorization、Draft、Run 和 Trace 都钉住确切 binding revision。未知 1.2 字段或未知版本继续拒绝。

### 10.2 “2 > 1”的产品语义

首推必须满足以下之一：

1. 注册且版本化的 deterministic feasibility/inspection protocol 以服务端证据阻塞所有其他候选，使其成为唯一可行候选；
2. 同一可比 cohort 的注册协议证明其在声明维度上超过阈值，并覆盖所有可行备选。

Option 1.2 新增服务端持有的 `FeasibilityDecision@1.0`。它绑定完整 candidate cohort、每个候选的 protocol revision、inspection/evidence refs、通过或阻塞结果、reason code、validator revision 和 context fingerprint。Agent 只能提议候选与检查，不能提交受信任 `blocked_reason`；服务端没有覆盖完整 cohort 的 FeasibilityDecision 时，不能以“其他候选被阻塞”为由产生唯一推荐。

Option 1.2 必须使用严格的 `RecommendationDecision@1.1` successor；现有 1.0 wire contract 不加字段。1.1 钉住 candidate cohort hash，并要求以下两个 typed refs 恰好一个非空：

- `feasibility_decision_ref`：指向覆盖完整 cohort 的 `FeasibilityDecision@1.0`；
- `comparison_decision_ref`：指向覆盖完整可比 cohort 的注册比较结果。

validator 重新计算 cohort hash，并验证 referenced decision 的 protocol/context/evidence hash 与 Option batch 一致。不得把 Feasibility id 塞进自由 `reason_refs` 或 `comparison_protocol_refs` 冒充 typed decision；未知字段继续 exact-key 拒绝。如果只是 Agent 偏好、领域惯例、一个不可解释总分、指标不可比或差异落在 tie margin 内，系统不得显示唯一首推。

现有 NotebookOption 1.0/1.1 路径与 `RecommendationDecision@1.0` validator 行为保持在其版本边界内，不把 Agent 提供的 `blocked_reason` 解释为 Option 1.2 的服务端 feasibility 事实。Option 1.2 使用 `RecommendationDecision@1.1` 独立 validator 分支并拒绝旧字段冒充新 decision。

### 10.3 确认并运行

既有 Notebook 契约的默认行为保持不变：

```text
select / confirm
→ OptionMaterialization
→ materialized Draft
→ 用户另行明确 execute
```

v1.8.3 为用户要求的自动全流程新增显式决议：

```text
DEC-CF-NB-001 — Confirm And Execute
NotebookOptionRevision@1.2 MAY offer confirm_and_execute only for an
already admitted, low-risk, fresh CapabilityResolutionBinding.
One user confirmation MAY authorize deterministic materialization and
one exact Draft execution. The server MUST still create and validate the
Draft, execute through the existing Run path, validate the Artifact
Contract, and record every transition in Core Trace.
This is a versioned extension of the earlier materialize-only contract,
not an interpretation of its old confirmation semantics.
```

该组合动作使用 `OptionExecutionAuthorization@1.0`，在确认界面向用户展示并钉住：

- Option 与 binding revision；
- 预计算的 deterministic Draft hash；
- capability、bundle、evidence、admission 和 runtime policy；
- 数据/Graph/freshness fingerprint；
- operation、资源上限、风险与 expected Artifacts；
- 单次消费的 authorization id 和 idempotency key。

授权 receipt 使用以下合法转换；表外转换全部拒绝：

| From | To | 含义 |
|---|---|---|
| `issued` | `rejected` | claim 前 payload/expiry/revocation/freshness 拒绝；终态 |
| `issued` | `claimed` | journal 与预分配 ids 已原子持久化 |
| `claimed` | `invalidated` | dispatch reservation 前失效；终态 |
| `claimed` | `failed` | materialization/验证确定性失败，或有界重试预算耗尽；终态 |
| `claimed` | `dispatch_reserved` | 在同一序列化控制点取得唯一 dispatch 权 |
| `dispatch_reserved` | `running` | durable executor 已确认唯一 process handle |
| `dispatch_reserved` | `failed` | supervisor 证明未 spawn 且启动确定性失败/重试预算耗尽；终态 |
| `dispatch_reserved` | `dispatch_unknown` | 无法证明是否已 spawn；隔离终态，不自动重试 |
| `running` | `dispatch_unknown` | 已确认 handle 后丢失 supervisor 状态，无法证明进程是否仍在运行；隔离终态 |
| `running` | `failed` | 有进程终止证明，且执行/结果验证/兼容 reconciler 明确失败；终态 |
| `running` | `consumed` | 所有副作用对账完成；终态 |

receipt 在任何外部 materialization 前持久化 authorization expiry/revocation identity、payload hash，以及服务端预分配的 materialization id、Draft id、run id/intent、artifact namespace、Graph-edge namespace 和 Trace-event namespace。receipt 同时钉住 namespace-derivation contract revision、Artifact/Graph/Trace producer revisions 与 canonical slot-mapping revision。动态副作用数量可以由有界输出决定，不要求提前猜数量；服务端先完成 facet/output-id/slot 的 exact schema、唯一性与 bounds 校验，再从规范化 identity 派生 stable key。其身份由 `(namespace, derivation revision, producer revision, slot-mapping revision, canonical stable key)` 确定性派生并受唯一约束；作者原始字符串、路径或未验证顺序不能直接成为持久化 id。`issued → claimed` 通过 compare-and-swap 或等价事务原子完成，并比较最新 binding/host/bundle/evidence/admission validity revisions；同一 authorization/idempotency key 的并发 claim 只能一个成功。expiry、revocation、payload 或 freshness 在 claim 前失败进入 `rejected`，不创建 materialization/Draft/Run。

`claimed` 带 lease owner、单调 lease epoch 与 deadline。确定性 reconciler 只能续租当前 epoch，或在 lease 过期后以新 epoch 接管同一 journal；它使用 caller-supplied ids/namespaces 对每个 side effect 执行 get-or-create，并验证已存在对象的 canonical hash。现有 materialization/Draft/Run API 若随机生成身份，CF4 必须先增加 caller-supplied id/idempotency contract，不能在 receipt 外先写对象。

Run 接缝严格拆成：

```text
prepare: valid Draft → content-addressed PreparedRunIntent（不创建 Run 目录或 Run 事实）
reserve: 原子 freshness/expiry fence → DispatchReservation
spawn: 用 caller-supplied run_id get-or-create Run，再交 durable supervisor
```

`PreparedRunIntent` 钉住 Draft、binding、run id、input hash、runtime policy、动态副作用 namespaces、derivation contract、producer revisions 与 slot-mapping revision。恢复只能加载这些确切 revision；当前部署版本不同不得用新规则重新派生 identity。若 supervisor 证明进程已终止但兼容 reconciler 不可用，receipt 进入有界失败并隔离部分输出；进程状态未知则 `running → dispatch_unknown`。现有 `create_run` 在 dispatch 前随机建目录的行为必须先重构；reservation 失败时不得留下成功 Run/Run directory。materialized Draft 是可见的非执行事实，可以在 reservation 前存在。

撤销与 dispatch 共享一个序列化 control stream。runner 不能先读 validity 再单独写时间戳；它必须在单个 serializable transaction/CAS 中：

1. 比较 authorization、host containment、bundle、evidence、admission 与 binding 的最新 validity cursors；
2. 使用可信事务时间直接比较 authorization 和所有 policy/validity 的 `expires_at`，不能依赖异步 expiry job；已到期时在同一事务追加 expiry/invalidation 并拒绝 reservation；
3. 比较 receipt lease epoch 与 canonical Draft hash；
4. 分配单调 `control_sequence` 并写不可变 `DispatchReservation`；
5. 将 receipt 推进到 `dispatch_reserved`。

revocation/expiry validity record 也在同一 control stream 分配 sequence。revocation 先提交则 reservation 失败并进入 `invalidated`；reservation 先提交则该 attempt 获得启动权，后续撤销不改写历史，但可由独立 emergency-termination policy 处理。这里的线性化依据是 control sequence，不是不可原子比较的 wall-clock `dispatch_started_at`。

对象幂等不等于进程 exactly-once。`DispatchReservation` 创建唯一 `ExecutionAttemptRecord(attempt_id, lease_epoch, executor_idempotency_key)`；只有受信任 durable executor/supervisor 能消费它。supervisor 必须对同一 key 返回同一持久化 process/job handle，并以 epoch fence 拒绝旧 worker 的 spawn、ack 和输出。若 worker 在 spawn/ack 边界崩溃，reconciler 只能查询同一 supervisor handle，不能重新调用新 spawn；如果 supervisor 无法证明“未启动”或恢复原 handle，receipt 进入 `dispatch_unknown`。

`dispatch_unknown` 会隔离 attempt、host containment subject 和对应 holdout/validation budget。新授权不能绕过隔离；只有受信任 supervisor 提供 `AttemptQuiescenceProof`（证明未 spawn，或已终止整个进程树并完成资源/输出清理 canary）后，才能解除隔离并由用户重新授权。无法立即证明时必须等待进程树硬截止时间并执行受信任清理；截止后仍无 quiescence proof，则撤销该 host containment validity，禁止在该宿主继续 dispatch。

dispatch 后执行失败进入 `failed`；成功且所有 Artifact/Graph/Trace side effects 已对账后才进入 `consumed`。所有输出与 side effect 都绑定 attempt id/epoch，旧 epoch 写入拒绝。

重放与崩溃恢复：

- 相同 idempotency key + 相同 payload hash 返回同一 in-progress 或 final receipt；
- 相同 key + 不同 payload 拒绝为 replay mismatch；
- worker 崩溃后从 claimed journal 和预分配 ids 恢复，不重新生成身份或创建第二个对象；
- materialization、Draft、Run 使用 caller-supplied ids；Artifact、Graph edge 与 Trace event 从预分配 namespace + stable key 确定性派生并去重；
- 在 claim、reservation、spawn 前后、supervisor ack 前后、输出与每个对象持久化边界注入崩溃后，reconciler 都只能恢复同一 attempt/handle 或进入 `dispatch_unknown`，不得启动第二个进程；
- `rejected`、`invalidated`、`dispatch_unknown`、`consumed` 和 `failed` 都是该授权的终态，不自动重新执行；
- transient infrastructure error 只能在同一 receipt/lease 的服务端有界预算内重试；确定性 materialization/validation 失败或预算耗尽进入 `failed`；
- `failed` 后若用户要再运行，必须创建新的 Draft execute 授权。

执行语义：

1. claim 前 binding stale、admission 失效、authorization 过期/撤销或预计算 Draft hash 不一致时，receipt 进入 `rejected` 且不执行；
2. materialization 失败时不创建 Run；
3. claim 后、reservation 前 freshness 变化进入 `invalidated`；Draft 验证通过后只能由该 receipt 的唯一 DispatchReservation/ExecutionAttempt 执行，启动状态不明进入 `dispatch_unknown`；
4. Run 或 Artifact Contract 失败时保留 materialized Draft 和失败事实，不推进 active head；
5. 再次执行必须由用户对该 Draft 发起新的明确 execute；
6. 用户选择 `materialize_only` 时完全沿用既有两段式流程，可先编辑 Draft。

因此“一次确认”只合并两个用户交互，不合并或绕过内部状态、验证和审计 gates。

dependency 下载、lock manifest 批准、作者代码验证、capability admission 和 promotion 仍需独立高风险确认，不能隐藏在“确认并运行”里。

## 11. Workflow 接入

Capability Factory 不允许自由代码进入 `operation.multi_step`。

后续只有满足以下条件的稳定 operation 才能加入 `WORKFLOW_STEP_SPEC_CONTRACTS`：

- capability 已准入；
- step 有版本化 schema；
- 输入只含服务端可验证引用和参数；
- output/Artifact Contract 已注册；
- 风险和确认语义已定义；
- dispatcher 只解析不可变 bundle identity；
- Agent 协议词表由同一 contract 生成。

当前产品中的 contract table 尚未持有全部 semantic validation 与 dispatch，仍存在 validator 硬编码分支，因此不能直接宣称“增加 step 只改一处”。CF4 必须先泛化 `StepSpecContract`，使每条记录同时拥有：

- required/optional 字段、字段类型、exact-key schema；
- semantic validator、引用解析器、列/角色提取器；
- 风险分类、确认策略、output schema；
- 受信任 dispatcher 与 Agent protocol projection。

迁移完成后，原有 operation 的行为必须保持回归一致，且 required 字段由通用 validator 真正执行。contract table 成为唯一**注册与协议投影入口**：增加全新 operation 仍需实现受信任的 schema/semantic validator、引用/列提取器和 dispatcher，但这些实现只能通过一条 contract record 的稳定 implementation keys 接入；错误消息、Agent 词表、风险和 runtime 由该记录统一投影。禁止第二张 OperationDefinition 注册表、runtime `if operation_id` 分派或为 `model.custom` 增加表外旁路。迁移测试必须使用任意 step id 与不同 DAG 顺序，证明 lineage/threshold source 不含固定 `step-4` 等位置假设。代码、依赖请求、准入与 promotion 永不成为普通 step payload。

## 12. 生命周期与 Trace

### 12.1 三条正交状态轴

#### Implementation build lifecycle

```text
proposed → fetch_pending → assembled → validation_ready
proposed | fetch_pending | assembled | validation_ready → superseded | retired
```

构建失败是当前 attempt 的失败事件；修复产生新的 `ImplementationBundleRevision`，不把失败 revision 改成成功。

#### Evidence assessment revisions

`EvidenceAssessment` 是对确切 semantic profile、bundle、验证材料和规则版本的 append-only 判断，不是 bundle 生命周期状态。新的独立证据可产生 E2/E3 assessment；证据撤回或规则变化也可产生更低或 invalid assessment。旧 assessment 仍保留供历史 Run 解释。

#### Scoped admission lifecycle

```text
review → immutable decision(admitted | rejected)
admitted decision → validity(valid)
valid → expired | revoked | superseded
```

每个作用域独立。新的 scope、bundle、assessment、runtime policy 或复审结果产生新的 decision；有效性变化只追加 validity record，不修改 decision 或其他作用域。

### 12.2 必须追踪的事实

Core Trace 至少引用：

- requirement 与 revisions；
- context/evidence hashes；
- resolver 过滤理由和候选 cohort；
- resolution policy snapshot 与 effective limits；
- dependency proposal、批准和 lock digest；
- 代码、Adapter、bundle、环境和 runtime policy digest；
- validation plan、执行、omission 和 evidence tier 派生；
- admission、作用域、批准、过期与撤销；
- Notebook Option、RecommendationDecision 和用户选择；
- CapabilityResolutionBinding、OptionExecutionAuthorization 和单次消费结果；
- Draft、Run、Artifact Contract 和 consumer projection；
- 所有失败的稳定错误码。

Trace 不复制原始项目数据、完整依赖文件或无限日志；大对象使用内容寻址引用和保留策略。

### 12.3 Versioned Trace event catalog

现有 Core Trace 对未知 event type 和额外字段 fail closed，因此任何 CF 切片写 Trace 前必须冻结 event catalog 与 exact payload schema。v1 catalog 的稳定事件名和最小 payload refs 为：

| Owner | Event type | Required payload refs |
|---|---|---|
| CF1 | `capability.requirement.registered` | `requirement_ref`, `requirement_hash` |
| CF1 | `capability.resolution.completed` | `resolution_set_ref`, `outcome`, `policy_snapshot_ref` |
| CF1 | `capability.selection.recorded` | `selection_decision_ref`, `resolution_set_ref` |
| CF1 | `capability.binding.created` | `binding_ref`, `resolution_set_ref`, `validity_snapshot_ref` |
| CF1 | `capability.validity.checked` | `binding_ref`, `expected_revision`, `observed_revision`, `outcome` |
| CF1 | `capability.admission.decided` | `decision_ref`, `scope_ref`, `outcome` |
| CF1 | `capability.admission.validity.changed` | `decision_ref`, `validity_ref`, `to_status` |
| CF1 | `host_containment.assessed` | `subject_ref`, `assessment_ref`, `outcome` |
| CF1 | `host_containment.validity.changed` | `assessment_ref`, `validity_ref`, `to_status` |
| CF2 | `dependency.lock.reviewed` | `lock_ref`, `decision_ref`, `outcome` |
| CF2 | `capability.bundle.assembled` | `bundle_ref`, `install_manifest_ref`, `outcome` |
| CF2 | `capability.bundle.validity.changed` | `bundle_ref`, `validity_ref`, `to_status` |
| CF3 | `capability.validation.completed` | `validation_run_ref`, `plan_ref`, `outcome` |
| CF3 | `capability.evidence.assessed` | `assessment_ref`, `tier`, `protocol_ref` |
| CF3 | `capability.evidence.validity.changed` | `assessment_ref`, `validity_ref`, `to_status` |
| CF3 | `capability.validation_attempt.recorded` | `attempt_ledger_ref`, `protocol_ref`, `outcome` |
| CF4 | `option.feasibility.decided` | `decision_ref`, `candidate_cohort_ref`, `outcome` |
| CF4 | `option.authorization.changed` | `authorization_ref`, `from_status`, `to_status`, `receipt_ref` |
| CF4 | `option.dispatch.reserved` | `authorization_ref`, `reservation_ref`, `control_sequence` |
| CF4 | `capability.consumer_projection.validated` | `adapter_revision_ref`, `projection_ref`, `outcome` |
| CF4 | `artifact_contract.v11.validation.completed` | `aggregate_ref`, `option_revision_ref`, `run_attempt_ref`, `outcome` |
| CF4 | `option.execution.reconciled` | `authorization_ref`, `lease_epoch`, `outcome`, `object_graph_ref` |

每个事件的 `payload_schema` 使用对应的 kebab-case `/v1` 标识；表中 refs 是 required exact keys，只有在实现计划明确列出的 bounded optional keys 才可扩展。大对象只能用 content-addressed ref，不进入 payload。

每条 event schema 必须声明 bounded fields、content refs、redaction projection、replay/idempotency key 和允许 producer。各切片只新增自己拥有的 event schemas，并测试未知字段、未知版本、重复 replay、超限与敏感字段拒绝；不得把自由 capability/memory dict 塞进通用 telemetry。若选择统一 Trace v2 作为前置切片，则它必须先独立验收，后续计划不得暗中依赖未实现 schema。

## 13. 失败语义

首版稳定错误类别：

- `CAPABILITY_REQUIREMENT_INVALID`
- `CAPABILITY_INPUT_KIND_UNSUPPORTED`
- `CAPABILITY_NO_FEASIBLE_IMPLEMENTATION`
- `CAPABILITY_IMPLEMENTATIONS_INCOMPARABLE`
- `CAPABILITY_DEPENDENCY_NOT_ADMITTED`
- `CAPABILITY_BUILD_FAILED`
- `CAPABILITY_ADAPTER_CONTRACT_INVALID`
- `CAPABILITY_VALIDATION_FAILED`
- `CAPABILITY_VALIDATION_ATTEMPT_BUDGET_EXHAUSTED`
- `CAPABILITY_VALIDATION_PROTOCOL_INELIGIBLE`
- `CAPABILITY_EVIDENCE_INSUFFICIENT`
- `CAPABILITY_NOT_ADMITTED`
- `CAPABILITY_ADMISSION_SCOPE_MISMATCH`
- `CAPABILITY_ADMISSION_REVOKED`
- `CAPABILITY_OPERATION_UNSUPPORTED`
- `CAPABILITY_CONSUMER_UNSUPPORTED`
- `CAPABILITY_CONSUMER_PROJECTION_INVALID`
- `CAPABILITY_BUNDLE_IDENTITY_MISMATCH`
- `CAPABILITY_RUNTIME_POLICY_UNAVAILABLE`
- `CAPABILITY_OPTION_EXECUTION_REPLAY_MISMATCH`
- `CAPABILITY_OPTION_EXECUTION_REJECTED`
- `CAPABILITY_OPTION_EXECUTION_INVALIDATED`
- `CAPABILITY_OPTION_DISPATCH_CONFLICT`
- `CAPABILITY_OPTION_DISPATCH_UNKNOWN`
- `CAPABILITY_OPTION_EXECUTION_RECEIPT_INVALID`

失败不写成功 Run、Artifact、Graph edge、admission 或领域记忆。错误详情必须有界、去敏并保留可定位证据。

## 14. 反过拟合审查清单

实现评审必须逐项回答：

- 根契约是否出现某个数据集列名、作业术语、固定年份或单一软件输出格式？
- 新能力能否只声明自己真正拥有的 operation，而不伪造全接口？
- 非参数、随机、多输出、集合识别或纯诊断能力能否表达？
- 样本、尺度、estimand 或 horizon 不兼容时，Compare 是否拒绝？
- 同名包、同名函数或同名指标是否被误当作相同能力？
- Agent 自测是否可能伪装成独立证据？
- 用户批准是否可能错误提升 evidence tier？
- 记忆是否可能绕过 feasibility、validation 或 admission？
- 运行时是否可能访问主环境、网络、宿主路径或未声明数据？
- 单一“成功样例”是否被当作设计完成？

任一答案不清楚，都不能进入实现验收。

## 15. 分阶段验收

### CF1

- Requirement/profile schema 能表达多个互不等价 capability kind；
- `column | columns | scalar` 外的输入与未注册 operation 产生 typed gap，不压平或伪装；
- server-owned policy snapshot 以最严格交集派生风险、来源和 evidence floor；
- semantic profile、bundle/validity、host assessment/validity、evidence assessment/validity、scoped admission decision/validity 与 resolution binding 身份分离；
- 原生能力通过 release evidence/admission backfill 接入，不存在 resolver 豁免；
- 固定优先级、hard filter、ResolutionSet、同级实现选择和 gap 语义有正反测试；
- 统一 `ControlSubjectCursor` 覆盖 host/bundle/evidence/admission/runtime-policy/authorization；
- `ExecutionControlStore.compare_cursors_and_append` 用 synthetic record 证明 stale cursor、expiry 与 revocation/CAS 全交错线性化；
- evidence、admission、consumer support 三者不可互相伪造。

CF1 不以 Option、Draft、Run 或真实 DispatchReservation 验收；CF4 是唯一真实 dispatch consumer，并负责证明这些 cursor 会阻止启动。

### CF2

- 主环境零安装；
- lock、hash、platform、transitive dependencies、SBOM 和政策结果进入 bundle identity；
- wheel/index/METADATA/RECORD 身份一致，恶意路径、link、`.pth`、site hook、重复 distribution 和解包炸弹 fail closed；
- no-follow 有界组装后重算 installation-tree manifest；lock 或安装树漂移需要新 revision 与重新批准；
- 只有不执行不可信代码的 fetch 平面有网络，组装、验证和正式运行均无网络；
- `ImplementationBundleValidityRecord` 的 quarantine/revoke/supersede 直接使 bundle admission/runner gate fail closed，不等待 scoped admission 传播。

CF2 不以 Option stale 或 Draft execute 拒绝验收；真实消费者传播归 CF4。

### CF3

- Adapter 只映射 profile 声明的 operation；
- 作者代码不能写可信 envelope 或宿主状态；
- 自研算法没有独立证据时最多 E1；
- evidence provenance DAG、隔离 holdout 与 server-owned statistical protocol 阻止自证循环和作者放宽阈值；
- protocol eligibility 在验证前冻结，跨 bundle/claim lineage attempt ledger 与 multiplicity budget 阻止 protocol shopping、seed search 和重复试验误通过；
- 验证 failure、timeout、资源超限和不适用有明确结果。

### CF4

- `NotebookOptionRevision@1.2` 引用确切 `CapabilityResolutionBinding`；
- 推荐只来自完整 cohort 的服务端 `FeasibilityDecision` 或注册比较协议；1.1 Agent blocked_reason 不可冒充 1.2 事实；
- deferred Option 可保留、revalidate 和以后 materialize；
- `ConsumerAdapterRevision` 与 payload schema 验证控制 report/diagnostic/figure/compare/downstream-source/rerun，不支持的 slot 显式拒绝；
- `ArtifactContractValidation@1.1` 是 Option completion/active-head/source eligibility 的唯一 aggregate commit gate；
- CF1/CF2 validity 变化会使 Option stale、Draft execute 被拒绝且不创建新 Run；
- `OptionExecutionAuthorization` 的一次“确认并运行”仍完整经过 Draft/Run/Artifact gates，失败后不自动重试；
- 并发 claim、expiry/revocation、相同 key 重放、不同 payload 重放、lease/epoch 接管、原子 dispatch reservation 与 revocation 全交错均有负面测试；
- durable supervisor 对 executor idempotency key 返回同一 handle；spawn/ack 状态不明进入 `dispatch_unknown`，每个边界崩溃都不能启动第二个进程；
- Run 遵循 prepare/reserve/spawn，reservation 前不创建 Run；动态 Artifact/Graph/Trace 身份由预分配 namespace + stable key 派生；
- `WORKFLOW_STEP_SPEC_CONTRACTS` 是唯一注册/协议投影入口并引用受信任 schema/semantic/ref/risk/output/dispatcher；任意 step id/顺序 lineage 无固定位置假设；
- 高风险 dependency/code/admission 行为不能被普通 workflow 组合绕过。
