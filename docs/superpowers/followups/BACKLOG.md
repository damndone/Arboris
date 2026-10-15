# BACKLOG — 当前唯一 live 滚动欠账清单

> 2026-07-15 从 `v1.6.9-followups.md` 改名（历次版本名误导已久）。文件名从此固定,
> 不再随版本改名;版本收尾冻结时复制快照进 `archive/followups/`,本文件继续滚动。
> 来源：v1.6.8 起各版评审/smoke 留痕,逐版滚动至今。
>
> **本文件 = 当前 live 的滚动 backlog**（约定见 `docs/superpowers/README.md`）：
> 所有还开着的债都收在这里，做完就删（git 历史留痕），下个版本起手时把
> 新债续在这里，直到某个版本收尾时才整份冻结进 `archive/`。
>
> **§1 是跨三份 canonical 文档（本文件 / `roadmap/architecture-debt.md` /
> `roadmap/2026-07-01-unified-graph-workbench-roadmap.md`）的扁平总索引**——
> 一处看全。架构债 / 主线只放 pointer 行，正文仍在各自文档就地更新。
> 本文件自有的债（P1/W/S/U/R）详情见 §2，已清留痕见 §3。

---

## 0.0 最新：v1.9.0 已发布（2026-10-14）

**v1.9.0 = 研究工作区重做 + Agent 增强**，已发布（main squash `402d2d3e`，tag `v1.9.0`）；**v1.8.13**（手动能力后端）同日单独发布（`c81fc89f`，未重跑 gate，说明里写明）。

- 发布说明：`docs/releases/v1.9.0-release-notes.md`、`docs/releases/v1.8.13-release-notes.md`；完成报告 `docs/releases/v1.9.0-completion.md`。
- 下一版开工交接：`handoffs/2026-10-15-next-version-kickoff.md`（候选、开工流程、坑）。
- 本文件 2026-10-15 快照：`archive/followups/BACKLOG-2026-10-15-v1.9.0-snapshot.md`。

### 0.0.1 v1.9.0 遗留（新增）

| ID | 级别 | 内容 | 现状 / 建议 |
|---|---|---|---|
| V190-OLS-HC3 | P | OLS 等线性族只有 HC1 稳健标准误，没有 HC0/HC2/HC3 | 补核心估计、结果信封、三语言脚本导出，并对 R/Stata 数值对照 |
| V190-COMPACT-SPLIT-TURN | W | 单个回合本身超过窗口且之前无可切分提问时无法压缩 | 参照 pi 拆分回合、两段摘要合并 |
| V190-AGENT-STEER-UI | U | core 已有 steer/follow_up 队列，界面未接；无执行计划显示 | 接入界面 |
| V190-REPORT-DRAFT-SIZE | W | 手写报告草稿接口一次 736 kB（证据重复来源） | 改数据格式时一并处理 |

## 0.0（旧）v1.8.12 已发布（2026-10-08）

**v1.8.12 = 基础加固**，**已发布**（2026-10-08，main squash `91550d73`，tag `v1.8.12`）：

- 发布说明：`docs/releases/v1.8.12-release-notes.md`；GitHub Release 已建。
- gate 日志：`evaluations/gate/2026-10-08-v1.8.12-gate.log`。
- 自审与发布验收：`evaluations/2026-10-08-v1.8.12-self-review.md`。
- 立项 8 步全部交付（第 8 步按用户决定只做项名引号）；完成项见 §3 留痕。
- 发布时修复共享虚拟环境：editable 安装指向主仓库，加 checkout 守护与 gate 检查。

**下一步：v1.9.0 界面重做与 v1.8.13 后端并行**（用户 2026-10-08 认可）：

- 两条线都从 tag `v1.8.12` 开始，即 ADR-PD-001 的合同锁：HTTP 接口与生成的前端类型。
- v1.8.13 改接口须单独提交新合同并重新生成类型，界面线明确切换后再用。
- 开工交接：`handoffs/2026-10-08-v1.8.13-and-v1.9.0-kickoff.md`。

> v1.8.11 的逐提交历史含 Stata 许可证值，只保留在本机 `refs/private/v1.8.11-full-history`；`.git/hooks/pre-push` 拒绝推送。

### 0.3 延续项

| ID | 级别 | 内容 | 现状 / 建议 | 来源 |
|---|---|---|---|---|
| V1811-DARK-PANEL-CONTRAST | P | 深色主题的 ios-group 面板仍用固定白底，文字对比度不足；浅色/跟随系统浅色可读 | 原有问题，本轮未修改样式；发版前修复并浏览器验收，或保留本项且在发布说明列出限制 | 第 6 步①②审核；handoffs/2026-10-04-v1.8.11-step6-review-feedback.md；devline inherited_dark_result_panel_contrast |
| V1810-FOCUS-REMAINING | P | 方案、报告两种焦点已登记未接页面；空白画布的项目 Agent 仍只读；焦点标签未移到输入框上方 | 界面重做那一版 | 第 8 步 |
| V1810-KERNEL-CAP | D | 完整协方差上限从 500 降到 300 个参数（500 个约 4.8 MB > 2 MB 预算） | 需要更多参数时改为压缩存储或按需计算 | 第 1 步 |
| V1810-MI-COMBOS | P | 合并结果上的后估计（D1）；多重插补与抽样设计或按组执行同用 | 现在明确拒绝 | 第 5、7 步 |
| V1810-HAC-MORE | P | HAC 与聚类同用（Driscoll–Kraay）、其他族的 HAC | 现在明确拒绝 | 第 6 步 |
| V1810-SURVEY-NODE-HASH | 观察 | 抽样设计字段（含 `survey_df`）不进节点哈希表单，只进运行输入 | 增量缓存目前只用于插补恢复，暂无影响；扩大缓存前要补 | 自由度惯例实现时发现 |

### 0.4 v1.8.12 输入：v1.8.11 发版后自检（2026-10-07）

> 每一项的归属版本与完成标准：v1.8.12 时见 `archive/handoff/2026-10-07-v1.8.12-kickoff.md`；v1.8.13 起见 `handoffs/2026-10-08-v1.8.13-and-v1.9.0-kickoff.md`，以最新交接为准。

