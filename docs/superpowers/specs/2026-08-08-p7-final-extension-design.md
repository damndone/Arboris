# P7 最后一批统计扩展设计

## 状态与目标

- 状态：已获用户批准，进入实施前的正式留痕阶段。
- Worktree：`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8-p7-multivariate`
- 目标：完成非参数/稳健推断、GLM 扩展、模型诊断、空间统计、Matching 与 Synthetic Control 的独立统计内核；完成后冻结 P7，不再继续扩展统计菜单，转入 P1/P2 能力接入和 Agent 端到端验收。
- 非目标：不修改 Claude 当前的 P0/P1/P2、Agent、CapabilityContract、OperationRegistry、前端、既有 survey 数学内核、既有 DID/IV/OLS/LMM 实现，也不在本阶段注册自然语言入口。

## 为什么这一批是 P7 的最后一批

P7 是统计发动机层，不是 Agent 控制层。它负责把一个明确的 typed 统计请求变成有边界、有假设、有证据和有失败语义的结果；它不负责决定 Agent 怎样发现、提议、确认和执行这个能力。

当前 P7 已覆盖多元统计、时间序列、实验设计、生存、ROC、Meta-analysis、重抽样、缺失数据、GMM、多重比较和 survey replicate 适配。本批补齐五类高频但形状不同的统计能力后，继续增加菜单的边际收益将低于把已有能力接入 P1/P2、Agent、报告和浏览器的收益。因此本批完成后建立明确的冻结点。

## 统一设计原则

### 1. pack 是独立插件，不强迫所有方法使用同一输入形状

PCA 消费数值矩阵，McNemar 消费配对列联表，Meta-analysis 消费研究级效应量，Power Analysis 可以不消费数据集。新 pack 只共享可验证的边界语义，不强迫所有方法伪装成 `fit(frame, columns)`。

每个 pack 自己拥有：

- 版本化输入/结果 contract；
- 封闭 operation ID；
- 明确的缺失、权重、随机数和精度政策；
- 稳定的 rejected/failed reason code；
- `scope`、`assumptions`、`limitations`、`not_claimed` 元数据；
- bounded JSON-safe result 和 evidence digest；
- 独立 Oracle 与 adversarial tests。

### 2. “边际”和“局限性”必须是机器可读的

每个完成结果都必须携带结构化的适用范围，而不是只在文档里写一段解释：

```json
{
  "scope": {
    "estimand": "...",
    "input_semantics": "...",
    "assumptions": ["..."],
    "limitations": ["..."],
    "not_claimed": ["..."],
    "unsupported_extensions": ["..."]
  }
}
```

这些字段有长度、数量和字符串边界，不能注入原始数据、公式代码、文件路径或任意提示词。`not_claimed` 是安全边界的一部分：例如 Matching 不得把估计量自动描述成无条件因果事实，诊断检验不得把一个 p 值自动翻译成“模型有效/无效”。

当前共享契约对文本安全采用“明确形态拒绝、统计 prose 放行”的边界：常见本地根路径、盘符/UNC/home/相对路径、带路径语境的相对 token、文件扩展名路径、独立 import 语句、`exec`/`eval` 和整段公式形态会拒绝；`A/B`、`x/y`、`group/time`、`/api/v1`、`file:` 语义和概念性 `import` 说明可以通过。它是有明确测试样例的 bounded heuristic，不是对自然语言中所有路径拼写的完备分类器；后续新增形态必须补正反例，不能用宽泛的字符禁令解决误报。

### 3. 运行时不执行 R、shell 或 Agent 生成的代码

R、statsmodels 和直接公式只允许出现在测试 Oracle。运行时使用仓库已有 NumPy/pandas/SciPy/statsmodels；不安装新依赖，不接受 callback、公式字符串、import path 或表达式。

### 4. 明确拒绝比静默降级更重要

- exact 条件不满足时不能悄悄改成 exact；
- Hurdle 与 zero-inflated 不能根据数据自动二选一；
- 空间权重矩阵存在孤立节点时必须使用显式策略或拒绝；
- Matching 没有 common support 时不能继续计算 ATT；
- Synthetic Control donor pool 不可识别时不能伪造权重；
- 诊断计算失败时不能返回“看起来正常”的空结果。

## 五个 pack 的范围、边际与局限

### A. 非参数/稳健推断

初始 operation：

- `nonparametric.mann_whitney`
- `nonparametric.wilcoxon_signed_rank`
- `nonparametric.kruskal_wallis`
- `nonparametric.friedman`
- `nonparametric.spearman`
- `nonparametric.kendall`
- `nonparametric.robust_summary`

支持显式选择 exact/asymptotic/permutation 语义、ties/zero 处理策略、效应量和 bootstrap/permutation CI。`robust_summary` 只提供 median、MAD、trimmed mean、Winsorized mean 等描述/区间证据，不把稳健描述量自动当成结构模型的估计量。

边际：秩检验回答的是秩/分布位置或相关性问题，不等于均值差异；Kruskal–Wallis 显著后不自动宣称哪两组不同；Friedman 需要明确的区组/重复测量结构。

局限：小样本、ties、零差值、非独立观测、复杂 survey 设计、重复测量缺失模式均需要显式策略；不支持无声明的自动缺失值删除。

### B. GLM 扩展

初始 operation：

- `glm.zero_inflated_poisson`
- `glm.zero_inflated_negative_binomial`
- `glm.hurdle_poisson`
- `glm.hurdle_negative_binomial`
- `glm.beta`

