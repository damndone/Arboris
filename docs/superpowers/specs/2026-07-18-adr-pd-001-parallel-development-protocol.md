---
adr: ADR-PD-001
title: Workbench Parallel Development Protocol
status: accepted
effective_release: v1.7.3
baseline:
  branch: origin/main
  release: v1.7.2
  commit: 4b2e6c1d9ddd289005b84c186255fec2e9cbd86a
---

# ADR-PD-001：Workbench 并行开发协议

## 决策

自 v1.7.3 起，Econometrics Workbench 采用：

> **3 条 Feature Lane + 1 条独立 Evaluation Lane，由 Contract-first Integration Release Train 协调。**

三条功能 Lane 分别为 Agent、Model Pack 和 UI/UX。它们从同一个冻结的合同基线独立开发，只通过版本化的、带语义约束的 packet 协作。Evaluation/QA 是独立验证角色，不实现被测功能；Integration Release Train 是发布治理机制，不是第四条功能开发线。

`v1.7.3` 是未来经过验证后才会出现的发布快照，而不是任何功能分支的名字。功能分支不得直接合入 `main`。

本 ADR 是工程执行约束，不是单次项目管理建议。所有新的并行工作包都必须遵守它；已存在的工作不能以“并行”名义绕开既有安全、确认、lineage 或统计语义边界。

## 1. 问题与目标

Workbench 当前已具备安全的受控执行基础：typed proposal、校验、用户确认、claim/lease、effect binding、domain commit、terminalization 与 reconcile。v1.7.2 还完成了 OLS Analysis Loop 的首个闭环：

```text
inspect → diagnose → PlanDiff → confirm → child rerun
→ ValidationPacket → ComparePacket → explain
```

但产品仍需要同时推进三类相互依赖的能力：更完整的分析模型、更有用但受限的 Agent、以及能让用户看懂并控制流程的 UI。顺序式地以“一个版本只做一条功能线”的方式开发，吞吐量不足；直接让多个 AI 在同一工作树或同一批中心文件中修改，则会带来合同漂移、冲突修复改变统计语义、测试与实现互相迁就、以及发布证据失真的风险。

本协议的目标是让并行开发本身具有 Workbench 所要求的性质：

- 合同明确，生产者和消费者可以独立工作；
- 每项修改可追踪，来源、基线、责任边界和验收命令清楚；
- 失败可恢复，不把卡住的分支、worktree 或审查调用变成停工理由；
- 结果可独立验证，功能作者不能靠修改 golden、容差或 gate 宣布自己通过；
- 最终集成仍保持统计正确性、安全确认和不可变 lineage 的边界。

## 2. 已核实的 v1.7.2 基线

本协议以 `origin/main` 的 v1.7.2 合并提交 `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a` 为唯一产品基线。它不是重新打开 v1.7.1 或 v1.7.2 发布 worktree 的授权。

基线已有、可复用的部件包括：

- `backend/workbench/agent/**` 中的 typed operation、proposal、生命周期和 orchestration 边界；
- `backend/workbench/analysis_loop/**` 中的 SourceRunContract、PlanDiff、ValidationPacket、ComparePacket、RecoveryAction 与持久化语义；
- `backend/workbench/engine/pack.py`、`registry.py` 和 `capabilities.py` 中的模型 handler 注册与 capability 暴露机制；
- `frontend/src/workbench/agent/**`、lineage detail sections 与 report/figure surfaces；
- v1.7.2 的 deterministic report、figure context、run cancel/timeout、比较及导出基础。

同时，基线也有三个不能忽略的限制：

1. `AnalysisPack` 目前可注册 handler、默认路由、stage 与 rerun action，但会拒绝尚未接线的 `diagnostics`、`recommended_actions`、`report_blocks` 和 `interpretation_restrictions`。因此 Model Pack Lane 不能假装这些扩展点已经可用。
2. `MODEL_REGISTRY` 是中心化 registry，`capabilities.py` 仍包含中心化的 UI metadata/order。若每个模型工作包都直接改这些文件，Integration 会成为新的串行瓶颈。
3. v1.7.2 的 RecoveryActionRegistry 只表达了受限 OLS covariance golden flow。新的模型诊断只能先产生统计上合法的候选动作，不能直接制造可执行的 Agent operation。

因此，首轮并行开发必须先完成 Contract Sprint；任何功能 Lane 都不得绕过它直接扩写中央 registry、orchestrator 或 Graph 存储。

## 3. 术语