| ID | 级别 | 内容 | 现状 / 建议 | 来源 |
|---|---|---|---|---|
| V1812-SESSION-TOKEN | P1 | 本地 API 会话令牌（纵深防御） | 用户决定 v1.8.12 不做；后端改为非回环监听、打包发布或多用户时与 V1812-LINUX 同批做 | v1.8.12 objective 评审 |
| V1812-GRAPH-CONTROL-KINDS | P1 | 图谱操作面板对 column / integer / number / object / json 控件只读（有序/多项 logit、Cox、LMM、分位数回归、ARMA-GARCH、ETS 的这些参数需回运行表单改） | **用户 2026-10-08 确定随 v1.9.0 界面重做**补就地编辑；种类已由生成的 `ControlKind` 约束 | v1.8.12 第 4 步 GAP |
| V1812-TYPES-FOLLOWUPS | P3 | ARMA-GARCH 变换 id 在 4 处重复；数据操作 `diff_ref` 各操作结构未声明；`notebook/contracts.ts` 解析后类型未与生成类型做编译期一致性断言 | 逐项收敛到单一来源 | v1.8.12 第 4 步 REVIEW |
| V1813-CLI-DATA-OPS | P2 | CLI 还没有数据操作子命令（subset、recode、merge、reshape 等） | v1.8.13：仿照 `postestimation` 从数据操作合同生成子命令，经同一数据操作服务执行 | v1.8.12 第 5 步 |
| V1813-GATE-LOCK-GLOBAL | P2 | gate 锁文件按目录名区分（`${TMPDIR}/workbench-gate-<目录名>.lock`），并行的两个工作目录可能同时跑 gate，曾出现内存到 40G | 改为整机唯一的锁；在此之前按交接文件人工错开 | 2026-10-08 写 v1.8.13 / v1.9.0 交接时发现 |
| V1812-NB1-R-EXPORT | P3 | NB1（常数离散）原生脚本导出只有 Stata / Python，R 保持 Workbench 结果侧车 | 需要 R 的参照级 NB1 实现，并先对 Stata `nbreg, dispersion(constant)` 验证；否则维持现状 | v1.8.12 第 5 步 |
| V1812-AGENT-GOD-FILES | P1 | 大文件转移到 Agent 层：`context_tools.py` 5445、`workflow_contracts.py` 4165、`notebook/service.py` 4129 行 | `context_tools` 按工具类别拆分转 v1.8.13 必做；模型族合同已在第 6 步分离（`workflow_contracts.py` 4165 → 3207 行） | v1.6.2 外部评价 #1 |
| V1812-FAMILY-LITERAL-DOWN | P2 | v1.8.12 第 7 步已从 165 降到 119（合同表声明移入 `contracts/model/` 26 处；Notebook 产物词表改由合同推导，真正去重 20 处）。剩余 119 处中 45 处是草稿节点 id（`model_1`、`table_1` 等），正则误计；真正的族名分支 74 处；`runner.py` 15 个 `run_*` 与估计阶段 14 个 `_fit_*` 仍与声明式模型包并存 | v1.8.13：先修正则（排除节点 id），按 74 重定基线，再每版定下降目标、逐步迁入模型包（`evaluations/2026-10-08-v1.8.12-family-literal-down.md`） | v1.6.2 外部评价 #2 |
| V1812-LINUX | P1 | 仅 macOS 验证；LMM 依赖 macOS 原生隔离 | 明确目标平台；Linux 隔离方案与 CI | 已知门槛 |
| V1811-LMM-REMAINING | P2 | LMM 的 ML 似然比检验与边际效应无对照；结果卡片只显示组 × 时间交互项；分类项名暴露公式原文 | 补对照后开放；卡片随 v1.9.0；项名映射为可读名（v1.8.13，用户 2026-10-08 确定） | v1.8.11 |
| V1811-SUITE-DURATION | P2 | 后端测试 18:39 / 预算 20:09，余量小；`honest_did` 纯计算约 95 s | gate 一律记录耗时；需要时优化 LP 求解 | 发版 gate |
| V1811-FRONTEND-CSS | P2 | 6 个全局 CSS 共 5471 行、139 处写死颜色（深色模式欠账根源）、931 处内联样式 | 随 v1.9.0：主题变量 + 组件级样式 | v1.6.2 外部评价 #4 |

---

## 0.0（旧）v1.8.9 状态与延后清单（2026-09-27）

> 本节是最新状态，覆盖下方 §0/§0.1 的旧结论（那两节记录到 v1.8.6/v1.8.7，未逐条清理）。

**v1.8.9 = 日常可用（重建版）**，**已发布**（2026-09-28，main `23c26072`，tag `v1.8.9`，
发布说明 `docs/releases/v1.8.9-release-notes.md`）。立项 `objectives/2026-09-25-v1.8.9-objective.md` 的 8 步全部交付；
另做了信任与易用性一轮、数字核对、手册（`docs/manual/`）、反脆弱测试。证据：`evaluations/2026-09-26-v1.8.9-trust-round.md`。
历史与存档（全部 worktree、残留文件、stash）：`docs/history/`。
Codex 的 v1.8.9 spec 与 11 份计划为“部分采纳”，每份文件顶部已标注去向。

### 0.2 v1.8.9 延后与未实现

优先级：**F** = 地基（加复杂模型之前先做），**P** = 对标 SPSS/Stata 日常能力，**E** = 扩展能力，**D** = 待用户决定。

| ID | 级别 | 内容 | 为什么延后 / 建议做法 | 来源 |
|---|---|---|---|---|
| V189-POSTEST-REGISTRY | F | 后估计扩到其余模型族：IV、面板、DID、混合效应、GLM（binomial/poisson/negbin）；之后有序、多项、负二项（nbreg） | v1.8.10 已对 OLS/logit/probit/Poisson 开放（按接口读推断核心，R 对照）；其余族的对照数据已由 Codex 工单 B 准备，见 §0.3 | v1.8.10 → v1.8.11 |
| V189-TYPED-STEP-BINDING | F | 工作流步骤输出统一类型化绑定、唯一 runtime admission | 目前只有 `produced_dataset` 与 `model_branches` 可跨恢复消费，已够用；随 RESULT-ENVELOPE 再评估 | Codex Workflow Truth Task 1/2A |
| V189-ORDER-BY | P | 依赖行序的操作显式带排序键（去重保留 first/last 加 `order_by`；滞后已由 `data.tsset` 定序）；导出增加“按变量排序” | 统计结果与行序无关，单独的“排序节点”价值低；Data View 已支持浏览排序 | objective 第 6 步 |
| V189-DATA-UI-GAPS | P | aggregate / lag / tsset 的界面入口；数据集级权重（WEIGHT BY）；批量重编码；面板里分组 summarize detail；Data View 单元格编辑（如做，须生成节点） | 目前这些只能经 Agent 或建模时指定 | Codex Data Consumer |
| V189-SURVEY-FAMILIES | P | 复杂抽样推广到有序、多项、负二项、Cox、分位数等 | 现仅 OLS/logit/probit/Poisson | v1.8.7 限制 |
| V189-SCRIPT-EXPORT | P | 可复现脚本导出（由血缘生成可重跑的脚本，对标 do-file / syntax） | 对 Stata 用户比新模型更实际；提前到 v1.8.11（用户 2026-10-04 决定） | 新 |
| V189-PUBLICATION-TABLES | P | 出版级表格 / Custom Tables 式可配置结果表 | 读结果信封；v1.8.10 信封已稳定，排期待定 | Codex P2/P3 |
| V189-CLASSIFICATION-ML | E | 分类 ML：先 logistic + random forest 两个 adapter，严格 CV、校准、模型比较、调参；再树模型/提升/神经网络、解释性 | 现仅回归预测（固定参数的 Lasso/Ridge/RF 回归）；计划 v1.8.11，按 Codex 计划精简 | Codex P1 Classification |
| V189-P2-FAMILIES | E | GEE/GLMM → Tobit/AFT/竞争风险 → SEM/CFA → RDD/动态面板 → 贝叶斯/空间回归/状态空间 | 均未实现（代码中已确认）；每个经 MODEL-ACCEPTANCE-KIT | Codex P2 |
| V189-QUANT | E | 量化研究与策略验证平台（Quant Research Pack，先做 Level 1 因子研究最小闭环） | 路线与前置依赖见 `roadmap/2026-09-27-quant-research-direction.md`；已定：个人研究者；数据先用 FRED/ALFRED + Ken French（免费），个股因子再接 EDGAR + 免费行情 | 用户 |
| V189-GRAPH-SCALE | F | 图的可扩展：集合节点（ExperimentSet/FactorSet/ParameterSweep）、trial 晋升制、有界投影 API（分页、单视图上限、`VIEW_TOO_LARGE`）、折叠与聚焦 | `GET /graph` 现一次返回全项目森林；影响持久化模型，需先于大规模参数搜索 | Quant 设计 |
| V189-AGENT-COMPILER-IR | E | Plan IR / PortType / 两阶段发现 | 不采纳；仅当组合错误在真机评测中复现时重评 | Codex Agent Compiler |
| V189-AUTO-TESTS-DISCLOSURE | D | 每次 run 自动计算的证据矩阵检验（t、卡方、相关…）目前不计入“分析路径”的检验数 | 要不要计入，是披露口径问题 | 新 |
| V189-LOCAL-MODEL | D | 离线本地模型：作为服务商选项（Ollama/LM Studio），不打包、不分流；上线前用评测脚本测成功率 | 等用户定方向 | 用户 |
| V189-MODEL-LIST-AUTODETECT | D | 服务商模型列表自动刷新（后端已有 `/llm/providers/{id}/models/refresh`），保留手填；去掉写死的版本名 | 等用户定方向 | 用户 |
| V189-PROVIDER-FAILOVER | D | 主服务商连续失败时切备用服务商（需用户显式开启：数据会发往另一家） | 等用户定方向 | 新 |
| V189-EVIDENCE-TRUST-TESTS | P | 结果防伪造测试：按现行可信边界验证来源（服务端身份/来源/摘要），而不是“所有旧结果不可显示” | Codex 8/19 的两份测试（`archive/stash/b065b0bd-…`）只凭 mock 名字判断，且与 v1.8.9 的展示行为冲突，不恢复原断言 | Codex 核查 |
| V189-CLASSIFICATION-SEARCH-REF | E | v1.8.11 分类 ML 参考 Codex 的分类搜索 objective（OOF 选择、holdout 封存、预算与参数校验） | 在 `archive/leftovers/main-codex-v1.8.9-program` 的 `docs/superpowers/objectives/2026-08-21-v1.8.9-classification-search-objective.md`；实现在 `archive/v1.8.9-codex-wip` | Codex 核查 |
| V189-V173-HARNESS-REF | 参考 | v1.7.3 评测 collector / strict runner 的 6 处未提交加固（selector 失败清理、隐藏 index flag 检查、fork/execve 防护、冻结执行器缺失拒绝启动） | `archive/leftovers/v173-evaluation-harness`；该 collector 当时处于阻塞状态，不直接并入 | Codex 核查 |
| V189-LIVE-EVAL-FULL | ✅ | 全量真机评测（32 条 × 3）88/96，失败例重跑 24/24；反脆弱轮见评测文档 | 2026-09-27/28 完成 | 新 |
| V189-AGENT-TURN-BUDGET | 观察 | Agent 单轮 120 s 上限与慢服务商 + 重试的关系 | 流静默已限 30 s；若仍常超时再调预算 | 新 |

