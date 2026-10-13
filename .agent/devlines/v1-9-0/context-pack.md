# Frozen Context Pack

Line: `v1-9-0`
Baseline SHA: `d983ae1d41ff7f005c85202843b6ab23dcf7beb8`

## Objective
# v1.9.0 — 工作台外壳：按工作顺序组织、单机全功能、唯一的 Agent

基线：tag `v1.8.12` = `91550d73`。来源：设计文档 `specs/2026-09-30-composable-capabilities-and-research-workspace-design.md` §8、§10；
设计图 artifact `GXYhj86xeRHhEMDBiAekW8`（最上面一行 “Everything works by hand” 是工作顺序与离线状态；第二行 “After v1.8.12” 补了
v1.8.10–v1.8.12 的新功能；第三行是融合方案）；交接 `handoffs/2026-10-08-v1.8.13-and-v1.9.0-kickoff.md`；BACKLOG §0.3、§0.4 中归
v1.9.0 的 5 项。v1.8.13（后端）在另一个对话并行。

## 一句话目标

把现有界面的全部功能按研究者实际的工作顺序重新组织进一个新外壳：每个操作都能不接模型、单靠点选完成，Agent 通过同一套声明
调用同样的操作；结果主导为默认、谱系主导可随时切换；浅色与深色由同一套设计 token 定义。整体简洁、直观、高级，不丢任何现有功能。

## 设计原则（本版的验收依据）

1. **单机全功能，Agent 同源**。Agent 能做的每一个操作，界面上都有点选路径；两者走同一份操作声明、同一个表单、同一个执行服务。
   Agent 的提案就是“已填好的表单”，可以打开改任何字段再确认。没有接入模型时，Agent 列收成一条窄栏，其他一切照常。
2. **按工作顺序组织**（设计图 `Journey`）：导入数据 → 理解与准备 → 探索 → 估计 → 追问（后估计、诊断）→ 稳健性（改参数重跑、
   分叉、比较）→ 汇总与分享（表格、报告、脚本）。追问常常回到准备或估计。因此：
   - 视图按顺序排列：Data · Analysis · Tables · Report · Plans；新项目打开在 Data，第一个模型完成后切到 Analysis；
   - 结果下方的动作按后续顺序排列：New test · Diagnostics · Rerun with changes · Compare · Add to table · Add to report · Reproduce；
   - 没有死路：空项目给出 Import data，没有角色的数据给出 Set roles，没有检验的模型给出 New test；
   - 一个入口找到所有操作：顶栏 Analyze 菜单与 ⌘K，按类别列出，按当前对象的性质标出可用与不可用（并说明原因）。
3. **简洁**：常用路径在第一层，高级选项在第二层；不加模态遮罩；状态同时用文字、图标、颜色表达；1.5px 线性图标，不用 emoji。

## 现状（2026-10-08 核实）

- 外壳：`WorkbenchRouteContainer.tsx` 2101 行，顶部视图标签 Notebook · Graph · Data · Table · Report，左侧运行记录栏，
  中间图，右侧多标签详情，下方面板（Agent · Logs · AI activity）。
- **操作覆盖**：Agent 工作流有 109 个步骤操作（数据 12、时间序列 10、模型 8、多元 8、检验 8、非参数 7、诊断 6、GLM 扩展 5、
  后估计 5、生存 3、功效 2，以及匹配、元分析、预测、重抽样、空间、ROC、合成控制等）。界面能直接调用的只有模型拟合（`POST /runs`）、少数数据操作（转换、类型转换、代码执行、
  特征配方）与统计探索；其余只能经 Agent 或命令行。后端没有不经 Agent 执行单个工作流步骤的 HTTP 接口（命令行 `workbench
  postestimation` 直接调用 `WorkflowExecutor`）。
- AI 入口 4 个：Notebook 规划、Report 写作、节点 Ask AI、下方 Agent。焦点已有 project / dataset / node 三种接入，
  plan / report 已登记未接页面（V1810-FOCUS-REMAINING）。报告只能经 AI 生成，保存走 `POST /runs/{id}/ai-reports`。