| 术语 | 含义 |
| --- | --- |
| **Release snapshot** | 经过完整验证后合入 `main` 并标 tag 的版本；不是开发分支。 |
| **Integration baseline** | Integration Release Train 从 v1.7.2 基线创建、仅承载合同和受控集成的提交线。 |
| **Contract lock** | 某一并行波次唯一允许消费的合同提交，包含版本化 schema、canonical fixture、mock packet 和兼容性测试。 |
| **Release baseline commit** | 已发布 v1.7.2 的不可变产品基线。 |
| **Integration base commit** | `integration/v1.7.3` 创建时的起点提交。 |
| **Branch start commit** | 当前 Lane 实际创建的提交；首轮应等于 Contract Lock，经过批准的移植才可不同。 |
| **Lane wave** | 全部功能 Lane 与 Evaluation Lane 从同一 `contract_lock_commit` 开始的一组并行工作。 |
| **Work package** | 一个可独立评审、可回滚的工作单元，具有 owner、文件边界、输入输出合同、验收命令和 non-goals。 |
| **Evaluation** | 独立生产测试、fixture、golden、故障注入、性能和浏览器验证证据的角色。 |
| **Integration** | 根据独立证据管理 merge queue、处理仅机械的冲突、运行完整 gate、组织发布判断的角色。 |

## 4. 分支与 worktree 拓扑

实际启用时采用下列拓扑；本 ADR 本身不创建这些分支或 worktree：

```text
origin/main @ v1.7.2 (4b2e6c1...)
        │
        ▼
integration/v1.7.3
        │
        ├── contract-only commits
        ▼
contract_lock_commit C1
        │
        ├── feat/v173-agent-recipes-recovery
        ├── feat/v173-model-linear-mixed-effects
        ├── feat/v173-ui-agent-inspector-compare
        └── test/v173-evaluation-harness
        │
        ▼
independent evaluation evidence → merge queue → integration gate
        │
        ▼
origin/main → tag v1.7.3
```

规则：

1. `integration/v1.7.3` 从本 ADR 所记录的基线建立；所有功能与测试 Lane 从同一个 `contract_lock_commit` 建立，不能从另一个 feature branch 建立。
2. 每个 work order 必须记录 `release_baseline_commit`、`integration_base_commit`、`contract_lock_commit` 和 `branch_start_commit`，并且可由 `git rev-parse` 验证。首轮 `branch_start_commit` 必须等于 `contract_lock_commit`；经过批准的移植或恢复才可不同，并必须说明原因。一个 Lane 不得自行 `pull`、rebase 到其他 feature 的未锁定提交。
3. 若合同必须变化，Integration 先发起新合同提交、更新版本和 fixture，并生成新的 lock；受影响的 Lane 重新从新 lock 开始或以明确记录的方式移植。不得在同一 wave 中悄悄混用两套合同。
4. 每条 Lane 使用独立 worktree。功能作者、Evaluation 和 Integration 不得在同一 worktree 中修改同一批实现；临时 scratch、浏览器证据和生产代码也必须分开。
5. 建议的 worktree 名称为 `integration-v1.7.3`、`v173-agent-recipes-recovery`、`v173-model-linear-mixed-effects`、`v173-ui-agent-inspector-compare`、`v173-evaluation-harness` 与 `v173-release-train`。命名表达职责，不用版本号伪装为功能分支。
6. 任何 feature branch 都不得直接合入 `main`。远程 push、PR、merge、tag 和 release 仍须取得用户当时的明确授权。

## 5. Contract-first：合同冻结的是语义，不只是字段

### 5.1 共同合同集合

首个并行波次至少锁定下列合同。它们可以由现有 dataclass/JSON schema 演进而来，但不能把未版本化的内部 dict 当成公共接口。下表的“主生产者”指产生符合合同的 packet 实例，不表示在 lock 后拥有公共 schema 的写权限；公共 schema 始终由 Integration 管理。

| 合同 | 主生产者 | 主要消费者 | 语义职责 |
| --- | --- | --- | --- |
| `ModelCapabilityContract` | Model Pack | Agent、UI | 模型适用条件、需要字段、支持的设计与限制。 |
| `ModelInputSchema` | Model Pack | UI、Agent validator | 可编辑参数、类型、默认、禁用组合与必填项。 |
| `DiagnosticPacket` | Model Pack / deterministic checks | Agent、UI、Evaluation | 机器可判定的诊断代码、严重度、证据和候选恢复动作。 |
| `ModelResultContract` | Model Pack | Compare、Report、Agent、UI | 有稳定 result identity 的估计、区间、样本、模型元数据与 artifact 引用。 |
| `FigureContext` | Model Pack / deterministic figure resolver | Ask-AI、Report、UI | 图表类型、数值源摘要、解释边界和 artifact identity。 |
| `ComparePacket` | deterministic compare adapter | Agent、UI、Report | 参数、数据、结果与结论差异；包括不可比较理由。 |
| `AgentRecipe` | Agent | Agent driver、UI | 从受控模型事实到检查、proposal、解释和恢复的编排规则。 |
| `PlanDiff` / `ValidationPacket` | Agent + deterministic validation | UI、execution、Evaluation | 执行前的计划差异和执行完整性/模型有效性判断。 |
| `RecommendedActionCandidate` | Model Pack | Agent validator | 统计上允许的候选修复，不是可执行操作。 |
| `RecoveryActionProposal` | Agent | confirmation / execution | schema-valid、已约束、需要用户确认的执行提议。 |
| `ErrorContract` | 各受控生产者 | UI、Agent、Evaluation | 稳定 code、severity、retryability、user-safe message 和 evidence 边界。 |