## 0. 一句话结论

**v1.8.6 已 SHIPPED**（2026-08-04，tag `v1.8.6`，`origin/main`=`9d5e947`）。
本版是 Predictive Research 正确性基础 + 四个新模型族 + 统计检验补完 + 报告审阅工作区；
发布说明见 `docs/releases/v1.8.6-release-notes.md`。

**下一版 v1.8.7 = 复杂抽样设计（引擎优先）+ 测量级别声明**，2026-08-04 拍板，
设计见 `archive/specs/2026-08-04-v1.8.7-survey-design-and-measurement-level-design.md`。
单轴：对标 SPSS/Stata。核心是**引擎优先、族是声明**——设计方差引擎做一次，
模型族通过 `ModelFamilyContract` 一条声明接入，并拆掉两张枚举天花板
（「族 × 设计」支持表、`result_shape` 封闭枚举）。
产品定位（四层、提问/回答不对称、永久红线）见
`roadmap/2026-08-04-ai-native-vs-spss-stata-positioning.md`。

北极星不是"更自主的 Agent"，而是**认知自主性高、操作自主性分级**：
理解/检查/设计/生成备选可以高度自主；改图、装依赖、跑新算法、产出正式数值
必须走 typed → validate → confirm → execute → verify → commit。

> 三条系统不变量（roadmap §1，任何版本不得违反）：
> 没有类型的内容可以解释、不能执行；没有验证的实现可以实验、不能产出正式数字；
> 没有 lineage 的结果可以预览、不能成为 Workbench 结论。

> NL proposal 当前只开放 `data.columns.cast`；单列 `data.column.cast` 与 `code.execute` 保持 NL 关闭。
> P-SBX2、P-CE1 和 honest-DiD 性能优化仍是独立后续债。

> NL proposal 当前只开放 `data.columns.cast`；单列 `data.column.cast` 与 `code.execute` 保持 NL 关闭。
> P-SBX2、P-CE1 和 honest-DiD 性能优化仍是独立后续债，不自动并入 v1.7.3。

## 0.1 当前版本状态（2026-08-04）

- v1.7.1：已发布。
- v1.7.2：已发布，PR #24 已合并，tag 与 `origin/main` 指向 `4b2e6c1`。
- v1.7.3：本机版本已在 Integration 提交 `730ebfc` 收尾；Report/Operations 与 LMM 已完成，正式 release PR/merge/tag
  采用唯一 Integration 分支；本机性能烟测取代未落地的 C2 collector。公共部署/App/插件安全留到出现对应信任边界时重新立项。
- v1.8.0：**已发布**（2026-07-22，PR #26，`origin/main`=`63f2fa1`，tag `v1.8.0`）。ARMA–GARCH
  时间序列工作台。交付层阻塞（原 `V1.8-DELIVERY-TRUTH`）已在发版前修复并独立验收，详见 §3。
  联合含 MA 的 ARCH/GARCH MLE 仍不属于本版，按 `V1.8-JOINT-ARMA-GARCH-MLE` 单独立项；
  当前一律 `REFERENCE_SEMANTICS = "directional_or_workflow_regression"`，不得称为 Stata 数值复现。
- v1.8.1：**已发布**（tag `v1.8.1`）。Agent Notebook + 选中文本交互。
- v1.8.2：**已发布**（2026-07-25，PR #29，`origin/main`=`ef38ece`，tag `v1.8.2`）。
  Raw 节点统计探索 + Agent 自主编排多步工作流；删除 class3 preset 并加防复发闸门。
- v1.8.3 / v1.8.4 / v1.8.5：**已发布**（tag 同名）。v1.8.4 = Agent Model Composition；
  v1.8.5 = 分级 typed memory + `ModelFamilyContract`。v1.8.4 遗留见 §1 表
  `V1.8.4-OPEN` / `V1.8.4-TIMER-EVIDENCE`。
- v1.8.6：**已发布**（2026-08-04，`origin/main`=`9d5e947`，tag `v1.8.6`）。
  Predictive Research 正确性基础（SplitPlan / holdout 隔离 / 负对照 / 泄漏诱饵）、
  四个新模型族（ordinal / multinomial / survival_cox / quantile）、统计检验补完、
  三种权重语义显式化、FeatureRecipe 与数据操作、变量与值标签、报告审阅工作区。
  本版开放欠账见 §1 表 `V1.8.6-*` 五条。
- v1.8.7：**进行中**。复杂抽样设计（引擎优先）+ 测量级别声明。见 §0 与
  `archive/specs/2026-08-04-v1.8.7-survey-design-and-measurement-level-design.md`。

---

## 1. 债务扁平优先级总表（跨三文档索引，一处看全）

> 「详情」列：`§2-x` = 本文件下方展开；`arch:Dn` = `roadmap/architecture-debt.md`；
> `roadmap` = `roadmap/2026-07-01-unified-graph-workbench-roadmap.md`；`roadmap G*` = `roadmap/2026-07-15-graph-scale-artifact-ai-terminal-directions.md`；
> `handoff §5.x` = archived `archive/handoff/v1.6.8-graph-native-genesis-handoff.md`。
> 「阻塞」= 是否阻塞用户正常使用（非验收阻塞）。