- 样式：6 个全局 CSS 共 5471 行，139 处写死颜色，931 处内联样式；深色主题下 `ios-group` 面板仍是白底（V1811-DARK-PANEL-CONTRAST）。
- 图谱操作面板对 column / integer / number / object / json 五类控件只读（V1812-GRAPH-CONTROL-KINDS）；LMM 结果卡片只显示组 × 时间交互项。

## 需要 v1.8.13 线提供的接口（合同提交，详见 `specs/2026-10-08-v1.9.0-operation-interfaces.md`）

第 3 步“操作目录”依赖两个通用接口，报告手写依赖第三个。按并行规则由 v1.8.13 线以单独的合同提交提供、重新生成类型、过漂移测试、
记入两条线的 devline；本线明确切换到新合同后再用。接口到位前，第 1、2 步与第 4–8 步中不依赖它们的部分照常推进。

## 范围（按 §8.8 迁移顺序交付，每步单独提交并验收）

新外壳在第 2 步到第 9 步都放在功能开关后面，和旧界面并存；第 10 步对照验收通过后才设为默认。

| # | 交付 | 验收场景 |
|---|---|---|
| 1 | **设计 token 与主题地基**（V1811-FRONTEND-CSS、V1811-DARK-PANEL-CONTRAST）。§8.5 的颜色、字号、间距、圆角、材质、动效写成 CSS 变量，浅色与深色两套（深色取设计图 `After1812LineageDark`）；`prefers-reduced-motion`、`prefers-reduced-transparency` 降级。写死颜色 139 → 0；内联样式只降不升，新代码不写内联颜色。棘轮测试守住两项计数；token 配对对比度测试（两种主题文字 ≥ 4.5:1） | 旧界面在浅色 / 深色 / 跟随系统三档下逐页截图，深色下无白底面板、无不可读文字 |
| 2 | **外壳骨架与布局切换**。功能开关（设置里的 “New workspace”，另有 URL 参数便于测试）；网格：地图 · 舞台 · Agent · 下方面板；顶栏（地图显隐、项目切换、视图 Data · Analysis · Tables · Report · Plans、布局开关、⌘K、Analyze、Rerun、设置）；结果主导 / 谱系主导切换：分段开关、⌘\、地图的“展开”与检查栏的“Open wide”、拖动分隔线（两个停靠点、按速度投影落点、临界阻尼弹簧、可中途打断）；每个项目记住上次布局；切换时选中节点、打开的标签、Agent 对话都不变；Agent 列可收成窄栏（⌘.），未接入模型时默认收起 | 两种布局来回切换 10 次（含动画中途反向），状态不丢；关闭再打开项目，布局保持；删除模型提供商后外壳完整可用 |
| 3 | **操作目录与通用表单**（依赖接口文件中的接口 1、2）。顶栏 Analyze 菜单与 ⌘K：按类别（Data、Describe、Tests、Models、Post-estimation、Diagnostics、Multivariate、Survival、Time series、Power、Export 等，由目录给出）列出全部操作，按当前焦点的性质标出可用 / 不可用及原因；表单由操作的参数声明生成（列选择器、数值、整数、列表、枚举、对象），与第 5 步“改参数重跑”的控件共用；执行后结果在舞台打开、在地图上成为节点、记入分析台账（来源 = 界面）。Models 类就是现有的运行表单（⌘N），字段不变。测试：目录中的每个工作流操作都有可渲染的表单（覆盖率 100%，新增操作自动出现） | 不接模型：对 IV 示例项目依次完成 recode → 描述统计 → t 检验 → IV 拟合 → Wald → 弱工具诊断 → PCA，全部点选完成 |
| 4 | **地图**。图画布在结果主导时是 280px 一列（树形，节点带关键数字与所属运行），谱系主导时占中间并保留全部工具（横向 / 纵向 / 手动布局、Fit、Stages、Fullscreen、缩放、未运行方案显隐）；选中一次运行在地图上高亮其分支（取代 Versions）；右键菜单、拖动布局原样保留 | 两种布局下对 IV 示例项目逐项操作图工具；选运行高亮分支 |
| 5 | **舞台与结果视图**。标签栏（Pin、在新窗口打开、关闭）；本页目录（滚动定位）；结果视图各段：Result（各族结果卡片内容不变）· Checks · Coefficients（含 LMM 完整固定效应表）· Post-estimation（列出该模型全部检验，New test 在段内就地打开表单）· Reproduce（脚本导出搬入，控件与覆盖表全部保留）· Rerun with changes（五类控件就地编辑，V1812-GRAPH-CONTROL-KINDS；运行后生成新分支，原节点不变）· Compare · Roles · Lineage · Info；结果下方的“下一步”动作行；来源行（运行、数据、估计方法、推断口径、估计方程），旧结果标 Legacy z。舞台按自身宽度切换排版（container query），谱系主导时是 360px 检查栏的紧凑版 | OLS、IV、分位数回归、LMM、负二项、ARMA-GARCH 各开一个节点，两种布局下逐段核对；在检查栏里改分位数列表与 bootstrap 次数并运行出新分支；手动做一次 Wald 与 lincom；从 Reproduce 导出 Stata 脚本并下载 |
| 6 | **唯一的 Agent 列**。合并下方 Agent、节点 Ask AI、Report 写作者；输入框上方焦点标签，作用对象跟随焦点（project / dataset / node / plan / report 五种都接上页面，空白项目的项目焦点可以提出提案）；Agent 的提案以对应操作的表单呈现，可打开编辑；节点上过去的问题按节点分组；写报告时写作模型、证据范围、图表选择以标签出现在输入框上方；输入框保留 Add context、Capabilities、上下文用量环、模型选择、语音、发送；选中即问（Ask / Explain / Add to message / Show source，带来源链接）；提案卡片改用新视觉 | 真 DeepSeek（`deepseek-flash`）：在 Data、节点、报告三种焦点下各问一次，作用对象正确；让 Agent 做一次后估计，提案打开后与手动表单相同，改一个字段再确认；选中结果中的数字提问，引文带来源 |
| 7 | **下方面板**。Timeline · Runs · Logs · Activity 四个标签，可拖高；收起时是一行（最近事件、披露计数）；Runs 承接原运行记录栏的全部功能（状态、时间、View all、删除等）；Logs、Activity 原样 | 运行一次新分析，四个标签各自更新；拖高、收起、展开 |
| 8 | **Data、Tables、Report、Plans 视图**。Data 全部保留（Data View / Variable View、数据集选择、Transform、Export、AI sharing、值标签、分页），空项目显示导入；Tables 支持多个模型并排，并列出后估计结果；Report 文档居中，Scope、分析路径、证据、图表选择、历史收进可开关的 Sources 侧栏，导出菜单保留，Report review 成为审阅模式；**不接模型时报告从计算得出的草稿开始，手写并保存**（依赖接口文件中的接口 3）；Plans 原样承载现有 Notebook，Notebook 中依赖模型的部分在未接入时说明原因并指向 Analyze。谱系主导下打开这四个视图临时用宽舞台，回到 Analysis 时恢复原布局 | 每个视图按旧界面功能清单逐项操作；不接模型写一份报告并导出；在谱系主导下进出 Report，布局正确恢复 |
| 9 | **术语与数字**。按 §8.7 清理内部标识符（移入来源，默认折叠）；新增测试：界面字符串不得出现内部标识符；数字统一按格式规则（不出现 p = 0 和 16 位小数）；主题开关与模型提供商移进设置 | 测试通过；两种布局逐页检查无内部标识符 |
| 10 | **对照验收与切换默认**。按设计图编号 #1–#22 逐项列出旧位置与新位置；三遍完整场景（导入 → 理解与准备 → 探索 → 估计 → 追问 → 稳健性 → 表格 → 报告 → 导出脚本）：结果主导 + 浅色 + 不接模型、谱系主导 + 深色 + 不接模型、结果主导 + 接 DeepSeek 由 Agent 完成同一场景；全部通过后新外壳设为默认。旧外壳在本版仍可从设置切回，v1.9.1 与 Notebook 页一起下线 | 对照表逐项打勾并附截图；三遍场景逐步截图 |

