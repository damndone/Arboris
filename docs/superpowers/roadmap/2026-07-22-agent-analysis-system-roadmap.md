# Agent 分析系统路线（2026-07-22 拍板）

> 状态：长活 roadmap。经 2026-07-22 两轮对齐后由用户拍板。
> 上游输入：v1.8.0 发版当日的独立验收 + Stata do-file 真机复现结果。
> 与 `2026-07-01-unified-graph-workbench-roadmap.md`（图谱北极星）并列，不替代它。

## 0. 这份路线是从哪来的

v1.8.0 发版当天做了两件事：对候选版本做独立验收，以及用用户自己的 VIXCLS Stata
do-file 在真机上跑一遍全流程。结果分成很干净的两半：

**统计内核扎实。** 参数与前一次 run 逐位相同；ADF、Ljung–Box、ARCH-LM、Jarque–Bera
逐项对上 Stata；持续性 0.7752 与半衰期 2.7226 与手算一致；在 do-file 自己的八个候选集里，
BIC 选出了它选的同一个模型。

**六个缺陷全部在外围**，而且**五个是 2960 条确定性测试一条都盖不住的**：交付物投影、
Compare 渲染、HTML 导出、Agent 工具预算、propose_operation 形状。它们需要真实使用
或真 provider 对话才会暴露。

结论因此不是"再加一个估计器"，而是：**扩展 Agent 能提议什么，而不是让它绕过类型、
验证和确认去直接执行。**

## 1. 三条系统不变量

任何版本不得违反。这三条是 Workbench 相对"让通用助手写 pandas"的全部差异所在。

```
没有类型的内容，可以解释，但不能执行。
没有验证的实现，可以实验，但不能产出正式数字。
没有 lineage 的结果，可以预览，但不能成为 Workbench 结论。
```

### 自主性分级

北极星不是"更自主的 Agent"。准确的表述是**认知自主性高、操作自主性分级**：

| 高度自主（无需确认） | 必须走完整链路 |
|---|---|
| 理解问题、检查数据、发现异常 | 修改 Graph |
| 设计路径、生成备选、解释原因 | 安装依赖 |
| 设计验证工装 | 执行新算法 |
| 提出质疑与警告 | 生成正式数值、覆盖已有结果 |

右列一律：`typed → validate → confirm → execute → verify → commit`。

这与既有分层一致：Proposal Agent → Confirmed Operation Agent → Bounded Autonomous
Analyst。自治不是被禁止，而是必须建立在明确预算、操作白名单、非破坏性分支和完整
lineage 之上。

---

## 2. v1.8.1 — Agent Notebook + 选中文本交互（主线）

### 架构定位（关键）

**Notebook 是 Graph 的叙事视图，Graph 仍是唯一事实源。**

不建设第二套类似 Jupyter 的独立执行状态。否则必然出现：Notebook 显示一套参数、
Graph 保存另一套、Run 实际执行第三套。

Notebook 的每一部分都引用既有对象（Dataset / Node / Draft / Proposal / Run /
Artifact / Compare / Diagnostic），叙事顺序为：

```
用户目标 → 数据检查 → Agent 推荐路径 → 已选方案
        → 执行结果 → 诊断 → 备选方案 → Compare → 结论
```

### 备选方案不是一段自然语言

未选择的备选方案必须存为结构化对象 `AnalysisOption`，带上下文指纹。
准确说法是：**保留一个尚未 materialize 的、带上下文指纹的 typed branch proposal**——
比预先创建大量空 Graph 分支干净得多。

状态机至少含：`proposed / selected / deferred / executed / rejected / stale`。

`stale` 是重点：用户今天没选方案二，几天后数据、上游节点或变量定义已变，系统不能
仍把旧方案显示为"一键可运行"，应据 `source_context_hash` 判定是否需要重新验证。

**这一层比看上去便宜**：仓库已有 `analysis_view_hash`、`contract_hash`、`split_hash`、
节点 Merkle identity 和 `node_index`。stale 判定是复用既有内容寻址，不是新基建，
而且与 Compare 判"样本是否变了"用同一套哈希，天然一致。

详见 `specs/2026-07-22-v1.8.1-agent-notebook-analysis-option.md`。

### 选中文本交互

不能只做"复制选中文字到输入框"。至少四类语义明确的操作：

```
加入下一次提问 / 解释这段内容 / 围绕这段内容提问 / 转成分析提议
```

可选再加：保存为备选方案、保存为 Notebook 备注。

**"转成分析提议"不得直接触发执行**，而应生成 typed proposal 走现有校验与确认流程。

选区必须保存稳定锚点而非只存文本：`message_id / block_id / start_offset /
end_offset / selected_text / text_hash / node_id / run_id`。