| 优先级 | ID | 债务（一句话） | 类别 | 修法 / 下一步 | 阻塞 | 详情 |
|---|---|---|---|---|---|---|
| 🟢 已收口 | V1.7.3-R | Report/Operations：真实 DeepSeek、8 图展开/导出、39 cite chips、timeout regression 已完成 | 独立版本工作包 | 保留既有完成证据；不重复运行真实 provider | 否 | `archive/plans/2026-07-18-v1.7.3-report-ops-closeout.md` |
| 🟢 已收口 | V1.7.3-LMM-LOCAL | 本机 LMM/Agent/UI：显式 local_contained、真实 Seatbelt canary、已知真值 HTTP/浏览器流程和导出 | 独立版本工作包 | 完整 gate 与精确产品提交证据写入 release ledger | 否 | `release-trains/v1.7.3/release-ledger.json` |
| 🔵 事件触发 | C2-HOSTILE-EXTENSIONS | 敌对插件、第三方模型包或外部候选代码的冻结执行与独立认证 | 长期安全边界 | 只有产品出现对应信任边界时，从新威胁模型和目标宿主重新立项 | 否 | `roadmap/architecture-debt.md#d7-敌对扩展第三方模型包的冻结执行边界未来需求当前不实现` |
| 🟢 下一版本 | V1.8-TS-C1 | Time Series Diagnostics：先锁 Facts/Assessment/Advisory 合同、统一“结论不充分”与条件化建议；不注册运行时能力 | 合同冲刺 | C1 锁定后再从同一提交并行创建 Pack、Agent、UI、Evaluation；预测另列后续工作包 | 否 | `archive/plans/2026-07-19-time-series-diagnostics-c1-contract-lock-plan.md` |
| 🟢 主线 | V1.8.1-NOTEBOOK | Agent Notebook（Graph 的叙事视图）+ 选中文本四类操作；备选方案存为带上下文指纹的 typed proposal，不预建空分支 | 主线 | 见 `archive/specs/2026-07-22-v1.8.1-agent-notebook-analysis-option.md` | 否 | roadmap §2 |
| 🟡 横向基础 | V1.8.2-EVAL | 评测工装：已知真值、参考实现对照、错误注入、lineage 检查、结论忠实度、proposal replay | 测试基建 | **必须照"实现与测试合谋"这一失败模式设计**：fixture 一律从真实持久化响应提取，禁止手写；replay 之外须含真 provider 探索性运行 | 否 | roadmap §3 |
| 🟡 后续模型核心 | V1.8.2-JOINT-ARMA-GARCH-MLE | 含 MA 的 ARMA(p,q)-ARCH/GARCH 目前顺序估计，无法对齐 Stata 联合条件 MLE 与联合 IC。**但联合估计只在联合设定正确时更有效**；设定有误时误差会沿似然传遍所有参数，顺序估计反而更稳健（有限信息 vs 全信息） | 独立估计核心 | 冻结版本化 Stata oracle 做 parity；**同时交付 typed recommendation**（当前建议/原因/升级条件/预期收益/额外风险），由 Agent 依方差诊断给出建议而非直接切换估计器 | 否（若不宣称数值复现） | §2-V1.8.2-JOINT-ARMA-GARCH-MLE |
| 🟡 基础设施 | ARTIFACT-SCHEMA-REGISTRY | artifact 不声明 payload 符合哪个 schema 版本（`register_artifact` 只有 `artifact_id`/`artifact_type`/`step`）。v1.8.1 已按 DEC-ART-001 明确排除，**不得声称已校验** | 契约基建 | schema registry + 命名版本规则 + producer 声明 + validator + 兼容性判定 + 旧 artifact 迁移 + 消费者版本协商；表格/模型对象/图形元数据 payload 规则各异 | 否 | spec §5、DEC-ART-FUTURE-001 |
| 🔵 待立项 | V1.8.3-CAPABILITY-EXT | Agent 提议扩展能力（依赖或自研）；**运行时禁止任意安装**。缺一层判据：无 oracle 时如何验证 | 能力扩展 | 分层判据：有 oracle→逐元素对照；无 oracle 但有可推导性质→性质/模拟回收检验；两者皆无→**只能停在 experimental，永不升 verified**。⛔ **被 `ARTIFACT-SCHEMA-REGISTRY` 阻塞晋升 verified**：只知道"它产出一个 table"不足以信任外部 Adapter 的产物 | 否 | roadmap §4 |
| ✅ 已完成 | V1.8.5-TYPED-MEMORY | 分级 typed memory（`project_domain_fact`、`apply_mode`、`vocabulary_version`、`verifier`、`last_validated_at`）+ 模型族契约（`ModelFamilyContract`，workflow-executable 扩到 cs_did/sa_did/dcdh）。**原标 v1.8.4，2026-07-31 改标**——实际 v1.8.4 是 Agent Model Composition，版本号被复用 | Agent 记忆 / 工作流 | 本机实现、Settings 管理、Notebook registry/admission、独立 GLM/IV/2SLS/TWFE DID 与 memory default 浏览器证据、4398/8/1 full-suite 证据已完成；外部部署 signer/scanner、ML/量化和六层检索链不在本版 | 否 | `archive/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md` |
| 🟠 本版遗留 | V1.8.4-OPEN | v1.8.4 仅剩 **2 条** open：`notebook_load_not_found`（legacy fixture 走加载/编译路径未复现原故障）、`chain_agent_proposal_upstream_error`（provider 上游故障未取得可归因复现）。2026-07-31 重开的 6 条已完成第二轮核验：5 条核实为 baseline `6607c2d` 已满足（带 commit:file:line 引用），`proposal_ready_budget_terminal_error` 原诊断不复现，记 not_applicable；**均不计为 v1.8.4 交付**。 | Agent/Notebook | 两条都不猜根因：legacy 需可确定性复现的 fixture，provider 需可观测的复现窗口 | 否 | `.agent/devlines/v1-8-4-reopened-incident-truth/events.jsonl` |
| 🟠 本版遗留 | V1.8.4-TIMER-EVIDENCE | 规划计时器跨组件重挂的修复仍只有确定性测试证据，无真机复现（需在真实规划调用进行中触发重挂） | 验收证据 | 下次真机 Notebook 验收时顺手构造一次重挂；不要补写为已验收 | 否 | `docs/superpowers/archive/handoff/2026-07-30-v1.8.4-remediation-handoff.md` §未完成 |
| 🟢 v1.8.7 在做 | V1.8.6-SVY-DESIGN | `sampling_weight` fail-closed，`strata`/`PSU` 只存在于错误信息里。复杂抽样调查数据（CGSS/CFPS/CHARLS/NHANES）得不到正确方差估计。**且现有错误信息建议用 `entity_col + covariance=clustered` 代替，这个建议本身是错的**（聚类稳健 SE 忽略分层带来的方差缩减、无设计自由度） | 统计正确性 | v1.8.7 A1：设计方差引擎（Taylor + 重复权重）+ 族按声明接入 | 是（对该类数据） | `archive/specs/2026-08-04-v1.8.7-survey-design-and-measurement-level-design.md` |
| 🟢 v1.8.7 在做 | V1.8.6-ORDINAL-ROUTING | 整数编码量表（李克特 1–4）被判为计数型静默路由到 Poisson；`YKind.ORDINAL` 仅由 ordered Categorical 产生。用户看不出来 | 路由/元数据 | v1.8.7 A2：测量级别声明 + 未声明时显式 advisory + Agent 批量提议。**不改自动路由**（区别在测量方式不在数值，自动跳只会换一批受害者） | 否 | 同上 |
| 🟢 v1.8.7 在做 | V1.8.6-FAMILY-ORACLE | `ordinal_logit` / `multinomial_logit` / `quantile_regression` 仅内部一致性——复核用的 statsmodels 正是执行引擎，等于自己批自己的卷子。`survival_cox` 已对 R 验证但 R 数值硬编码在测试里，无可重跑生成脚本 | 验证等级 | v1.8.7 A3：五个 `.R` 生成脚本 + fixture + 逐位对照，照 `tests/fixtures/{cs_did,dcdh,sa_did,honest_did}/generate_oracle.R` 范式 | 否 | 同上 |
| 🟠 v1.8.8 | V1.8.6-COLUMN-LOOKAHEAD | **列级前视无法检测**。无 availability/provenance 声明时系统判断不了某列是否偷看未来；时序标成 IID 时一个显式未来位移特征可跑出 r²>0.9 而不被拦。`AvailabilitySpecV1` 字段已在，但唯一构造点 `prediction.py:147` 把 `kind`/`validation_status` 硬编码为 `declared`，无列级信息、无校验 | 静默正确性 | 填空不是重建：补生产者与校验；`test_future_shift_leakage_decoy_v186.py` 现钉为已知行为，落地后应收紧为拒绝 | 否 | v1.8.7 设计 §5 明确顺延 |
| 🟡 长期 | V1.8.6-SCOPE-LIMITS | 三条本版未交付项：外部格式（`.dta`/`.sav`）标签自动保留不宣称；数据节点模型桥接只启动数值 OLS；temporal/panel prediction 实际执行未做 | 范围 | 各自按需求单独立项，不打包 | 否 | `docs/releases/v1.8.6-release-notes.md` 已知限制 |
| 🟡 测试 | N2 | 预存 slot-leak race:`test_run_inputs_persisted` 发 run 不等完成 → EventManager 单例 slot 泄漏，反字母序运行会 429 污染后续 run 测试 | 测试卫生（预存，v1.6.10 发现） | 测试收尾 join/await run 或按测试隔离 slot（字母序下不触发，故 gate 一直绿；非回归） | 否 | §2-N2 |
| 🟡 工程 | W1 | draft-execute dedupe 响应 `produced_lineage` 与 fresh execute 不同形 | 后端协议 | 统一响应形状 | 否 | §2-W1 |
| 🟡 工程 | W2 | 全量孤儿 upload/draft GC（项目级后台回收未做） | 后端 | 单独设计 GC；本版只回收 discard 创世链的无引用 upload | 否 | §2-W2 |
| 🟡 同族 | S1 | genesis 全流程 / Playwright smoke 层未建（只有单测 + fake-timer） | 测试 | 建 e2e smoke 层 | 否 | §2-S1 |
| 🟡 同族 | S2 | 全模型族 FE 真机执行 smoke 剩 `panel_ols`/`cs_did`/`sa_did`/`dcdh`/prediction | 测试 | 真数据肉眼确认 5 家族 Genesis 全流程 + drawer 估计方程渲染 | 否 | §2-S2 |
| 🟡 同族 | S3 | 并发 draft-execute 单槽搁浅（`pendingRerunRun` 单槽，B execute 覆盖 A） | 前端状态 | 按 draftId 键控 pending 集合（无数据丢失，reload 可 rehydrate） | 否 | §2-S3 |
| 🟡 同族 | S4 | forest refetch 卸载整树 → loading 闪烁 + rail 每 30s 重拉 `/runs` | 前端 | stale-while-revalidate（refetch 保留旧 forest） | 否 | §2-S4 |
| 🟡 同族 | S5 | `handleRerun`（顶栏 context rerun）focus 4s 残留 | 前端 | 复用 draft 的 usePendingRun 思路（无 draft 中心） | 否（低优） | §2-S5 |
| 🟡 同族 | S6 | `WorkbenchRouteContainer` Escape/modal 预存 flake（观测 1/10） | 测试 flake | 查独立根因（与 useCapabilities flake 无关） | 否 | §2-S6 |
| 🔵 拍板 | U1 | drawer 元信息裸机器串（`runId·64hex·owner_resolution` 枚举） | UX 拍板 | 人类可读文案 + tooltip/copy 保机器串；连同 v1.6.2 验收意图改 | 否 | §2-U1 |
| 🔵 拍板 | U2 | role 缩写 `X` 二义（`focal` 与 `explanatory_unspecified` 都显示 X） | UX 拍板 | 新呈现方案（淡色/斜体 X），仅 tooltip 可区分现状 | 否 | §2-U2 |
| 🔵 指针 | R1 | Variables 面板规模化（搜索 / 虚拟列表 / role tabs） | 前端规模化 | 规模化时再动 | 否 | handoff §5.3 |
| 🔵 指针 | R2 | Browse 产品边界 / workspace root / 项目注册表 | 产品 | 见 §4 范围外 | 否 | handoff §5.1 |
| 🔵 指针 | R3 | schema-driven `modelParams()` | 前端 | 用 schema 驱动替手写 | 否 | handoff §5.2 |
| 🟠 架构 | A-D2 | GLM 6 家族（ols/logit/probit/poisson/negbin/glm）该收敛成策略+注册表 | 架构 | `GLM_FAMILIES` 注册表；DID 家族维持异构；golden 23 护栏钉数值 | 否 | arch:D2 |
| 🟠 架构 | A-D6 | 无 OpenAPI codegen，api.ts 44 手写 type 迟早漂移 | 架构 | `openapi-typescript` 从 `/openapi.json` 生成 | 否 | arch:D6 |
| 🟠 架构 | A-D4 | 全局 CSS 1053 行（低，churn>收益） | 架构 | 不专门立项；新组件用 CSS Modules 渐进 | 否 | arch:D4 |
| 🟠 复盘 | A-D5 | lineage 复查（**非债**，每版一次"抽象是否挣钱"复盘） | 复盘 | 用户拍板；与 roadmap 北极星一致（有意复杂度投资） | 否 | arch:D5 |
| 🔵 AI | V7 | 超大数据集 Ask AI 策略:profile 摘要已防爆(不随行数涨),但宽表/用户想深入时不够（反馈批3） | 设计 | ①列分块/top-K 列(按缺失率·方差·与y相关)②抽样预览(head+分层随机,标"样本")③v1.7 工具式 drill-down:AI 按需向后端取单列直方图/分位数,上下文只装摘要 | 否 | — |
| 🟢 主线 | V11 | 图内数据层（✅ v1.7 第一典型切片完成）:`data.column.cast`/`data.columns.cast` 已落(typed preview/confirm/immutable child/幂等/failpoint/浏览器验收);cleaning 策略/异常值规则等更多 data operation 未做 | 主线=v1.8+ | 沿 data.column.cast 模式扩 operation 面 | 否 | roadmap |
| ~~🟢 方向~~ | ~~G1~~ | ~~图爆炸~~ **✅ v1.7.2**:batch `data.columns.cast`(N 列→1 record/1 child/1 recipe/1 diff)+ **投影层折叠**(`foldNodeClusters` 把 >3 个同源 data-cast 兄弟折成 "Data operations (N)" 卡,durable graph 一字不改) | — | — | — | — |
| ~~🟢 方向~~ | ~~G2~~ | ~~AI 解读图表~~ **✅ v1.7.2**:figure→chart_type+数值源 context/`/figures/ai-context`/chat figure mode/图库按钮、报告图表 marker 和导出；多模态真·看图仍是 provider-gated 可选方向 | — | — | — | — |
| ~~🟢 方向~~ | ~~G3~~ | ~~terminal 面板~~ **✅ 全闭(2026-07-16)**:输入框去重 + 沙箱 runner(8 条安全测试真验)+ **`code.execute` typed operation 全链路**(preview=沙箱真跑进一次性 temp 目录、项目零写入;execute 二次跑并**校验结果与 preview 逐字节一致**,不确定代码→拒写;同 key 幂等重放)+ registry(`risk_level=high`)+ orchestrator + routes(sandbox 缺失→503 fail-closed)+ UI section + 真机验收(四条边界对真实项目实测)+ **terminal 外观**(sandboxed stdout 进 AgentPanel;诚实:是跑完的捕获输出**不是实时流**,真流式要 SSE) | v1.7 | 已完成 | 否 | roadmap G3 |
| ~~🟢 主线~~ | ~~优先级 6~~ | ~~NL Agent 生成同一份 typed proposal~~ **✅ 真机闭环(2026-07-16)**:只开 `data.columns.cast`(**`code.execute` 保持 NL 关闭**)。模型只出意图,后端绑 `artifact_id`+preview fingerprint;新增只读 `inspect_data_schema`。有单独真机 smoke 记录，但不作为本版 gate 或系统级 E2E 承诺。**真机抓到 4 个确定性测试盖不住的 bug**(contract 不可读 / `casts` 被声明成 string / oneOf 与父级 AND 导致顶层强制 model.rerun 形状 / confirm 端点算错 fingerprint 身份) | v1.7 | 已完成 | 否 | roadmap 优先级 6 |
| ~~🟡 债~~ | ~~P6-1~~ | ~~失败只回 `invalid_tool_arguments`,不带校验详情~~ **✅ 已修(2026-07-16)**:`tools.py` 新增 `validation_details()`,`ToolResult.error_details` 进 tool payload(仅失败时出现,成功 payload 形状不变;`error` 码保持稳定)。**`oneOf` 用 `const` 判别式选分支,不用 `best_match`**——best_match 无判别式概念,曾把 model.rerun 的 `'node_hash' is a required property` 当成 cast 提议的建议:**给错建议比不给更糟**。plain schema 则保留全部顶层错误(一次说完,不要每轮只挤一条)。有界(5 条 / 240 字符,消息里嵌的是调用方自己的参数) | v1.7 | 已完成 | 否 | 本轮 |
| 🟡 债 | P-CE1 | `code.execute` 一次 confirm 用户代码跑 **5 遍**(route freshness + lifecycle prepare/execute preview + apply 确定性 run)。正确但昂贵,每遍 30s wall clock。**减到 2 遍**=把已算 preview 带 execution key 缓存、confirm 复用——但那 4 遍分散在 failpoint 崩溃恢复里(恢复进程不能信任已死进程传入的 preview),减少=重写崩溃恢复契约,高风险须单独立项 | v1.7+ | 缓存 preview 结果 by execution key;prepare/execute/apply 复用而非重跑;崩溃恢复时才重算 | 否 | 本轮实测 |
| ~~🟡 债~~ | ~~P-RISK1~~ | ~~`risk_level`(含 code.execute 的 `"high"`)曾是**纯装饰**~~ **✅ 已修(2026-07-17)**:高风险操作现在要求后端风险授权，授权绑定 proposal、fingerprint、active head、execution key，并一次性消费 | v1.7.1 | 已完成 | 否 | 独立 review；`tests/test_risk_policy.py` |
| ~~🟡 债~~ | ~~P-SBX1~~ | ~~B1 新增的 `tests/test_code_execute_recovery.py` 需要与兄弟沙箱测试一致的无后端 skip 守卫~~ **✅ 已清(2026-07-17)**:已补 `pytestmark = pytest.mark.skipif(isolation_backend() is None, ...)`；生产路径继续 fail-closed | v1.7.1 | 已完成 | 否 | 独立 review 实测 |
| 🟡 债 | P-SBX2 | `isolation_backend()` 只探测二进制存在，不验证后端是否真的可执行；受限工作区会把 exec 拒绝误报为可用，导致沙箱测试红或诱发错误的静默 skip | v1.7+ | 增加仅供测试使用、模块级缓存的 `sandbox_selftest()`；无后端可合法 skip，后端存在但不可用必须以醒目原因失败/可见 | 否 | 独立 review 实测；不得把不可用后端静默 skip |
| ~~🟡 债~~ | ~~N-COV~~ | ~~B2 翻转了 pin 路径的 fallback 测试后，默认路径“store 存在但 active provider 未配全仍回退环境”的行为需要单独钉住~~ **✅ 已清(2026-07-17)**:默认路径 fallback 已由 `test_default_path_falls_back_when_active_provider_is_unconfigured` 固定；pin 语义不变 | v1.7.1 | 已完成 | 否 | N-COV 独立验证 |
| 🟢 更远 | M2 | 画布拖放建链 | v1.7+ | 独立版本，不与图内操作混排 | — | §4 |
| 🟢 更远 | M3 | batch run (`y_list`) 图内化 | v1.7+ | 创世向导 v1 只做单 run | — | §4 |
| 🟢 更远 | M4 | 后端项目注册表 / 项目级设置页 | v1.7+ | Launcher 最近项目仍走前端 localStorage | — | §4 |
| 🟢 更远 | M5 | roadmap §3.5 的 W·C·A + Agent Harness | v1.7 | — | — | roadmap |
| 🟢 穿插 | M6 | 统计方法线未建大类:**机器学习**(RF/XGBoost/CV 框架/SHAP)·**降维聚类**(PCA/K-means/层次)·**高级时序**(VAR/VECM/协整/GARCH)·**生存分析**(KM/Cox PH/log-rank)。⚠️ 统计方法 roadmap §12 版本表是 2026-05-13 旧草稿(写"V1.7=DID"但 DID v1.5.x 已全 ship),版本号作废勿照排 | 统计方法(独立穿插线,低风险不阻塞) | 沿用 DID 模式:自实现+R oracle 验证+golden;每类单独排版本,与主线穿插 | 否 | roadmap §13 |