## 不在本版

- 1200px 以下的窗口与 iPad、手机尺寸（设计图 Compact、Phone 保留，以后再做）。
- 方案对比视图、手动建立方案、预先设定与探索性的判定、问题变更（v1.9.1）；Timeline 只显示已有数据能给出的标记。
- 多语言；后端任何改动（新接口只经 v1.8.13 线的合同提交）。
- ≥ 1920px 时并排比较两个结果（只做舞台最大宽度）。

## 硬约束

- **单机全功能**：第 3 步覆盖率测试守住“每个工作流操作都有界面入口”；第 10 步不接模型完成全部场景。
- **不丢功能**：现有界面的每个功能都有新位置（第 10 步对照表为准）；v1.8.12 已有的模型族、后估计、脚本导出、外发管控、数字核对全部保留。
- **文件边界**：不改 `backend/`；接口只用 `frontend/src/generated/api-schema.ts`；不在工作目录里运行 `npm install`。
- **可访问性**：§8.9 全部做到；键盘可完成全部操作；只有图标的按钮都带 `aria-label`。
- **代码结构**：新外壳的文件每个 ≤ 500 行；不再往 `WorkbenchRouteContainer.tsx` 加代码，默认切换后它只承载旧外壳。
- **尺寸**：在 1512 × 982（14 寸 MBP 默认）下设计与验收；1280–1511 与 ≥ 1920 保证不重叠、不出现横向滚动，但不单独验收。
- **性能预算**（1512 × 982，IV 示例项目，另用一个 ≥ 100 节点的项目复测）：
  - 布局切换动画 ≤ 350 ms，切换过程中没有 > 50 ms 的长任务；
  - 打开项目到可交互，不慢于 v1.8.12 同场景实测值的 110%；
  - 点选节点或切换舞台标签到内容出现 ≤ 100 ms；Analyze 菜单打开与搜索响应 ≤ 50 ms；
  - 前端产物（gzip）增长 ≤ 15%；
  - 前端测试数不减少，前端测试总时长记录在每次 gate 里。

