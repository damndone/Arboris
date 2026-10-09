# Frozen Context Pack

Line: `v1-8-13`
Baseline SHA: `91550d734fe9f4612c169708a69323bfb1df0c7c`

## Objective
# v1.8.13 — 单机全功能后端、Agent 同源能力与分层优化

状态：**APPROVED / 2026-10-09 用户批准开工**。实施已授权；发布仍需另行授权。

## 目标与基线

Workbench 在不配置模型提供商、不接入模型 API 时，也必须是完整、强大的手动分析工具。所有现有产品操作都有手动调用路径，Agent 通过同一份能力声明、校验和执行服务调用；自然语言生成和解释是模型增强能力，不成为本地分析的前置依赖。

本版负责该目标所需的后端：优先提供 v1.9.0 所需的三类新增接口，保持 v1.8.12 既有接口兼容；同时拆分 Agent 大文件，补齐数据操作 CLI，降低共享层的模型族分支，并以独立数值对照决定 LMM 后估计能力是否可开放。v1.9.0 负责所有界面入口、表单与交互，不自行补后端。

- 输入：`docs/superpowers/handoffs/2026-10-08-v1.8.13-and-v1.9.0-kickoff.md` 的 v1.8.13 一节、ADR-PD-001 并行规则、`docs/superpowers/followups/BACKLOG.md`。
- 新增输入：v1.9.0 工作目录中的 `docs/superpowers/objectives/2026-10-08-v1.9.0-objective.md` 与 `docs/superpowers/specs/2026-10-08-v1.9.0-operation-interfaces.md`。2026-10-08 已只读核对；接口文件是需求草案，最终以本线审定的合同提交为准。
- 精确代码基线：tag `v1.8.12` → `91550d734fe9f4612c169708a69323bfb1df0c7c`（2026-10-08 已核实）。main 已前移，不能用当前 main 替代。
- 确认后创建：分支 `workbench-v1.8.13`，工作目录 `.worktrees/workbench-v1.8.13`，唯一正式开发线 `v1-8-13`。
- 最新交接、规则与已确认 objective 若不在 tag 中，作为明确的治理输入带入新目录；不因此带入 tag 后的产品代码。

## 范围取舍

推荐采用 **单机能力合同优先、原 P1/P2 保留、P3 受证据与边界约束**。仅拆大文件会继续阻塞前端 Analyze 与手写报告；在前端线各补一套执行逻辑又会让手动与 Agent 行为分叉。新增通用入口应薄接入既有能力，不另建计算引擎。

## 首批交付：单机全功能合同（V1813-MANUAL-OPERATIONS）

用户已将这三类新增接口及后端优化交由本线负责。新增接口通过独立合同提交交付；旧接口的字段、来源校验与安全限制不因此放宽。路由和完整请求/响应在实施计划中冻结，报告路由为本线提案。

| 接口 | 后端职责 | 验收 |
|---|---|---|
| `GET /operations` | 从现有操作合同与能力目录推导全部操作，返回 id、类别、名称、说明、字段类型/控件提示、必填/默认/范围/枚举、列约束和目标要求；给定目标时返回适用性及具体拒绝原因。已有专用入口的能力声明对应调用方式，不重复实现。 | 覆盖 live registry 的全部操作，不硬编码草案所述的 109 个；逐项能定位参数合同与手动执行入口，新增已注册操作自动纳入。无模型提供商时结果不退化；读取目录不创建业务记录。 |
| `POST /operations/run` | 接收明确项目/数据集/运行/节点目标与步骤，复用 `compile_workflow`、`WorkflowExecutor` 和既有服务；返回执行标识、步骤状态、产物引用和节点引用，记录真实 UI 来源。按操作语义复用预览/确认流程。 | 不调用 LLM；与 Agent/CLI 同输入得到同计算结果和持久化语义。覆盖数据与模型目标、多步依赖、无效参数、目标过期、不可用能力、部分失败及重复提交策略。不得直接信任客户端提供的准入、授权、产物归属或指纹。数据变更和自定义代码仍须已有确认/隔离规则。 |
| `POST /runs/{run_id}/manual-reports`（拟定） | 新增用户作者的报告保存入口；从已计算的事实生成确定性草稿，允许手写修改正文，复用报告历史、版本与导出服务。明确区分用户正文、计算事实和模型生成内容，不伪造模型身份。历史读取/导出所需新增入口一并在合同中说明。 | 不配置模型也能创建草稿 → 编辑 → 保存 → 重开历史 → 导出；服务端校验引用的事实/图表和归属，正文编辑不能覆盖原始统计证据；旧 AI 报告保存、历史与导出继续通过。 |