> **已清（v1.8.0，做完即删，git 历史留痕）**：🔴 **V1.8-DELIVERY-TRUTH**（ARMA–GARCH 交付层）
> — 五条完成条件全部有真机证据（run `20260722_043812_924307_874cc62b`）：报告单一事实源 +
> 新报告持久化为 `ai_report_<id>`；`tables.xlsx` **八表全非空**；Compare 人类摘要；
> Agent 聚合审计三格式。**独立验收推翻了它原本"已完成"的自述**：非空不等于可用——
> Rolling forecasts 只导出 18 列里的 2 列、Volatility candidates 一个候选都没有、
> Diagnostics 只有 ADF（漏掉产生验收警告的那些检验），根因是 exporter 与其 fixture
> 共用同一套猜错的列名。commit `ede19ff`。
> 另清 🔵 **U-COMPARE-INLINE**（内联 Compare 打印两坨 ~900 字符 JSON）— `nodeDiff.ts`
> 展平为叶子路径，commit `54a9879`；🔵 **U-AUDIT-HTML**（HTML 审计导出实为 markdown
> 塞进 `<pre>`，因为只测了 JSON/Markdown 载荷没测渲染）— commit `93f437d`。
>
> **已清（v1.6.11，做完即删，git 历史留痕）**：🔵 **U3**（covariance 默认值硬耦合）
> — 后端 `COVARIANCE_UI` robust 标 `default:True` + `_COVARIANCE_DEFAULT` 单源驱动 param value;
> 合约放行 `default:boolean`;前端 `covarianceDefault()` 读 flag（`[0]` 仅防御兜底）。commit `2a3eca5`。
> 随 v1.6.11 切片 B 折入（图内对比必碰 capabilities 展示契约）。
>
> **已清（v1.6.10，做完即删，git 历史留痕）**：🔴 **P1**（auto-mode draft 不可编辑）
> — `_validate_params` 跳过未变的继承参数（②根因修复,`6739f56`+`f56…`）,store 3 TDD + 端点
> 回归测试 + **真机 uvicorn smoke 复现**（covariance-only PATCH→200、model_type→bogus→422）;
> **A-D1**（api.py 万能垃圾桶）— 2206→32 facade,五层拆分（Phase1-4）。
> **v1.6.10.1**:**N1** — draft 执行编排下沉 `services/draft_service.py`,`drafts_routes` 819→485;
> **所有拆分文件 <500,D1 彻底收口**。
>
> **已清（v1.6.9）**：D3 CLI 补参数（`a914309`+`4d7759e`；架构债台账 v1.6.10 已同步标清）、
> `POST /runs`·`/runs/batch` 校验对称
> （`0c7a4c1`）、useCapabilities flake（`b95369f`）、429 flake 根因（`edd4f8d`）、dead RunHistory
> （`23719ba`）、REV-3 classifyError（`9c7f74d`+`820eb82`+`fc4ef0c`）、rerun-child 长 run 窗口期
> （`8ef74f0`+`06f36bb`+`23a3c2a`）、RUNS rail 及时刷新（`0eada74`）、WorkbenchRouteContainer 拆分
> （`25bc798`+`06619f7`，987→859）、裸 `global.fetch=` 卫生（`fe65cad`）、`did_mode` 值核查（全对）。