所有合同都必须把“事实”和“解释”分开：模型、验证、比较和错误的事实由确定性后端产生；Agent/LLM 只解释这些已锁定事实或生成 schema-valid proposal，不能自行计算统计量、猜测 artifact 意义、或者把相关性表述成因果结论。

### 5.2 版本 envelope

每个锁定合同使用显式 envelope：

```json
{
  "contract": "model_result",
  "contract_version": "1.0",
  "producer_version": "linear_mixed_effects@1.0",
  "payload": {}
}
```

`contract`、`contract_version` 和 `producer_version` 都是必填字段。`contract_version` 使用 `major.minor`：major 表示不兼容语义边界，minor 表示向后兼容的扩展。不能只用类似 `model_result_v1` 的字符串而不说明生产者与兼容级别。

### 5.3 兼容规则

- 新增可选字段：允许；必须定义缺失时的默认行为，并有旧 consumer fixture。
- 删除字段：当前 release 禁止。
- 修改字段语义、单位、result identity 或比较口径：禁止在同一主版本中进行，必须提升 major 并重新锁定所有受影响合同。
- 新增 diagnostic code：允许；UI、Agent 和 report 必须有安全的 `unknown` fallback，不得把未知 code 当成功或自动执行。
- 新增 model capability：允许；不得改变既有模型的能力、默认选择或统计结果。
- 扩展枚举、operation 或 editable parameter：必须经合同变更和兼容性测试；不能以“前端暂时不用”为理由绕过。

### 5.4 Canonical fixture 先于功能实现

合同波次的顺序固定为：

```text
contract schema
→ canonical fixture / known-truth fixture
→ consumer mock packet
→ producer implementation
→ consumer implementation
→ independent evaluation
```

UI Lane 只依赖合同 mock 开发，不能读取 feature branch 的内部 JSON。Model Lane 必须让真实输出通过同一个 fixture/schema。Agent Lane 必须让 proposal 和解释消费同一 packet，而非重新从原始 artifact 推断。

### 5.5 Contract Lock Manifest

每个 release wave 必须有一个提交到仓库的 lock manifest。实现计划负责指定其精确路径；它至少包含：

```yaml
release: v1.7.3
release_baseline_commit: 4b2e6c1d9ddd289005b84c186255fec2e9cbd86a
integration_base_commit: <integration-branch-initial-sha>
contract_lock_commit: <exact-sha>

contracts:
  model_capability: "1.0"
  model_input: "1.0"
  model_result: "1.0"
  diagnostic_packet: "1.0"
  figure_context: "1.0"
  compare_packet: "1.0"
  agent_recipe: "1.0"
  plan_diff: "1.0"
  validation_packet: "1.0"
  recovery_action: "1.0"
  error_contract: "1.0"
```

示例中的尖括号值是 work-order 模板变量，不是尚未作出的协议决定：Contract Sprint 通过后必须用唯一的实际 commit 替换。没有 lock manifest 的工作包不进入 feature 开发，也不能进入 merge queue。

## 6. 共享扩展点与所有权

Integration 专属的当前中心文件包括但不限于：

```text
backend/workbench/agent/orchestrator.py
backend/workbench/agent/operations.py
backend/workbench/analysis_loop/** 的公共合同与持久化根语义
backend/workbench/engine/pack.py
backend/workbench/engine/registry.py
backend/workbench/engine/capabilities.py
backend/workbench/graph_store.py
frontend/src/workbench/agent/AgentSurfaceContext.tsx
scripts/gate.sh
```

这里的“Integration 专属”不是让 Integration 任意重构，而是防止 feature lane 竞争同一控制面。Integration 对这些文件只允许三种变化：

1. Contract Sprint 中为已批准合同建立薄扩展边界；
2. 只增加注册声明、且不改变 runner、结果语义或 feature 实现的机械接线；
3. 经独立复核确认没有行为变化的冲突解决。

一旦冲突解决需要改变统计、操作、确认、Graph 或 UI 行为，Integration 必须退回给相应的功能 Lane；不能在集成提交里“顺手修好”。

首个 Contract Sprint 要把下列中心化耦合改造成薄的、可声明的边界：

```text
Model pack manifest / registration declaration
    → registry loader
    → capability projection

Agent recipe declaration
    → recipe registry
    → orchestrator consumes registry

UI feature adapter / slot
    → AgentSurfaceContext consumes stable view model
```

并不要求自动发现机制。若自动发现会扩大启动、打包或安全风险，则允许 Integration 维护一个极薄的显式注册表；其提交只能增加新声明，不能携带 estimator 或 UI 功能改动。

Contract Sprint 生成 C1 后，所有公共合同定义由 Integration 专属维护。推荐把新合同根放在 `backend/workbench/contracts/model/**`、`backend/workbench/contracts/agent/**` 和 `backend/workbench/contracts/common/**`；如果 C1 为兼容现有代码继续使用 `backend/workbench/engine/model_contracts/**`，该目录同样是 Model Lane 的只读消费边界，不因名称含有 `model` 而成为其 owned scope。