## 验证

- 每步先写失败测试；前端 `tsc --noEmit` 与相关 vitest。
- 每步做浏览器验收（端口：后端 8034、前端 5194；在主仓库 `.claude/launch.json` 新增 `backend-v190`、`frontend-v190`），
  截图存入 `evaluations/`；浏览器受控输入用真实键入。
- 第 6 步用真 DeepSeek（`deepseek-flash`）走真实发送路径。
- 发版前：确认 v1.8.13 线没有 gate、Vite 或重负载测试在跑，然后在宿主终端跑 full gate（带耗时），Claude 两轮自审，再请用户授权发版。

## 已知门槛

仅本机 macOS 验证；gate 在宿主终端跑（LMM 依赖宿主隔离），并与 v1.8.13 线错开（gate 锁按目录名区分，不会互相阻止）；
merge / tag / push / Release 需用户授权。哪条线先完成先发，后完成的合入已发布版本、重跑 gate 再发。
第 3 步与第 8 步的报告手写依赖 v1.8.13 线提供的接口；如 v1.8.13 先发布，本线合入后切换到新合同。

## 开发线

worktree `.worktrees/workbench-v1.9.0`（分支 `workbench-v1.9.0`），devline `v1-9-0`，known gate `scripts/gate.sh --full`。

## 确认记录

- 2026-10-01（用户）：结果主导为默认，保留谱系主导，两者功能一致；保留现有优秀设计和功能，只换位置。
- 2026-10-08（用户）：v1.8.13 与 v1.9.0 两个对话并行；v1.9.0 不改 `backend/`。
- 2026-10-08（用户看过 “After v1.8.12” 三张设计图后）：设计由 Claude 把握，追求简洁、直观、高级；**一版做完**；
  **暂不做小窗口 / iPad 与手机尺寸，只做本机屏幕尺寸**。
