# Frozen Context Pack

Line: `v1-8-10`
Baseline SHA: `59b52231ec67ae5d9f8755cbdf3021639b7c3427`

## Objective
# v1.8.10 — 扩展地基

基线：main `a583ab7c`（v1.8.9 发布 `23c26072` + 文档、依赖声明与存档索引），加上本文件与设计文档的提交。
来源：`docs/superpowers/followups/BACKLOG.md` §0.2（每项有 ID）、
`docs/superpowers/roadmap/2026-09-27-quant-research-direction.md`、
Codex 核查原文 `docs/superpowers/archive/handoff/2026-09-28-codex-verification-request.md`。
设计依据：`docs/superpowers/specs/2026-09-30-composable-capabilities-and-research-workspace-design.md`（下称“设计文档”）§3–§4。
P7 来源代码：tag `archive/worktree/workbench-v1.8.8-p7-multivariate`（`0ef1110c`）。

## 一句话目标

把能力做成按“性质”声明、可以像积木一样组合、Agent 能用自然语言调用的形式。这样之后再加复杂模型（分类 ML、P2 模型族、Quant）时：

- 每个模型的结果都能被 Agent、报告、表格、Notebook 同样读到；
- 后估计和前提检查自动适用；
- 新模型必须带齐验证才能合入。

同时补上多重插补合并、Newey–West 标准误、按组分别执行三个日常缺口。

## 为什么先做地基

详见设计文档 §2。要点：结果里没有完整协方差矩阵，联合检验只能重新拟合；检查和后估计按模型族名字写死；结果读取有两套；实际运行发现四个检查缺陷（第 3 步）；P7 有 22 个对照测试没进 main；多重插补没有合并估计。

## 范围（按顺序交付，每步单独提交并验收）