在 Contract Sprint 完成后，Model Lane 的理想 owned scope 收缩为：

```text
backend/workbench/engine/packs/<pack_name>/**
tests/models/<pack_name>/**
tests/fixtures/models/<pack_name>/**
```

Model Lane 的 `read_only_contracts` 列表必须指向 C1 中锁定的公共合同根。若模型实现发现合同无法表达需要的事实或诊断，必须停止该 Lane、提交 Contract Change Request、由 Integration 形成新 lock wave 后再继续；不得在模型分支中补字段或改 schema。

这些路径在 v1.7.2 基线尚未全部存在，不能预先假装已经存在。Contract Sprint 必须以现有 `engine/pack.py`、`registry.py` 和 `capabilities.py` 为依据创建最小、明确的路径和 loader；之后每个 work order 列出实际路径，不得笼统声明拥有 `backend/workbench/engine/**`。

## 7. 四类职责边界

### A. Agent Lane

**生产：** `AgentRecipe`、`AgentProposal`、`PlanDiff`、`ValidationPacket`、`RecoveryActionProposal`、`CompareExplanation`、Agent operation/error state、受预算限制的 `RobustnessBranchPlan`。

**消费：** `ModelCapabilityContract`、`ModelInputSchema`、`DiagnosticPacket`、`RecommendedActionCandidate`、`ModelResultContract`、`ComparePacket`、`FigureContext` 和 `ErrorContract`。

**禁止：**

- 实现或修改 estimator；
- 改变 coefficient、standard error、p-value、CI 或 result identity 的语义；
- 绕过 model validator、operation registry、risk policy 或用户确认；
- 直接改写 Graph 核心持久化结构；
- 在没有确认或已授予的批量授权时执行连续分支；
- 让 LLM 发明 editable schema 以外的字段、custom code 或未注册动作。

Agent Recipe 的职责是决策与编排，不是模型事实的所有者。模型包只能提供 `recipe_hints`，不能把整个 Agent 执行流写进模型实现。

### B. Model Pack Lane

**生产：** `ModelCapabilityContract`、`ModelInputSchema`、validator、estimator adapter、`DiagnosticPacket`、`ModelResultContract`、`FigureContext`、`RecommendedActionCandidate`、compare adapter、known-truth fixture 和模型测试。

**消费：** pack/registry extension contract、artifact contract、error contract 以及 Contract Lock Manifest。

Model Lane 产出的是符合锁定 schema 的模型 packet；锁定后的 `ModelCapabilityContract`、`ModelResultContract`、`DiagnosticPacket`、`FigureContext` 和 `RecommendedActionCandidate` 定义均为只读公共合同。

**禁止：**

- 实现确认 UI、Agent orchestrator 或自然语言策略；
- 从 runner 直接创建可执行 Agent operation；
- 自行决定 UI 展示结构；
- 改变 Graph lineage、run lifecycle 或 source artifact；
- 修改公共 registry、capability projection 或 gate，除非工作包是 Integration 授权的薄注册提交。

恢复行为严格分两段：

```text
Model Diagnostic
→ RecommendedActionCandidate
→ Agent validation
→ RecoveryActionProposal
→ user confirmation
→ typed execution
```

Model Lane 只对统计上是否允许候选动作负责；Agent Lane 对用户可见理由、schema-valid patch、确认和执行提议负责。

### C. UI/UX Lane

**生产：** AgentPanel、Proposal/Confirmation/Execution state views、Node Inspector、Compare view、Validation issue view、Report/Figure renderer 适配、loading/error/empty states，以及基于 mock 的组件与交互场景。独立 browser E2E 的通过判定属于 Evaluation Lane。

**消费：** versioned mock `AgentProposal`、`ModelResultContract`、`DiagnosticPacket`、`ComparePacket`、`FigureContext`、`ValidationPacket` 和 error packet。

**禁止：**

- 在前端重新计算系数、诊断、比较或结论；
- 根据 UI 条件改变模型、数据或 Graph 语义；
- 依赖未版本化的后端内部字段；
- 跳过 confirmation 或把 pending/error 显示为成功；
- 以视觉层的“推荐”替代后端的 schema/validator 判断。

UI Lane 可以先用 canonical mock 完成完整交互路径，随后只替换数据源 adapter；它不等待真实 Mixed Effects runner 才开始工作。

### D. Independent Evaluation Lane

**生产：** synthetic dataset、known-truth fixture、golden output、fault injection、合同兼容性测试、Agent proposal tests、统计正确性测试、报告过度主张测试、性能基线、browser E2E 与 release evidence。

**禁止：**

- 实现或修复被测功能；
- 为了通过测试修改 estimator、Agent recipe 或 UI；
- 静默提高数值容差、更新 golden、删除失败案例或弱化 gate；
- 没有 known truth 就声称模型正确；
- 同时充当 feature author 与该 feature 的通过判定者。

Evaluation 需要独立 worktree、独立任务说明、独立提交和独立完成报告。即便由同一个 AI 系统执行，也不得共享功能实现上下文来替作者补测试或解释失败。

### Integration Release Train