能力覆盖清单逐项记录声明来源、手动入口、Agent 入口、执行服务、适用目标、参数、结果落点、拒绝原因和测试。工作流目录以外的导入、模型拟合、重跑/比较、表格、报告、脚本导出也纳入核对；发现其他“只有 Agent 可调用”的后端缺口须补入计划，不以菜单有条目代替可执行。

能力未准入、缺统计对照或缺本地运行依赖时，手动与 Agent 返回同一具体限制，不能为了“全部可点”强行开放。真正依赖模型的自然语言能力明确标注增强功能；对应计算、参数编辑和报告手写路径必须仍可用。

先提交合同和后端证据，再交付 commit SHA、生成类型、示例请求/响应及迁移说明。v1.9.0 明确切换并登记本线合同后做 UI 集成验收；本线不直接编辑它的工作目录或 devline。

## 必做交付与顺序

每步先建立失败测试或能暴露缺陷的结构守卫，再实施、单独提交并保存验收记录。纯重构同时保留基线行为对照。顺序为下表第 1 步 gate 锁 → 上述单机能力合同 → 第 2–5 步；不让后续重构延迟前端合同交付。

| 顺序 | 交付 | 验收标准 |
|---|---|---|
| 1 | **V1813-GATE-LOCK-GLOBAL**：gate 使用整机共享的排他锁 | 不同工作目录、不同 TMPDIR 的两个调用仍互斥；第二个调用在重负载开始前明确拒绝；正常退出、失败与中断释放锁；陈旧锁处置不误杀进程。用轻量替身验证竞争，不实际并跑两套 full gate。旧版本 gate 未采用新锁时，人工独占规则继续有效。 |
| 2 | **V1812-AGENT-GOD-FILES（必做）**：按工具类别拆分 `backend/workbench/agent/context_tools.py` | 按节点/操作、数据集、模型统计、图形证据、Notebook/分析循环等职责分组，具体依赖划分在实施计划中核定；公共请求类型与 provider 入口保持兼容，保留薄入口；入口和本次拆出的每个模块均 ≤ 2000 行。不得把大文件整体搬家、复制实现或新增循环依赖。工具注册、返回结构、错误、预算截断、只读边界、准入与外发脱敏行为保持一致。 |
| 3 | **V1812-FAMILY-LITERAL-DOWN**：先修测量口径，再迁移旧模型族路径 | 单独提交正则修正：排除草稿节点 id，并在 tag 基线上复核交接中的 119 − 45 = 74；若不吻合先解释差异，不能静默改数。随后按同一口径降至 ≤ 54，逐族迁移旧 `run_*` / `_fit_*` 到模型包；明确列出迁移族与剩余项，区分正确分层迁移和真正去重，不靠扩大扫描排除范围达标。每个迁移族有结果、错误与导出回归。 |
| 4 | **V1813-CLI-DATA-OPS**：从现有数据操作合同生成子命令 | 覆盖现有合同所声明的数据操作，包括 subset、recode、merge、reshape；复用同一服务、验证与持久化路径，不新增第二套参数表。真实 CLI 完成“数据操作 → 拟合 → 后估计 → 导出”；验证帮助、参数错误、无效列、合并键问题、reshape 错误及退出码，核对 Operation Record、谱系和 API 同输入结果。 |
| 5a | **V1811-LMM-REMAINING**：可读分类项名 | 复用既有公式项解析；如 `C(Q('arm'), Treatment(reference='a'))[T.b]` 显示为 `arm: b`。覆盖参考组、交互项、引号/反斜杠/冒号列名与标签冲突；保留计算键和系数定位，不改已发布记录格式，不改变统计值。通过现有 HTTP/Agent 路径及原界面验证显示。 |
| 5b | **V1811-LMM-REMAINING**：ML 似然比与边际效应独立对照 | 完成 R/Stata 同数据、同样本、同模型与同估计定义的对照，记录版本、命令、估计方法、数值、预定容差及误差。LR 检查 ML/REML、嵌套性、样本一致性及边界情形；边际效应检查估计对象、协方差和区间定义。证据充分且既有合同可承载时才开放；不一致或环境不可用时保留关闭并记 GAP，不改容差或估计定义凑通过。 |