| # | ID | 交付 | 验收场景（浏览器内真实操作，真实数据） |
|---|---|---|---|
| 0 | — | 文档整理：`docs/superpowers/specs/`（56 份）与 `plans/`（113 份）顶层已发版的文档，按 `docs/superpowers/README.md` 移入 `archive/specs/` 与 `archive/plans/`。先 `git grep` 引用并同步修改。本版的设计文档与计划留在顶层 | 无浏览器场景。验收：`git grep` 不再有指向旧路径的引用 |
| 1 | `V189-RESULT-ENVELOPE` | **结果信封 + 推断核心 + 集合信封**（设计文档 §3.2）。<br>① 每个结果带：参数向量、协方差矩阵（k ≤ 500 时全存，否则只存关注参数并写明限制）、参考分布与自由度、对数似然、`predict` 声明、估计样本指纹。<br>② 合并 `result_shapes` 与 `FAMILY_EVIDENCE_PROJECTIONS`，Agent / 报告 / 表格 / Notebook 从同一份声明读取。<br>③ 集合信封，供按组执行和多重插补使用。<br>④ 两条漂移测试：已登记能力没有信封声明就失败；消费者绕开信封按路径读取也失败。<br>⑤ 所有消费者统一使用同一套数字格式规则。现在报告页的证据表会显示 0.9928945017762245 这样的 16 位小数和 p = 0（2026-10-01 在现有界面里看到），应显示为 0.993 和 p &lt; 0.001 | 选中一个 Callaway–Sant'Anna 节点，问 Agent “整体 ATT 是多少、置信区间多少”：回答与结果面板一致；加入报告后报告里有 CS 结果段；Notebook 引用同一数字。另抽有序 logit、Cox 各做一次同样的场景 |
| 2 | `V189-POSTEST-REGISTRY` | **按接口做后估计**（设计文档 §3.3）：Wald、LR、lincom、nlcom、边际效应都读推断核心，不再重拟合。<br>① 推断规则：F(q, df) 还是 χ²(q) 按核心的声明决定；遇到稳健或聚类标准误、pweight、复杂抽样、估计样本不同时，LR 拒绝。<br>② “族 × 操作”要有 Stata 或 R 对照才开放。首批开放 OLS、logit、probit、Poisson 的全部操作；负二项、有序、多项尽量补上 Wald 与 lincom 的对照。<br>③ 去掉共享代码里的模型族字面量（`"ols_1"`、`model_family in (...)`），并加 lint 测试 | ① 选中 logit 节点，用中文问“x1 和 x2 联合显著吗”：返回 Wald χ²、自由度和 p 值，与 Stata `test` 一致。<br>② 再问“x1 的平均边际效应”：与 Stata `margins, dydx(x1)` 一致。<br>③ 对稳健标准误的模型请求 LR 检验：明确拒绝并说明原因。<br>④ 对没有对照的组合：回答“尚无对照数据，暂不开放”，而不是笼统的“不支持” |
| 3 | `V189-MODEL-ACCEPTANCE-KIT` | **准入套件 + 性质声明 + 检查库骨架**（设计文档 §3.7、§4）。<br>① 模型族声明性质与接口；检查、后估计、标准误、组合子按性质匹配，不按名字。<br>② 准入五项：声明、对照（R/Stata 对照数据，**或模拟数据参数找回**：偏差与覆盖率在蒙特卡洛误差以内）、信封、台账分类、真机评测用例。适用的检查自动推导。<br>③ 检查库：每项检查声明盲化等级、阈值（附出处）、状态和来源标签。先收拢已有检查，并修正四个缺陷：共线性改用 GVIF 并在设计矩阵上计算；新增完全拟合检查；分离检查改用线性规划判定并扩展到 probit 等二元、有序、多项结局；诊断摘要要反映检查结果。<br>④ 工具强度加上 104.7 门槛，低于它时自动附 Anderson–Rubin 区间（Lee 等, 2022）。<br>⑤ 现有 20 个族的缺口清单写入本文件末尾 | ① 在 `cross_section.csv` 上跑 `wage ~ education + experience`：结果标明“完全拟合”并不显示 p 值，共线性显示 VIF 75.7。<br>② 加入 `region` 后，GVIF 正常算出。<br>③ probit 在完全分离的数据上被标出。<br>④ IV 结果显示第一阶段 F，并在 F < 104.7 时附 Anderson–Rubin 区间。<br>⑤ 开发者验收：故意登记一个缺对照的假族，测试失败并指出缺哪一项 |
| 4 | `V189-P7-TESTS-PORT` | 按 Codex 核查的逐文件清单移植 22 个测试，另 3 个选择性提取：<br>`test_matching_contract.py` 适配新合同；`test_matching_oracle.py` 只取增量断言；`test_statistical_extensions.py` 去掉“没有 Agent 注册”这类过时预期。<br>保留 main 已改进的 matching、hurdle 实现和 survey 样本一致性修复。无条件 skip 的占位测试不计入。移植后暴露的真实缺陷逐个修复并记入 devline。补上的对照数据计入第 3 步的缺口清单 | 无浏览器场景。验收：移植的测试全部通过，或逐条说明去向（已修复 / 需要某个 R 包 / 记入 BACKLOG），不留静默 skip |
| 5 | `V189-MI-POOLING-E2E` | **多重插补组合子**（设计文档 §3.5），沿用 `replicate_combine.plan`。<br>① 流程：生成 m 份数据并记录 manifest → 每份分别拟合 → 按 Rubin 规则合并，小样本自由度用 Barnard–Rubin 调整，同时报告缺失信息比例和相对方差增量。<br>② 不显示单份数据的残差和 R²。<br>③ 只有提供推断核心的族才能参加；以下组合明确拒绝：与复杂抽样同时使用、插补不完整、在合并结果上做后估计（需要 D1，以后做）。<br>**作为独立功能单独评审**，不混进第 4 步 | ① 在有缺失值的真实数据上做 m = 5 的插补后跑 OLS：显示合并系数、Rubin 标准误、自由度与缺失信息比例，写明 m = 5；系数与标准误与 R `mice::pool` 一致。<br>② 在合并结果上请求联合检验：明确拒绝并说明原因 |
| 6 | `V189-HAC` | **HAC 标准误插件**（设计文档 §3.4）。<br>① Bartlett 核；滞后阶数可由用户指定，默认 ⌊4(T/100)^{2/9}⌋，结果里显示所用规则和值。<br>② 需要已声明的时间顺序；以下情况拒绝：有时间缺口、与聚类同时使用。<br>③ 首批只开放 OLS。<br>④ 对照要对齐三方默认值：Stata `newey`；R `sandwich::NeweyWest(prewhite = FALSE, adjust = TRUE)`；statsmodels 的校正选项 | ① 在时间序列数据上选 Newey–West、滞后 4：标准误与 Stata `newey, lag(4)` 一致。<br>② 用中文让 Agent “用 Newey-West 标准误重跑”：确认后生成新节点。<br>③ 未声明时间变量时：提示先设定 |
| 7 | `V189-BY-GROUP` | **按组执行组合子**（设计文档 §3.5）。<br>① 每个分析显式写“按 X 分组”，没有全局开关。<br>② 能力声明子集语义；复杂抽样一律走域估计（subpop），不对数据做子集。<br>③ 缺失的组值自成一组；样本不足的组标为“无法估计”并写明原因，最低样本量取自检查库。<br>④ 输出集合信封，各组并排。<br>⑤ **每个开放按组执行的能力都自动跑不变性测试**：组结果等于先筛选再单独运行的结果。<br>⑥ 各组的检验计入台账，提供跨组 Holm/BH 校正。<br>⑦ 组间差异检验 = 合并样本加完全交互项 + Wald（复用第 2 步）；Agent 说出组间差异之前必须引用这项检验，由数字核对扩展执行。<br>⑧ 默认最多 50 组。<br>⑨ 首批开放：描述统计、t 检验、卡方、相关、OLS、logit、probit、Poisson；其他能力声明子集语义并通过不变性测试后即可开放 | ① 用真实数据按一个 4 组变量分别跑 OLS：各组结果并排，样本量正确，与分别筛选后单独回归一致；报告披露的检验数随之增加。<br>② 用中文问 Agent “男女的回报一样吗”：给出交互项 Wald 检验，不凭并排的系数下结论。<br>③ 有抽样设计时按组执行：结果与 Stata `svy, subpop()` 一致 |
| 8 | `V189-DATA-TAB-AGENT-SCOPE` | **焦点上下文**（设计文档 §8.4）。<br>① 用 `FocusRef`（类型 + id）表示焦点，由上下文提供者注册表解析，焦点类型可以是数据集、节点、方案、报告。<br>② Agent 的作用范围跟随焦点，不为每个页面各配一个 Agent。<br>③ Data 页的提问作用于正在查看的数据集，确认规则不变。<br>这也是之后界面重做里“只有一个 Agent”的地基 | ① 在 Data 页查看数据集 X 时问“对 wage 做描述统计”：在 X 的节点上直接运行（只读）。<br>② 改成选中模型节点后再问：作用于该节点。<br>③ 全程不再出现“只读的项目级 Agent 无法运行分析”这条死路。<br>④ 在图上选中 `iv_2sls` 节点时，Agent 显示的作用对象就是该节点。现在显示的是当前版本的头节点 `ols_robust`（2026-10-01 在现有界面里看到） |