Integration 不属于 D Lane 的实现职责。流程上必须分为：

```text
Evaluation role
    → immutable evidence and failure reports
Integration conductor
    → merge decision, full gate, browser acceptance, release recommendation
```

Integration 读取证据而不修改证据。它也不能在失败后替作者改变实现、预期、容差或统计解释。若必须改变行为，则退回相应 Lane，产生新的提交和新的独立 Evaluation。

## 8. v1.7.3 的首个 3+1 垂直切片

本协议的第一个并行试点是 **Repeated Measures Analysis**，目标不是一次添加大量模型，而是证明 3+1 模式能够交付一个完整、可验证、可恢复的分析闭环。

### 8.1 范围

Model Pack 的最小能力为 `linear_mixed_effects`：

- 连续型 outcome；
- subject/group identifier；
- time variable；
- fixed effects，包含 group × time interaction；
- random intercept；
- 可选 random slope；
- 收敛、奇异随机效应、组数不足、缺失必要字段等结构化诊断。

Agent Lane 提供 Repeated Measures Analysis Recipe：识别 subject/time/outcome/group、检查设计条件、提出 schema-valid run/rerun、解释诊断，并将模型的候选恢复动作转换为需要确认的 proposal。对阻塞性设计错误，它必须解释缺少什么或为何不可估计，而不是伪造可执行的 recovery。

UI Lane 提供对应 proposal、PlanDiff、confirmation、execution、Node Inspector、诊断、source/child Compare、figure 和 error/loading 状态。

Evaluation Lane 提供已知固定效应与随机效应方差的合成重复测量数据，以及缺失 `subject_id`、组数不足、singular random effects、不收敛、非法配置、过度解释和 child rerun 等故障路径。

### 8.2 Linear Mixed Effects statistical contract

Contract Sprint 必须在任何 `linear_mixed_effects` 实现前锁定下列统计语义。仅冻结 JSON 字段不足以保证 source/child 的结果可解释或可比较。

1. **拟合方法与比较。** 锁定默认使用 ML 或 REML、是否可编辑、以及有效 fit method 如何写入 PlanDiff、ModelResultContract 和 result identity。若两个 REML 模型的固定效应结构不同，ComparePacket 必须返回 `comparability: restricted` 与 `reason_code: REML_FIXED_EFFECTS_DIFFER`；不得以 likelihood、AIC 或 likelihood-ratio test 宣称其中一个模型更好。用户安全文案必须说明限制，而不是展示绿色优胜结论。
2. **固定效应推断。** 锁定公式的 canonical representation、分类变量参考水平、时间作为连续或分类变量的编码、交互项编码、系数估计/标准误/置信区间的来源，以及自由度或 p-value 方法。若实现仅提供渐近正态近似，结果与报告必须如实标注，不能暗示使用未实现的自由度修正。
3. **随机效应输出。** 明确 random-intercept variance、random-slope variance、intercept–slope covariance、residual variance、group count 与每组 observations summary 的单位、稳定 result id 和 `null` 规则。
4. **缺失值策略。** 明确哪些缺失阻塞、哪些字段纳入 complete-case filtering、过滤在公式展开前后的顺序、每种排除原因的计数，以及过滤后的 `n_obs`/`n_groups`。ComparePacket 必须把样本改变与参数改变分开，不能只输出一个最终 n。
5. **收敛和奇异性。** 锁定标准化 convergence code、optimizer status、可获得的梯度/迭代证据、singularity threshold、variance 近零规则，以及 warning 与 blocking 的界线。模型不得把“随机效应方差很小”的原始数值交给 LLM 自行判定；确定性 DiagnosticPacket 负责分类。
6. **结果身份与可比性。** result identity 至少包含 dataset fingerprint、analysis unit、outcome、fixed-effects formula、random-effects specification、group variable、fit method、missing-data policy、estimator version 与 contract version。不同 identity 组成部分发生变化时，ComparePacket 必须按锁定规则返回 comparable、restricted、partial 或 not-comparable，并带稳定 reason code。

```text
repeated-measures data
  → Agent identifies design fields
  → validation / recipe
  → PlanDiff + confirmation
  → Linear Mixed Effects run
  → result, diagnostics, figure
  → recovery candidate when needed
  → confirmed child rerun
  → ComparePacket
  → constrained Agent explanation
```

### 8.3 明确不做

- 一次性扩充十几个模型、自动选择任意模型族或建立独立 models 平台；
- 无限制 Agent autonomy、任意 custom code 或未经确认的多分支运行；
- 更换数据集、大规模清洗、任意派生变量或多节点 Graph 重写；
- 重写 Graph store、全部前端页面或最终完整设计系统；
- 同时升级所有现有合同主版本；
- 为 Mixed Effects 引入新的公共依赖环境，除非用户另行明确批准；
- 真实 LLM/API 作为日常 feature 或测试依赖。真实 provider 只可在用户明确授权的独立验收步骤调用，且不成为 release gate 的唯一证据。

### 8.4 与已有 v1.7.3 文档的关系