- 2026-10-08（用户）：**Agent 能力是核心，但没有接入 API、单机时 Workbench 也要是强大的工具：所有功能必须单靠 Workbench 就能操作，
  Agent 也能调用**；重构时要考虑用户实际的操作顺序、会点什么、功能之间的顺序与联系。据此：
  - 撤回“后估计只经 Agent 运行”，改为舞台内 New test 手动表单，Agent 走同一表单；
  - 新增第 3 步“操作目录与通用表单”，需要 v1.8.13 线提供接口文件中的接口；
  - 视图顺序改为 Data · Analysis · Tables · Report · Plans；New analysis 并入 Analyze › Models（⌘N 不变）；
  - 第 10 步增加两遍“不接模型”的完整场景。
- 2026-10-08（Claude 的设计决定）：Rerun with changes 运行后生成新分支，原节点不变，Agent 提出同一改动时与检查栏共用一份草稿；
  Plans 视图在本版原样承载 Notebook，右侧 Agent 在 Plans 视图默认收起以免同屏两个输入框；旧外壳在本版仍可从设置切回，v1.9.1 下线。

## Boundary
- Affected paths: `frontend/src`, `frontend/package.json`, `docs`, `evaluations`, `backend/workbench/report_view_model.py`, `backend/workbench/http/runs_routes.py`, `tests/test_report_export.py`, `backend/workbench/services/lmm_coefficients.py`, `backend/workbench/services/results_service.py`, `backend/workbench/contracts/model/presentation.py`, `backend/workbench/agent/context_tools_support/coefficients.py`, `tests/test_lmm_coefficient_view.py`, `backend/workbench/contracts/model/script_results.py`, `backend/workbench/script_export/builder.py`, `tests/test_script_export_intrinsic_covariance.py`, `backend/workbench/lineage/manual_patch_validation.py`, `tests/test_manual_patch_validation.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_read_only_analysis.py`, `tests/test_agent_routes.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `tests/test_workflow_capability_adapters.py`, `backend/workbench/services/operation_catalog.py`, `tests/test_operation_catalog.py`
- Allowed paths: none
- Protected paths: `backend`
- Dependencies: `v1-8-13 contract commit: GET /operations, POST /operations/run, manual report save (specs/2026-10-08-v1.9.0-operation-interfaces.md)`
- Tests: `cd frontend && npx tsc --noEmit`, `cd frontend && npx vitest run <focused tests>`
- Known gates: `host full gate with durations, exclusive of the v1-8-13 line: PYTEST_ADDOPTS='--durations=30 --junitxml=local/pytest-durations.xml' bash scripts/gate.sh --full`, `browser acceptance at 1512x982 on ports 8034/5194, both layouts, light and dark, with and without a model connected`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-workflow-memory-integration (2026-08-02T11:23:33.067Z)

Completed formal devline v1-8-5-workflow-memory-integration; final_state=COMPLETED; failure_lesson_keys=browser-memory-projection-contract-must-roundtrip, complete-v11-fields-when-removing-memory-provenance, did-genesis-empty-predictors-contract, did-model-family-contract-before-workflow-admission, did-notebook-family-contract-wiring, did-planner-family-contract-wiring, memory-default-target-registry-before-application, memory-provenance-version-from-new-proposal-on-revalidation, opaque-vocabulary-id-before-consumer-wiring, tdd-domain-memory-preflight-before-gate-wiring, tdd-memory-default-provenance-ui-before-persistence

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-3-mem2-domain-memory (2026-07-27T11:05:00.000Z)

Completed formal devline v1-8-3-mem2-domain-memory; final_state=COMPLETED; failure_lesson_keys=domain-memory-contract-first, frontend-api-awaits-response

### v1-8-3-design-review-corrections (2026-07-26T00:27:24.000Z)

Completed formal devline v1-8-3-design-review-corrections; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-b0-authority-verifier-redesign (2026-07-26T09:04:34.000Z)

Completed formal devline v1-8-3-b0-authority-verifier-redesign; final_state=COMPLETED; failure_lesson_keys=none