## 不在本版

- **界面重做**：布局 A/B、只有一个 Agent 列、选中即问、地图列、时间线条。设计图已出，用户选定后另立一版（设计文档 §10 提议为 v1.9.0）。本版需要新界面的地方只做最小可用，例如按组结果的并排表，避免重做时推倒。
- **研究规划重做**：方案对比、推荐时看不到结果、预先设定与探索性、问题变更（设计文档 §5–§7，提议为 v1.9.1）。
- `V189-SCRIPT-EXPORT`（可复现脚本导出）、`V189-PUBLICATION-TABLES`（出版级表格）：两者都读结果信封，等本版信封稳定之后再做（提议为 v1.9.2）。
- 多重插补合并结果上的后估计（D1 统计量）、HAC 与聚类同时使用（Driscoll–Kraay）、其余模型族的 HAC。
- 分类 ML、P2 模型族、Quant Pack、图的可扩展（`V189-GRAPH-SCALE`）；BACKLOG 中标 D 的待决项。

## 硬约束

- **正确性**：统计数字只由确定性代码产生；不适用的方法明确拒绝，不静默降级。每个新数字（Wald、LR、边际效应、lincom、Rubin 合并、HAC、分组结果、检查统计量）都有 R 或 Stata 对照，或者模拟参数找回。
- **声明而非分支**：共享代码不写模型族名字字面量，由 lint 测试检查。检查、后估计、标准误、组合子都按性质匹配。
- **自然语言可达**：新增的检查、后估计操作、标准误插件、组合子全部登记进能力目录，可达性守卫覆盖它们。
- **分析诚信**：为让结果显著而改数据或挑设定，对用户和 Agent 一律拒绝。按组执行的检验数必须计入披露。检查阈值的调整记入台账。
- **性能预算**：

  | 项 | 预算 |
  |---|---|
  | 读取单个结果 | < 1 s（v1.8.9 为 0.09 s） |
  | Wald / lincom / LR | 读推断核心，< 0.5 s，不重拟合 |
  | 边际效应（10 万行） | < 3 s |
  | 设计级检查合计（10 万行 × 20 列：共线性、每参数行数、工具强度、聚类数） | < 1 s |
  | 分离检查（10 万行） | < 2 s；超出预算标为“未检查”并写明原因 |
  | 按组执行：10 万行、10 组 OLS | < 5 s |
  | 多重插补：1 万行、m = 20 插补 + OLS 合并 | < 30 s |
  | 推断核心的存储（k ≤ 500 时） | 每个结果增加 ≤ 2 MB |
  | 后端测试总时长 | ≤ v1.8.9 的 1.5 倍（13:02 → 上限 19:33），含移植的测试 |