> ⚠️ `text_hash` 能处理重排版，处理不了**消息重新生成**。Agent 消息被重新生成时
> `message_id` 仍在但内容已换——此时锚点必须**硬失效**，不得静默重绑到相似文本上。

---

## 3. v1.8.2 — 评测工装 + 设定诊断建议 + 联合 MLE

### 3.1 评测工装（横向基础，先行）

必须**照着"实现与测试合谋"这一失败模式设计**，否则只是再造一套自洽的绿灯。

v1.8.0 的实测教训：

- `deliverables.py` 的 fixture 用的正是 exporter 猜错的列名——实现与测试互相自洽、
  双双偏离真实 artifact，八张表"非空"但三张不可用；
- HTML 审计导出没有渲染测试，只测 JSON/Markdown 载荷，于是"支持三种格式"字面为真、
  实质为假；
- Agent 工具输出超预算是**第三次**发生，前两次都补了测试，但都是照已知触发路径补，
  第三条路径（候选表行宽）没人想到。

因此硬性验收标准：

1. **fixture 一律从真实持久化响应提取，禁止手写。**
2. `proposal replay` 只能证明不回归，证明不了新路径；**必须掺真 provider 的
   探索性运行**（v1.8.0 那两个 Agent 缺陷都是真 DeepSeek 一轮对话抖出来的）。
3. 覆盖：已知真值数据集、参考实现对照、数值容差、错误注入、Graph lineage 检查、
   结论忠实度检查。

> 现在不训练 ≠ 现在不采集。从 v1.8.1 起就记录：Agent 看到什么上下文、生成哪些候选、
> proposal 是否通过 schema validation、用户选择/修改/拒绝了什么、执行是否成功、
> 诊断是否通过、结果是否被 Compare 推翻、结论是否忠于 Artifact。

### 3.2 联合 ARMA-GARCH MLE + 设定诊断建议

**理论前提要说准确**：联合 MLE 只在**联合分布假设正确时**才有效率优势。若某个分布、
相关结构或误差假设设错，联合估计会把错误沿似然传遍所有参数；顺序估计对整体联合分布
依赖较弱，反而更稳健。这是全信息 vs 有限信息的经典取舍（同 3SLS/FIML 对 2SLS/LIML）。

所以既不能说"联合 MLE 永远更准"，也不能因为"当前点估计、预测和诊断已一致"就永不实现。
**该实现，但真正值钱的是"什么时候该用"。**

建议必须表现为 typed recommendation，而非 Agent 依一句自然语言直接切换估计器：

```
当前建议：顺序估计
原因：……（如标准化残差平方仍有显著自相关，方差方程可能设错）
升级条件：方差诊断满足……
备选方案：联合 MLE
预期收益：联合标准误、联合 IC
额外风险：优化稳定性、计算成本、设定错误的跨方程传播
```

数值 parity 的验收要求（冻结 Stata oracle、conditioning、LL/IC、收敛、预测）
见 BACKLOG `§2-V1.8.2-JOINT-ARMA-GARCH-MLE`，不在此重复。

---

## 4. v1.8.3 — Capability Extension Proposal

只开放"提议扩展能力"，**不开放正式运行时自动安装**。

以下能力不应存在：正式分析运行中发现缺包 → Agent 直接 `pip install` → 现场写
Adapter → 用用户数据跑出正式数字。它会同时破坏 fail-closed sandbox、依赖可复现性、
供应链安全、single-worker 控制面、数值可信度和已审查代码边界。

安全流程：

```
检测能力缺口 → CapabilityExtensionProposal（依赖或自研）→ Adapter → 验证工装
→ 隔离构建环境测试 → 人工审查 → experimental → 达到验证门槛 → verified
→ 才能用于正式数值输出
```

**构建环境可以联网，正式分析环境仍然断网。**

### 缺失的一层：没有 oracle 时怎么办

原设计预设 oracle 存在。但 Agent 提议的能力很可能压根没有参考实现——那正是要扩展它的
原因。DID 套件能做到 1e-13 是因为有 `HonestDiD`、`fixest::sunab`、`DIDmultiplegtDYN`
可对；新能力未必有。若不补这一层，v1.8.3 会卡死在验证门槛上。

分层判据：

| 情形 | 判据 | 可达等级 |
|---|---|---|
| 有 oracle | 逐元素数值对照（现有标准） | verified |
| 无 oracle，但有可推导性质 | 性质检验：已知 DGP 模拟能否回收参数；不变量是否成立（如 α+β<1、方差非负、退化情形收敛到已知闭式解） | verified |
| 两者皆无 | — | **只能停在 experimental，永不升 verified**，产出数字须带不可移除标记 |

第三档不是妥协，是让"任何未验证实现都不能伪装成 verified estimator"这条不变量
有可执行判据。