## P3 与边界冲突的处理

- **V1812-NB1-R-EXPORT**：先评估参照级 NB1 原生 R 实现，并与 Stata `nbreg, dispersion(constant)` 独立对照。满足定义与数值验证才接入；原生验收必须重新估计且明确 `fully_native`，不能用结果侧车重放冒充。未满足则维持现状并保留原因。
- **V1812-TYPES-FOLLOWUPS**：本线可收敛后端 ARMA-GARCH 变换 id 的重复来源，前提是值及接口输出不变。`diff_ref` 声明若改变 OpenAPI，先向用户说明影响与必要性，等待明确授权；`frontend/` 下 `notebook/contracts.ts` 的编译期一致性归前端线协调，本线不修改。
- LMM 能力开放若需要 HTTP 合同调整，同样先报告、等待授权。单机能力所需的三类新增接口属于本次新增范围，不扩展为其他接口变更的预授权。

## 文件与行为边界

- 实施范围：上述交付直接涉及的 `backend/`、`tests/`、gate/检查/生成相关 `scripts/`，以及对应 objective、plan、evaluation、followup 和 release 文档。开 devline 前根据实施计划冻结具体 affected paths 和 allow paths。
- **不改前端实现**；唯一例外是独立合同提交所需的自动生成文件 `frontend/src/generated/api-schema.ts`。既有 v1.8.12 路由、方法、参数、响应形状与错误约定保持兼容，新增 schema 单独审查，不能借生成类型修改手写前端。
- 单机合同按交接要求单独提交、重新生成类型、跑漂移验证并登记两条线；v1.9.0 明确接受新合同后才能依赖它。跨线记录由各线正式 CLI 完成，不手改另一条线文件。其他新增接口或已有接口的变更先说明影响并取得授权。
- 不做界面重做、完整 LMM 固定效应卡片、CSS、会话令牌、Linux 支持或其他未列明能力。已有安全、准入、持久化权限和外发边界不得放宽。
- 不在 main 提交，不修改 v1.9.0 工作目录；不执行 merge、tag、push、Release 或删除工作目录。发布另需授权。

## 验收与预算

- 聚焦回归从 `tests/test_gate_script.py`、`tests/test_agent_context_tools.py`、`tests/test_family_literal_ratchet.py`、`tests/test_layering_guard.py`、`tests/test_cli_from_catalog.py`、`tests/test_lmm_result_adapter.py`、`tests/test_lmm_postestimation_v1811_reference.py` 及对应合同/准入测试扩展；新增测试文件随实施计划登记。
- 合同验证覆盖实际返回分支，检查 OpenAPI 与生成类型漂移；新增接口之外的基线合同保持兼容，生成文件只通过正式生成流程更新。子进程显式固定本工作目录的 `PYTHONPATH=backend`，避免测到共享环境指向的另一版本。
- 浏览器使用本线 v1.8.12 前端、可见且独立的会话，在 8033/5193 完成“上传 → 数据操作 → 拟合 → Agent 查询已保存结果 → 后估计 → 导出”；LMM 项名、已开放能力与拒绝分支另做场景。使用临时验收项目，记录结果与限制。
- CLI 实跑、R/Stata 数值对照、浏览器验收、provider 验证、full gate 与 FMS 分开记录；未跑项标为 NOT VERIFIED。
- 单机专项：未配置 provider，并用测试阻止任何 LLM 调用，后端完成 recode → 描述统计 → t 检验 → IV → Wald → 弱工具诊断 → PCA，以及报告草稿 → 手写保存 → 重开 → 导出。后端逐项合同覆盖与代表性执行均验证。v1.9.0 接入新合同后，另做上述流程的真实点选验收及全目录表单覆盖；在此之前只声明后端已验收，不能宣称“全功能已可点”。
- 后端全套预算 **≤ 20:09**；每次 gate 保存墙钟时间及慢项。交接记录的 18:26 为历史值，不当作本版测量。不得放宽预算、删测试或跳过统计对照以求通过；新增 CLI 帮助/命令生成维持既有 < 0.5 s 启动预算并明确测量口径。
- 发布前在宿主终端运行 `scripts/gate.sh --full`，完成两轮自审；最终验收覆盖最终代码。FMS verify 只证明过程合规，不替代上述验收。