- **不退化**：v1.8.9 已有的 UI、Agent、模型族、结果展示、外发管控全部保留，除非本文件列出替代。
- **提交**：每个交付完成即提交，不留跨天未提交的改动。

## 验证

- 每步先写能复现问题的失败测试，再修；跑相关测试和前端 `tsc`。Python 命令一律加 `PYTHONPATH=backend`。
- 第 1、2、3、5、6、7、8 步：在浏览器里用真实数据、真实界面状态（选中模型节点、长会话）走验收场景。用户 `~/Downloads` 里的 `.dta` / `.sav` 只在本地使用。
- 第 2、6、7、8 步的 Agent 场景用真实 DeepSeek 调用，结果与确定性测试分开记录。
- 发版前：
  - 在宿主终端跑 full gate（`bash scripts/gate.sh --full`）：先停 Vite，独占机器，日志存入 `docs/superpowers/evaluations/gate/`；
  - `scripts/agent_live_eval.py` 全量与对抗用例，加上本版新增用例；
  - `scripts/agent_chaos_eval.py` 反脆弱轮；
  - 验收中改过代码就重跑 gate。

## 已知门槛

- 仅在本机 macOS 验证；Linux、其他主机、云端为 NOT VERIFIED。
- 真实 LLM 的质量只对 DeepSeek 负责。
- 对照依赖本机 Stata 18 与 R 包（`mice`、`sandwich`、`car`、`did` 等）。缺包时测试明确报出，不静默 skip。
- merge / tag / push 需用户单独授权；worktree 与缓存不自动删除。

## 开发线

- worktree：`.worktrees/workbench-v1.8.10`，分支 `workbench-v1.8.10`，基线为本文件与设计文档提交后的 main。
- devline：`v1-8-10`，known gate `scripts/gate.sh --full`。
- 预览端口：backend 8030 / frontend 5190。
- 主要影响路径：
  - `backend/workbench/contracts/model/`、`agent/`、`engine/`、`econometrics/`、`survey/`、`imputation.py`、`analysis_ledger.py`；
  - `frontend/src/`（最小改动）；
  - `tests/`、`scripts/`、`docs/superpowers/`。

## 确认记录

- 2026-09-30：Data 页 Agent 作用域放进本版（做成焦点上下文）；脚本导出、出版级表格放到之后。后估计覆盖面和按组支持范围由用户交给 Claude 设计，结论是按接口和子集语义匹配，由对照数据和不变性测试决定开放什么（设计文档 §3.3、§3.5）。撤回“给现有 Agent 面板加选中文字操作”。准入套件增加模拟参数找回。
- 2026-10-01：用户同意提交本 objective。界面以结果主导为默认、可切换到谱系主导，功能一致（设计文档 §8.2–§8.3，v1.9.0）。nature-skills 只吸收规范、不整包接入（§13，v1.9.2），本版只在检查库预留“报告检查”。现有界面里发现的两处问题归入第 1 步 ⑤ 和第 8 步验收 ④，不加新范围。

## Boundary
- Affected paths: `backend`, `frontend/src`, `tests`, `scripts`, `docs`
- Allowed paths: none
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest <focused tests>`, `cd frontend && npx tsc --noEmit`
- Known gates: `host full gate: scripts/gate.sh --full`, `browser acceptance per objective scenarios`, `real DeepSeek evaluation recorded separately`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-3-cf3-validation-runtime (2026-07-27T12:25:00.000Z)

Completed formal devline v1-8-3-cf3-validation-runtime; final_state=COMPLETED; failure_lesson_keys=authoring-source-allowlist, cf3-validation-runtime-red, fms-event-draft-validation, protocol-identity-binding

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required