### 前置阻塞：Artifact payload schema

```
ARTIFACT-SCHEMA-REGISTRY
        ↓ blocks verified promotion
V1.8.3-CAPABILITY-EXT
```

v1.8.1 的输出契约只匹配 `artifact_id + artifact_type + count`（DEC-ART-001），
对仓库内已注册、已知行为的能力够用。但外部依赖 Adapter 或 Agent 生成的新 capability
不同：只知道"它产出一个 table"远远不够，系统还必须知道该 table 是否确实含
参数名、估计值、标准误、区间、样本量、模型标识。

**实验性 capability 可以构建与测试，但在没有 payload contract 之前，
不得晋升为可产出可信数字的 `verified`。**

---

## 5. v1.8.5 — Typed Memory + 项目历史检索

> **2026-07-31 改标**：本节原定为 v1.8.4。实际发布的 v1.8.4（tag `v1.8.4` = `9ff0551`）
> 是 Agent Model Composition —— 版本号被复用成了另一个主题，而本节从未同步，导致文档里
> 一度同时存在两个互相矛盾的 v1.8.4 定义。根因是 v1.8.4 没有设计文档，范围只活在逐条
> devline 的 Context Pack 里，没有任何一层回答「这个版本整体交付什么」。
>
> 本节内容顺延 v1.8.5，范围与裁定以
> [`v1.8.5 设计文档`](../specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md) 为准。
> 其中 apply_mode 只做 `inform_only` + `suggest_default`，执行者做运行时判定 + gate
> preflight 两层，**六层检索链明确排除在 v1.8.5 之外**。

记忆不能是"把历史聊天总结一下塞进系统提示词，下次默默影响 Agent"。
**会漂移的记忆比没有记忆更糟**——这句话是本仓库自己写的
（`arma_garch_vocabulary.py` 开头："会漂移的词汇表比没有更糟"）。

### 分级

| 类型 | 例 | 要求 |
|---|---|---|
| 用户偏好 | 报告默认中文；优先可解释模型 | 用户确认，通常无需统计检验 |
| 项目/领域事实 | 财年 4 月起；`customer_id` 是分析单位；某字段单位 mg/L | 必须有来源、作用域、版本 |
| 分析模板 | 重复测量默认考虑 subject-level correlation | 只能作 proposal 默认值，不得跳过当前数据检查 |
| 可执行经验 / Failure Memory | 扁平点号 patch 无效，必须嵌套对象 | 附正向测试、反向测试、`vocabulary_version`、最后验证时间、失效条件 |

### Memory Registry

```
memory_id / memory_type / scope / statement / evidence / verifier
vocabulary_version / confidence / last_validated_at / expires_at / apply_mode
```

`apply_mode ∈ {inform_only, suggest_default, require_confirmation}`。
**记忆永远不能获得 `bypass_validation` 权限。**

> ⚠️ `last_validated_at` / `expires_at` **需要执行者**。没有执行者，记忆要么静默过期
> 要么静默长存，两种都比没有记忆糟。建议走与共享依赖守卫相同的路子：规范写进文档、
> 判据写进 `gate.sh` preflight、契约测试钉住行为。

### 检索

顺序是 **Graph 和元数据优先，向量检索只作文本补充**。

对普通大型表格，向量检索是错的工具——你不是要"找到相关的行"，而是要算统计量；
`tool_output_budget_exceeded` 的正确解法是有界投影而非向量库。

但以下确实适合检索：开放式问卷、病历文本、日志、文档与研究报告、代码与分析说明、
几百个历史 Run 的解释与决策、跨项目方法记录。

因此更准确的目标不是"RAG"，而是 **Context Compiler**：

```
1 Graph 邻域与 lineage 确定性检索
2 元数据过滤
3 有界结构化投影
4 关键词检索
5 仅对文本内容使用语义检索
6 rerank 与上下文预算控制
```

**RAG 可以延期，有界上下文编译不能延期**——Notebook Agent 本身就依赖它。

---

## 6. 更后续 / 明确不做

更后续：OCR 与非结构化文档提取、更大规模历史内容检索、有限多分支自治、
离线偏好优化、工具路由与方案排序训练。

**不应进入正常路线**：

- 运行时自研估计器并立即用于正式结果；
- 在线强化学习修改 Agent 行为。

关于学习系统的边界：可以优化**候选方案排序、工具选择、上下文投影策略、错误分类、
修复建议排序、成本与输出预算、用户偏好**；不可由奖励函数决定**哪个估计器正确、
哪个模型假设成立、哪个数字可信、是否可以忽略诊断**。

一句话：**学习系统可以优化"提议得是否更好"，不能替代验证器决定"数字是否成立"。**