---

> **已清（v1.6.12,做完即删,git 历史留痕）**：🔵 **V1**(A3 逐 artifact Explain,`3b826d9`)、
> **V2**(A4 LLM 多供应商设置面板+Home 状态卡)、**V3**(typed `aiActivityLog`+底部 AI activity 面板,
> v1.7 diff 留痕契约打底,`dbdb0f2`)、**V5**(零依赖 markdown 渲染器,AskAI+Report 共用)、
> **V6**(per-node AskAI History)、**V8**(画布 Reset 键,`7d99d41`)、**V9**(折叠框,销案非 bug)、
> **V10**(Workbench Home 视图,`/?home=1` 兼容别名)、**V4**(legacy `/graph` 挂住,v1.6.12 closeout 修复)。
> 🟢 **M1**(图内对比/节点 AskAI/引用报告)已 SHIPPED v1.6.11;🟠 **A-D1**/🔵 **U3** 见上方各版已清块。

## 2. 本文件债务详情（按 ID）

### §2-N2 · 预存 slot-leak 测试污染 race（v1.6.10 发现,非回归）

`test_run_inputs_persisted` POST /runs 后**不轮询等待完成**就结束——后台 `_bg_run` 线程可能仍
持有 `EventManager` 单例 slot。若其后紧跟另一个 POST /runs 的测试（如 `test_graph_editable_
annotation`），第二个 POST 撞 429 → `.json()["run_id"]` KeyError。**pytest 字母序采集下
`test_graph_...`(g) 排在 `test_run_...`(r) 之前,不触发,故 full gate 一直绿**;仅在手动反序运行时
暴露。预存债（EventManager 单例本就如此,v1.6.10 D1 未改其逻辑,仅在验证时发现）。修法=测试收尾
join/await run,或按测试隔离 slot。