## 并行与开工流程

1. 用户确认本 objective 后，才从精确 tag 创建工作目录，运行 `bash scripts/link-shared-deps.sh <工作目录>` 与 `.venv/bin/python scripts/check_dev_env.py`，验证导入来自本目录。禁止 `pip install -e` 或 `npm install`。
2. 形成实施计划、具体路径、测试和已知 gate；只用 `PYTHONPATH=backend .venv/bin/python scripts/devline_control.py start` 打开 `v1-8-13` 一条正式线。读取生成的 `CONTEXT_PACK.md`、global rules 及其指定历史材料，再实施；本轮已预读 v1.8.12 回顾，开线后按 Context Pack 补齐。
3. 配置本线端口：backend 8033、frontend 5193，后端允许对应前端源。主仓库 `.claude/launch.json` 是交接指定的共享配置例外：修改前重新读取，仅新增/维护本线 `backend-v1813`、`frontend-v1813`，保留另一线条目并核验并发修改，不在 main 提交。
4. **每次 gate 前确认另一线没有 gate、Vite 或重负载测试**，记录实时进程/锁证据；不能确认就询问用户。不能把工作目录存在、旧进程快照或本线加锁当作另一线空闲的证据。浏览器服务与 gate 分时运行，不擅停另一线进程。
5. 重大 FAILURE、ERROR、GAP、WASTE、REVIEW、GATE、STATE_CHANGE 通过 CLI 登记。范围变化只用 `rescope-context`；allowlist 变化显式给出重复的 `--allow-path`。不手写/改写 `.agent/devlines/`。收尾验证事件流并用 CLI 重生成 retrospective。

## 确认记录

- 2026-10-08 用户要求：先起草并确认 objective；`context_tools.py` 拆分必做；从 v1.8.12 tag 开线；不改前端，需要接口变更先告知；gate 开跑前确认另一条线没有在跑。
- 2026-10-08 用户补充：Claude Code 继续 v1.9.0 前端，v1.8.13 后端优化全部由本线承担；所有功能必须不依赖模型 API、单靠 Workbench 手动可用，Agent 调用同一能力。已将三类接口加入首批交付，前端边界仅增加生成类型的合同例外；完整修订于 2026-10-09 获用户批准。
- 2026-10-09 用户：“好的，批准，开干吧”。按本修订版本建工作目录、开唯一 devline 并实施；不授权发布。

## Boundary
- Affected paths: `backend/workbench`, `tests`, `scripts/gate.sh`, `scripts/gate_lock.py`, `frontend/src/generated/api-schema.ts`
- Allowed paths: `backend/workbench`, `tests`, `scripts`, `docs/superpowers`, `docs/releases`, `frontend/src/generated/api-schema.ts`
- Protected paths: `frontend/src/components`, `frontend/src/routes`, `frontend/src/notebook`
- Dependencies: `v1.9.0 consumes standalone additive contract commit; never modify its worktree`, `shared dependencies only; host-exclusive gate and no Vite`
- Tests: `tests/test_gate_script.py`, `tests/test_agent_context_tools.py`, `tests/test_family_literal_ratchet.py`, `tests/test_layering_guard.py`, `tests/test_cli_from_catalog.py`, `tests/test_lmm_result_adapter.py`, `tests/test_lmm_postestimation_v1811_reference.py`
- Known gates: `host scripts/gate.sh --full, exclusive machine; backend <=20:09`, `offline manual operation contract and report end-to-end; independent visible UI acceptance`, `R/Stata independent references before statistical capability admission; formal verify not statistical acceptance`

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

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-3-mem1-project-context-index (2026-07-27T09:14:00.000Z)

Completed formal devline v1-8-3-mem1-project-context-index; final_state=COMPLETED; failure_lesson_keys=project-index-contract-first

### v1-8-3-b0-runtime-implementation (2026-07-26T03:36:00.000Z)

Completed formal devline v1-8-3-b0-runtime-implementation; final_state=CLOSED; failure_lesson_keys=none