`2026-07-18-v1.7.3-report-ops-closeout.md` 记录的是并行协议前已经追踪的 report/operations 工作包及其验证证据。本 ADR 不重写、伪造完成或自动发布那份计划；它要求后续 v1.7.3 release ledger 明确列出该工作包与 Repeated Measures 试点各自的状态和证据。

Repeated Measures 是 **首个采用本协议的 3+1 垂直切片**。它不能因为已有 report/operations 证据而跳过 Contract Sprint，也不能把已发布的 v1.7.2 worktree 当作可写开发区。

## 9. 一个工作波次的固定流程

### Phase 0：冻结基线与 Contract Sprint

1. Integration 从基线建立 integration branch，并记录工作树状态、保护测试和依赖环境。
2. Integration 定义版本化 schema 与最小薄扩展点；Evaluation 在独立的 contract-fixture worktree 提供 canonical fixture、known truth 和 mock consumer packet。该预锁贡献只能包含合同与验证资产；Integration 将其受控纳入 C1。
3. 合同兼容性测试在没有功能实现的条件下通过后，生成唯一 `contract_lock_commit`。
4. 线性混合模型可行性只允许作为 Contract Sprint 的受限 spike：验证已有 Python 环境是否能支持既定 estimator、确认输入/输出及错误分类。它不得安装、升级或修改共享依赖；如果现有环境不足，停止并请求用户对依赖策略作决定。

完成 C1 后，正式的 `test/v173-evaluation-harness` 与三条 feature Lane 一样都从 C1 建立；它不是从任何 feature branch 派生。这样“fixture 先于实现”和“同一 wave 使用相同锁定基线”同时成立。

### Phase 1：从同一 lock 并行开发

1. 每条 Lane 基于相同 lock 建立独立 worktree，领取一个有边界的 work package。
2. 功能 Lane 在实现前必须建立或明确一个可失败的验收证据，再完成最小实现。证据可以是红色 unit/integration test、失败的 contract test、失败的 browser scenario、明确的 snapshot 差异、可重复的性能基线或可访问性检查；不能先完成实现，再编写只会验证当前实现的测试。公共合同变更必须退回 Phase 0。
3. UI 使用 canonical mock；Agent 消费已有 schema；Model Pack 产出真实 packet。各 Lane 不等待另一个 feature branch 的内部实现。
4. Lane 完成时提交 completion report，不自行宣称 release-ready。

### Phase 2：独立 Evaluation

1. Evaluation 在独立 worktree 对每个候选分支和随后候选集成提交运行合同、known-truth、fault、overclaim、性能与浏览器测试。
2. 失败报告必须包含可重现命令、基线、实际结果、预期结果、最小证据与归属建议；不提供功能补丁。
3. 功能作者修复后产生新提交；Evaluation 重新验证。审查调用超时、测试 runner 卡住或浏览器会话中断时，Evaluation 记录故障并重新从干净 worktree/最小复现启动，不能因此把整个 Release Train 停在“等待审查者”。

### Phase 3：Merge queue 与集成

建议顺序为：contract lock → Model Pack → Agent → UI → cross-lane adapters。实际顺序由依赖图决定，而不是分支完成先后；任何顺序都必须保持 contracts 兼容。

- Integration 只接受已带 completion report 和独立 Evaluation 证据的候选提交；
- 冲突若是机械注册，可由 Integration 以单独提交解决；
- 冲突若改变行为、统计语义、confirmation、Graph 或 UI 状态，退回 owner Lane；
- merge queue 中每次合并后运行增量兼容性检查，最终在候选 integration tip 上重新运行独立 Evaluation。

### Phase 4：Release decision

候选集成 tip 必须通过全量 gate、browser acceptance、性能证据和发布证据审查，才能向用户提出合并/发布建议。没有用户明确授权时，Release Train 不 push、不建 PR、不 merge、不 tag、不创建 GitHub release。

## 10. Work Order 与 Completion Report

每个 AI/工程工作包必须随分支提交两类可审查材料。实施计划将固定它们的存放位置；字段本身不可省略。

### 10.1 Work Order

```yaml
work_package: v173-model-linear-mixed-effects
lane: model
release_baseline_commit: 4b2e6c1d9ddd289005b84c186255fec2e9cbd86a
integration_base_commit: <integration-branch-initial-sha>
contract_lock_commit: <C1-sha>
branch_start_commit: <C1-sha>

owned_files:
  - backend/workbench/engine/packs/linear_mixed_effects/**
  - tests/models/linear_mixed_effects/**
  - tests/fixtures/models/linear_mixed_effects/**

read_only_contracts:
  - backend/workbench/contracts/model/**
  - backend/workbench/contracts/common/**

forbidden_files:
  - backend/workbench/agent/orchestrator.py
  - backend/workbench/engine/registry.py
  - backend/workbench/graph_store.py
  - frontend/**
  - scripts/gate.sh
  - tests/test_honest_did_adversarial.py
  - tests/test_honest_did_sd_adversarial.py

consumes:
  - ModelCapabilityContract@1.0
  - ModelResultContract@1.0
  - DiagnosticPacket@1.0
  - FigureContext@1.0

produces:
  - linear_mixed_effects ModelResultContract@1.0
  - RecommendedActionCandidate@1.0

preimplementation_acceptance_evidence:
  kind: failing contract test
  command: "pytest ..."
  initial_observation: "..."

acceptance:
  - targeted unit tests
  - contract tests
  - known-truth numerical tests
  - failure-injection tests

non_goals:
  - Agent orchestration
  - UI implementation
  - Graph schema changes
  - unrestricted model selection
```