### §2-W1 · draft-execute dedupe 响应形状不对称

deduped 响应的 `produced_lineage` 与 fresh execute 不完全同形。本轮忠实保留 from-node 既有行为，未顺手改协议。

### §2-W2 · 全量孤儿 upload/draft GC

本版只做 discard 创世链时回收无引用 upload；项目级后台 GC 仍需单独设计。

### §2-S1 · genesis 全流程 / Playwright smoke 层未建

v1.6.9 已给 draft-execute 补了全 UI 驱动的 fake-timer 测试（成功/失败/长 run 三分支，`WorkbenchRouteContainer.test.tsx` "draft execute — index-wait" describe）；genesis wizard 全流程驱动仍只有单测层，Playwright smoke 层仍未建（见 archived handoff §5.5）。

### §2-S2 · 全模型族 FE 真机执行 smoke（含估计方程渲染）

v1.6.9 已用真数据跑过 CLI 路径的 `did`（two_by_two，ATT≈1.55）与 `iv_2sls`（≈1.49），销掉 CLI 半边；**剩 FE 半边**：`panel_ols`/`cs_did`/`sa_did`/`dcdh`/prediction 的「Genesis 全流程执行 + drawer 估计方程渲染」仍没有用真数据肉眼确认（`EstimatedEquationSection` 家族特判有单测钉住，端到端没跑）。= archived handoff §6.2 剩余部分。

### §2-S3 · 并发 draft-execute 单槽搁浅

`pendingRerunRun` 是单槽状态（沿袭 genesis 单例形状）。draft A execute 进入 index-wait（分钟级）期间 `draftBusy` 已复位，再 execute draft B 会覆盖 A 的 pending + focus ref → A 永久卡 "executing"（不移除、不聚焦、后端 draft 不删；无数据丢失，reload 可 rehydrate 后手动 discard）。修法=按 draftId 键控的 pending 集合。Task 7 评审确认，Important 但不阻塞。

### §2-S4 · forest refetch 卸载整个 shell 子树（loading 闪烁）

`useForestData.refetch()` 会 `setLoading(true)+setForest(null)`，容器 `if (loading||...) return <Loading/>` → 每次 30s 轮询/pending 轮询都整树 unmount+remount（rail 每次重挂重拉 `/runs`）。这掩盖了 rail 延迟、也是闪烁与浪费；修法=refetch 保留旧 forest（stale-while-revalidate）。Task 9 实现与评审双方独立确认。

### §2-S5 · `handleRerun`（顶栏 context rerun）focus 4s 残留

超长 run 下 `pendingFocusTarget` 20×200ms 耗尽后聚焦不落（无 draft 消失、无错数）。与 draft-execute 不同源（无 draft 中心可复用 usePendingRun），spec §7 已记，低优先。

### §2-S6 · `WorkbenchRouteContainer` Escape/modal 预存 flake

全量 vitest 偶发（观测 1/10）`S1: Escape with modal open closes only the modal` 红。与 useCapabilities flake 无关，独立根因未查。

### §2-U1 · drawer 元信息行裸机器串（需拍板）

DetailHeader 渲染 `{runId} · {nodeKey}`（森林下 nodeKey 是 64-hex hash，截成 `·…`）和裸 `owner_resolution` 枚举（`active_head_contains_node`）。这是 v1.6.2 NodeOperationContext 有意的调试可见性，有测试钉住；改法应是人类可读文案 + tooltip/copy 保留机器串，需要连同 v1.6.2 验收意图一起改。

### §2-U2 · role 缩写 `X` 二义（需拍板）

`focal` 和 `explanatory_unspecified` 现在都显示 `X`（v1.6.8 把 `X?` 改掉响应"看不出变量名"的抱怨），仅 tooltip 可区分。如果 unspecified 的视觉信号还重要，需要新的呈现方案（如淡色/斜体 X）。

---

## 3. 已清留痕（做完即删的历史，防重复排查）

> 保留一版可查阅，下次收尾整份冻结进 `archive/` 时一并带走。