Negative Binomial 本体已存在，本批只增加 zero-inflated、hurdle 和 beta outcome 的独立 contract/pack。Zero-inflated 使用计数过程与结构零过程的显式分解；Hurdle 使用零/非零两阶段；Beta regression 要求响应严格位于 `(0, 1)`，边界值不得静默变换。

边际：系数、均值、发生概率和零概率属于不同 estimand，结果必须逐项标明；不能只返回一张“系数表”让消费者误读。

局限：零值机制不是由零比例自动识别的；过度离散、边界值、分离、非收敛和极端线性预测必须 fail closed；本批不做自动模型比较和零膨胀模型选择。

### C. 模型诊断

初始 operation：

- `diagnostics.vif`
- `diagnostics.breusch_pagan`
- `diagnostics.white`
- `diagnostics.breusch_godfrey`
- `diagnostics.reset`
- `diagnostics.influence`

本批以显式 OLS design matrix/result 为主要输入，输出统计量、自由度、p 值、使用的残差/设计语义和限制。VIF 属于设计矩阵共线性证据；Breusch–Pagan/White 属于异方差检验；Breusch–Godfrey 属于残差序列相关检验；RESET 属于函数形式提示；Cook’s distance/DFBETAs 属于影响点证据。

边际：每个诊断只回答自己的统计问题，不能被 pack 自动合成为“模型通过/模型失败”，也不能仅凭 SE 大小差异推断存在异方差或序列相关。

局限：高维设计、奇异矩阵、自由度不足、非线性模型和 survey/cluster covariance 需要专门输入语义；本批不修改现有 econometrics diagnostics，不替换既有模型 runner。

### D. 空间统计

本批只做全局空间自相关诊断与置换推断：

- `spatial.moran_i`
- `spatial.geary_c`
- `spatial.getis_ord_g`

输入包括显式的有界空间权重矩阵/边列表、行标准化策略、孤立节点策略和置换计划。矩阵规模、边数、置换次数和输出大小都有硬上限；原始矩阵和原始行不进入公共结果。

边际：这些统计量描述空间相邻结构下的全局聚集/离散证据，不自动识别空间因果机制，不等于空间回归系数。

局限：权重矩阵定义决定 estimand；不同邻接规则不能直接比较；孤立节点、非连通图、重复边、负权重和矩阵方向不明确时必须显式处理或拒绝。本批暂不做 spatial lag/error regression、局部热点扫描或自动邻接矩阵学习。

### E. Matching / Synthetic Control

Matching 初始 operation：

- `matching.att`
- `matching.balance`

支持显式 treatment、outcome、covariates、propensity model、caliper、replacement、common-support 和 balance threshold。输出 ATT、匹配样本摘要、SMD/方差比等平衡证据；没有 common support 或平衡严重不足时，不输出无条件 ATT 结论。

Synthetic Control 初始 operation：

- `synthetic_control.fit`
- `synthetic_control.placebo`

支持显式 treated unit、donor pool、pre/post periods、非负和权重和为一的约束、pre-fit RMSE、post-treatment gap 和 placebo evidence。权重优化失败、pre-period 不可识别或 donor pool 不足时拒绝。

边际：两者都是设计假设下的因果估计工具。结果必须显示 estimand、识别假设、共同支持/预拟合质量和未检验的威胁；不把“匹配成功”或“pre-fit 很好”自动当成因果识别已经成立。

局限：未观测混杂、模型错设、极端 propensity、donor pool 污染、干预前趋势不匹配和 interference 都可能破坏解释；本批不修改既有 DID/事件研究/合成控制代码，也不自动选择最可信的设计。

## 与 P0/P1/P2 的关系

- P0 负责 workflow step 间的数据来源、依赖、指纹和 stale 拒绝；本批只提供可被未来 step adapter 消费的 typed pack。
- P1 负责把这些能力登记成 CapabilityContract 并声明可达路径；本批不修改 P1 文件。
- P2 负责检查每个能力是否真的可达、是否是明确豁免或真实缺口；本批不修改 P2 文件。
- P7 只生产可验证的统计内核和结果证据。完成后，P7 的“冻结”意味着内核边界稳定，不意味着 Agent 入口已经完成。

## 并行与审查策略

先顺序完成一个极小的 P7 extension metadata contract，统一 `scope`/`limitations`/`not_claimed` 的校验；之后五个 pack 使用互不重叠的 contract、pack 和 test 文件。

代码实现按 fresh subagent 逐任务交接，避免多个实现 agent 同时修改共享文件；Oracle 研究、只读保护路径审查和测试设计可以并行。每个任务都必须经过：

1. 红测确认缺口；
2. 最小实现；
3. focused tests；
4. external Oracle；
5. spec-compliance review；
6. code-quality review；
7. protected-path 和安全扫描。

## P7 冻结验收

冻结前必须满足：

- 五个 pack 都有 contract、engine、Oracle、adversarial tests 和边际/局限元数据；
- 运行时无 R/shell/eval/exec/import-path execution；
- 统一资源上限、NaN/Inf、退化和失败语义通过；
- 与已有 P7 及 survey/MI/resampling 回归全绿；
- Claude 的 P0/P1/P2、Agent、frontend、survey mathematics protected-path diff 为空；
- formal devline verify 通过；
- 生成 P7 freeze handoff，记录所有暂缓的空间回归、复杂 survey rank inference、Bayesian、自动模型选择和 Agent reachability；
- 不 merge、push、tag、release，除非用户另行授权。