`owned_files` 是许可清单，不是建议；`read_only_contracts` 明确锁定后可读取、不可改写的公共合同根。出现共享文件或合同需求时，作者必须提出 Integration work request，不能直接修改。`forbidden_files` 必须包含 `tests/test_honest_did_adversarial.py`、`tests/test_honest_did_sd_adversarial.py` 和本协议列出的 central files，除非用户和 Integration 显式改写 work order。

### 10.2 Completion Report

每个 Lane 完成时报告：

1. 实现了什么、没有实现什么；
2. 精确修改的文件和提交；
3. 是否修改合同、使用哪个 lock；
4. 执行过的命令及精确结果；
5. 已知限制、失败路径和性能观测；
6. 潜在集成风险、建议合并顺序和回滚方式；
7. 是否触碰 forbidden/protected files（应为否，或带明确授权和理由）。

没有 completion report 的 branch 不能被 Integration 视为可合并。

## 11. 失败、阻断与恢复协议

并行不是“所有人等待最慢任务”。以下处理是强制的：

| 情况 | 必须动作 | 不允许动作 |
| --- | --- | --- |
| 合同不够表达需求 | 停止受影响 Lane，提出合同变更，产生新 lock wave。 | 在 payload 偷塞未版本化字段。 |
| 共享文件冲突 | 交给 Integration 分类；行为变化退回 owner。 | 在 merge commit 中悄悄重构或改变语义。 |
| feature test 失败 | 作者最小复现、修复并重新提交。 | 改 golden、提高容差或删测试。 |
| Evaluation runner/审查调用超时 | 记录最后可见证据；从独立干净 worktree 重新启动最小复现或备用检查。 | 无限等待、把“未返回”写成通过或停止整个任务。 |
| lane worktree 污染或依赖异常 | 保留证据，重新创建/恢复干净 worktree；只复用已提交变更。 | 在其他 Lane worktree 临时修补或修改公共环境。 |
| real-provider 验收失败 | 报告 provider/网络/产品层的可区分证据；本地 deterministic tests 仍独立判定。 | 伪造 LLM 成功或让真实 API 成为唯一 correctness oracle。 |

长期工作协议要求每个阻断都有下一步：**记录 → 最小复现 → 重启独立检查 → 分类为代码、环境、合同或外部服务 → 继续可推进的工作。** 只有确实需要新的用户授权、依赖策略或产品选择时才停止请求方向。

## 12. 验收与 Definition of Done

### 12.1 Lane-local gate

每个 feature Lane 必须至少通过：

- 实现前建立或明确的可失败验收证据；
- 相关 unit/integration tests；
- versioned contract validation；
- 当前 lock 的 fixture/mock compatibility；
- `git diff --check`；
- work order 中的边界与 protected-file 检查。

### 12.2 Independent Evaluation gate

Evaluation 必须在已知真值和故障注入上证明：

1. 所有公共 packet 能通过 schema validation；
2. 前端 mock 与真实 packet 有相同合同形状；
3. `linear_mixed_effects` 在 known-truth fixture 上达到 Contract Sprint 锁定的误差范围；
4. 至少一个可恢复诊断会产生有效 `RecommendedActionCandidate`，并经 Agent 转成合法、需确认的 `RecoveryActionProposal`；
5. 至少一个不可恢复诊断（例如缺少 `subject_id` 或每个 subject 仅一次观测）保持 `blocked`，且不会产生伪造的可执行 operation/proposal；
6. 可恢复案例的 child rerun 创建新 child，不覆盖 source run；
7. ComparePacket 能分别说明参数、样本、结果和结论变化，或诚实标为不可比较；
8. Agent 不把关联性/模型结果越界表述为因果结论；
9. UI 有 loading、error、confirmation、pending 和 success 的可见状态；
10. 功能 Lane 未越权修改 protected tests、gate 或 central files；
11. 浏览器路径从数据/节点上下文到确认、执行、诊断、child compare 和解释可用。

### 12.3 Evaluation Evidence Manifest

每次 Independent Evaluation 都必须生成并提交一个结构化 evidence manifest。它是 Integration 判断的最小单位，而不是一句“tests passed”。manifest 一经提交不得原地改写；补跑、复验或更正必须生成新的 `evaluation_id` 并保留旧证据。