- **v1.8.12 已完成并删除的项**（2026-10-07）：V1812-LOCAL-API-SECURITY（第 1 步，`c1ff9638`；Host 白名单 + 所有方法校验 Origin + 改状态拒 cross-site，GET 只读由枚举测试守住；会话令牌按用户决定未做，见 V1812-SESSION-TOKEN；证据 `evaluations/2026-10-07-v1.8.12-local-api-security.md`）；V1812-LOCAL-EVIDENCE-RETENTION（第 2 步：测试证据统一写 `local/test-evidence/<类别>/<运行>`，每类留最近 3 份，失败或 `WORKBENCH_KEEP_EVIDENCE=1` 的永不自动删；LMM 准入只在失败或显式要求时复制运行目录；`tests/evidence_retention.py`）。V1812-REPO-EVIDENCE-POLICY 与 V1812-PREPUSH-GUARD（第 3 步：证据存放规范写入 `docs/superpowers/README.md` 第 8 条；`scripts/repo_evidence_budget.py` 每版对比上一发布 tag：净增 ≤ 5 MiB、新增文件 ≤ 1000、单文件 ≤ 512 KiB、冻结评估目录不得新增；pre-push 护栏源文件 `scripts/git_hooks/pre-push` + 安装脚本 + 真实推送回归测试；`tests/eval_v1811/` 5 个既有失败已逐一核实为审查脚本过期，原位保留）V1812-OPENAPI-TYPES（第 4 步：133 个接口全部声明响应，128 个 JSON 中 127 个以真实响应严格校验；前端 API 函数返回手写服务端结构 66 → 0，由编译器级不变量测试守住；顺带修复 Frequencies 预览 422 等 10 处合同与实现不一致；证据 `evaluations/2026-10-08-v1.8.12-openapi-types.md`）。V1812-NODE-RERUN-FROM（2026-10-08：补齐 v1.6.3 规格的节点级重跑来源，冲突时失败关闭；顺带把 `run_inputs.rerun_from` 混用的三种形状分开，数据集桥接改为 `dataset_source`，修复重跑子运行脚本导出 422；`014c307d`、`d0a4abf3`，证据 `evaluations/2026-10-08-v1.8.12-rerun-provenance.md`）。V1812-NOTEBOOK-AUTHORIZE（2026-10-08 用户同意删除：客户端提交执行授权的 HTTP 入口不该存在，授权只由 `confirm-and-execute` 在服务端签发；服务方法保留，路由测试锁定入口不存在）。生成类型文件放行（用户 2026-10-08 批准，上限 1 MiB；放行清单失效条目会被报出）。V1812-CLI-FROM-CATALOG（第 5 步：`run` 由 `POST /runs` 字段表生成并经同一 `_submit_run` 提交，`postestimation <op>` 由步骤合同生成并经工作流引擎执行，另有 `export-script` / `export-targets` / `models`；顺带补 NB1 的 Stata / Python 原生导出；命令行 NB1 → Wald → 原生 Stata 包经 Stata 冷启动实跑通过；证据 `evaluations/2026-10-08-v1.8.12-cli-from-catalog.md`）。V1812-CONTRACT-LAYERING（第 6 步：族合同表与结果形状注册表移到 `contracts/model/`，`OperationValidationError` 移到 `contracts/common/errors.py`，JSONL 工具移到 `workbench/jsonl_store.py`；分层守卫 `tests/test_layering_guard.py` 静态扫描 13 个下层包与模块含函数内导入；顺带修复子进程测试导入的是共享虚拟环境指向的旧 worktree 代码；证据 `evaluations/2026-10-08-v1.8.12-contract-layering.md`）。V1812-FAMILY-LITERAL-DOWN 本版目标（第 7 步：165 → 119，余项见 §0.4 同名条目）。V1811-PUBLIC-TERM-QUOTE（第 8 步：`workbench/formula_terms.py` 统一项名引号与反转义，前后端 8 处手写解析改用它；修复 ANOVA 含引号列名拟合失败与外发脱敏漏认双引号形式（运行流水线会规范列名，属潜在缺陷）；证据 `evaluations/2026-10-08-v1.8.12-term-quote.md`）。
- **v1.8.11 已完成并删除的项**（2026-10-07）：V1810-FAMILY-ORACLES、V1810-PANEL-DID-KERNEL、V1810-NEGBIN、V1810-LMM-ORACLE（另改 GLS 口径并开放 wald/lincom/nlcom）、V1810-AGENT-FIT-THEN-TEST、V1810-PROVIDER-MODEL-NAMES；§2-V1.8.2-JOINT-ARMA-GARCH-MLE（联合 MLE 对 Stata `arch`，VIX 复现；ω 与原 Stata 的差为 Stata 停止精度，见发布说明）。
- **v1.8.10 已完成并删除的 §0.2 项**（2026-10-04）：V189-RESULT-ENVELOPE、V189-MODEL-ACCEPTANCE-KIT、V189-BY-GROUP、V189-HAC、V189-DATA-TAB-AGENT-SCOPE、V189-P7-TESTS-PORT、V189-MI-POOLING-E2E；V189-POSTEST-REGISTRY 已对 4 族完成，余下族保留在表中。
- **v1.6.9 前置清债**：见 §1 表末「已清」块。
- **v1.6.9 收尾卫生**：①6 个测试文件裸 `global.fetch=` 无恢复 → 统一 `vi.stubGlobal` + 只还原 fetch（`fe65cad`；注意 `vi.unstubAllGlobals()` 会连带清掉 setup 里一次性装的 ResizeObserver，故只还原 fetch）。②`did_mode` 值拼写核查 → UI 全对（DID `cohort/two_by_two/status`、CS `never/not_yet` 均正确），无需改；仅内部 `EstimatedEquationSection` 有个 `modelType.includes("twfe")` 的 OR 死分支（无 model_type 含 "twfe"，不给用户看、有家族测试钉着，不值得碰）。
- **REV-3**（v1.5.0 滚入）已于 v1.6.9 清（`9c7f74d` + forest 路径去重 `820eb82` + Safari "Load failed" `fc4ef0c`）——更早版本滚入的债至此全部清空。

---

## 4. v1.6.8/v1.6.9 明确范围外（对应 §1 表的 M2–M5 / R2）

- **画布拖放建链**（M2）：数据模型已支持无父创世链，但当前宿主是右侧向导，不做拖放 builder。
- **Submit 表单代码删除**：只摘除主导航和 Launcher 入口；`/submit` 保留给 Command Palette「快速 run（旧表单）」和 batch 兜底。
- **batch run (`y_list`) 图内化**（M3）：创世向导 v1 只做单 run。
- **后端项目注册表 / 项目级设置页**（M4，R2）：Launcher 最近项目仍走前端 localStorage；项目根仍是文件系统路径。
- **图内任选对比 / 节点 Ask AI / 引用报告**（M1）：已 SHIPPED v1.6.11。

---

## 5. 从更早版本滚入、仍未解决的债

> 整理 followups 时（2026-07-08）逐份核销：只有 v1.5.0 的 REV-3 曾滚入本 live backlog，
> **已于 v1.6.9 清掉**（见 §3）。更早版本滚入的债至此全部清空；其余更早 followups 已冻结进 `archive/`。

---

## 6. v1.8.8 P0 途中发现、不在本版范围的

- **`_persist_model_post_estimation_result` 里 `"model_artifact_id": "ols_1"` 是硬编码**
  （`backend/workbench/agent/workflow_runtime.py`）。非 OLS 族的 post-estimation 记录会写
  一个不存在的 artifact 名。它就在刚修正的 `source` 血缘块旁边，属于同一类「落盘记录
  声称的事实与实际不符」，但触发条件不同（换模型族而非换数据来源），故单列。
  发现于 v1.8.8 Task 4.6。

- **`exploration_fingerprint` 与 artifact 路径的碰撞面**：已在 Task 4.6 改为吃真实来源的
  sha，但 P3 引入 reshape/subset（改行、改值）后，需要复核同 spec 不同上游帧是否还有
  其他共享 key 的路径。见 P0 计划 Task 6 的范围补充。

- **`branches` payload 有与 `produced_dataset` 完全相同的 resume 缺陷**
  （`backend/workbench/agent/workflow_runtime.py`：`:1250` 发布，`:1332` 读取，
  `:1567`/`:1687`/`:1734` 三个 step 家族消费）。它不随 `WorkflowStepState` 持久化，
  所以上游 branch 生产者完成后一旦中断，resume 时 `previous[dep].payload` 是空的，
  报错是 `{step_id} must directly depend on a completed model branch: {branch_id}`
  ——把人送去查 `depends_on` 声明，而那里没有问题。

  与 v1.8.8 Task 5 修的是同一个病，但 `branches` 不是 `SUPPORTED_STEP_OUTPUTS` 成员、
  不在声明式 source 契约里，所以不在那个任务范围内。**它也没有 `payload["result"]`
  那样的 `_result_from_artifact_ids` 兜底**——那条路 resume 会降级读 artifact，
  `branches` 这条路直接骗人。

  ⚠️ **不要把「链式 resume 通了」读成「resume 全通了」。** 发现于 v1.8.8 Task 5 审查。