```yaml
evaluation_id: eval-v173-lmm-001
evaluated_commit: <candidate-sha>
contract_lock_commit: <C1-sha>
evaluation_harness_commit: <evaluation-sha>

environment:
  python_version: "..."
  node_version: "..."
  os: "..."
  dependency_lock_hash: "..."
  machine_fingerprint: "..."

commands:
  - command: "pytest ..."
    exit_code: 0
    duration_seconds: 12.4
    output_artifact: "..."
    output_sha256: "..."

fixtures:
  - path: tests/fixtures/models/linear_mixed_effects/known_truth.json
    sha256: "..."

results:
  contract_validation: passed
  known_truth: passed
  fault_injection: passed
  browser_e2e: passed
  overclaim_checks: passed

artifacts:
  - path: "..."
    sha256: "..."

generated_at: "..."
```

manifest 不得记录 API key、provider secret、原始机器身份或用户数据。任意中央 adapter、registry declaration、合同 projection 或冲突解决提交进入候选 integration tip 后，旧证据不得直接复用；Evaluation 至少重新运行受影响的合同、功能和浏览器检查，并生成指向新 `evaluated_commit` 的 manifest。

### 12.4 性能证据

Evaluation 在固定 fixture、机器条件和数据规模下记录 warmup 次数、正式运行次数、冷/热缓存状态、失败率、机器条件、输入规模、artifact 数量、是否全量 refetch，以及至少以下指标的 p50/p95：

```text
NodeOperationContext construction
ComparePacket generation
Agent proposal confirmation → visible terminal state
Linear Mixed Effects fit
Graph child indexing / focus
```

Contract Sprint 根据实测基线为本波次锁定可接受阈值；在没有基线前不虚构 SLO。性能优化只在指标阻塞闭环或明显违背锁定阈值时进入该 work package，不能以“顺手优化”为由扩大功能 scope。

### 12.5 Release Definition of Done

v1.7.3 只有在至少一条完整路径成立时才可被称为本协议的 0→1 试点完成：

```text
repeated-measures data
→ Agent identifies subject / time / outcome / group
→ validation and Analysis Recipe
→ user reviews PlanDiff and confirms
→ Linear Mixed Effects Model Pack executes
→ structured result, diagnostics and figure are visible
→ recoverable failure yields a constrained, confirmed RecoveryActionProposal
→ unrecoverable design failure remains blocked without an executable proposal
→ confirmed recoverable child rerun preserves lineage
→ ComparePacket and Agent explanation state whether the conclusion is stable
```

并且完整 gate、独立 Evaluation、浏览器验收、依赖/安全边界检查均有可审查证据。单个模型函数、单个 UI 页面或单个 LLM 演示都不足以构成完成。

## 13. 安全、依赖与发布权限

- v1.7.1 与已发布 v1.7.2 worktree 是只读发布基线；新功能只在相应 Lane worktree 中开发。
- 不修改 `tests/test_honest_did_adversarial.py` 或 `tests/test_honest_did_sd_adversarial.py`。任何例外都需要用户明确授权和独立审查。
- 不重新安装、卸载或修改公共依赖环境；若 Mixed Effects 或测试真正需要新依赖，先报告现有环境的可行性证据并请求批准。
- 不调用真实 API，除非用户明确授权某次独立验收。真实 provider 的文本只能作为产品互操作性证据，不能取代 deterministic contract/known-truth 验证。
- 不 push、PR、merge、tag 或发布，除非用户对该动作明确授权。Integration Release Train 可以准备证据和建议，但不越权执行外部状态变更。

## 14. 后果与反模式

该协议增加了一个短的 Contract Sprint 和独立 Evaluation 循环，换取后续 Agent、模型和 UI 的真实并行性。它刻意拒绝以下看似更快、实际会降低交付速度的做法：

- 多个 AI 在同一 worktree 同时改中央文件；
- 先各自实现、最后再猜合同；
- 用一个 Agent 同时实现、修改测试、改 golden、解决冲突并宣布发布；
- 把每个新模型都塞入 `registry.py`、`orchestrator.py` 或单一巨大前端 context；
- 让 LLM 读取大量未结构化 JSON 后自行判断结果可比性；
- 因 runner、审查或外部 API 暂时卡住而无限等待或停止其他可验证工作。

成功标准不是同时拥有更多 branch，而是每条 branch 的输入、输出、职责、验证和回滚都足够明确，使它们能低成本汇合。

## 15. 下一步

本 ADR 已正式接受并自 v1.7.3 起生效。本 ADR 本身不创建 Lane、合同 lock、worktree 或产品代码。

下一步进入 v1.7.3 Repeated Measures 实施计划编写阶段。实施计划必须先完成 Contract Sprint、四个 Work Order 和 Repeated Measures vertical slice 的验收设计，并且把真实路径、真实命令和实际 contract SHA 写入可分派的工作包。

1. Contract Sprint 的精确任务、合同 schema、fixture 和薄扩展点；
2. 四个 work order 的实际 owned/forbidden paths 与验收命令；
3. lane wave 的创建顺序、独立 Evaluation 和 Integration release train 流程；
4. Repeated Measures vertical slice 的范围、风险和退出条件。
5. Evaluation 的 golden 更新审批、重复性能测量和确定性 report-overclaim 检查。

在实施计划获得用户批准前，不创建功能 Lane，不修改产品代码。
