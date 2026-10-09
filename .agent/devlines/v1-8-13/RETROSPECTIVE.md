# Retrospective — v1-8-13

## Goal

# v1.8.13 — 单机全功能后端、Agent 同源能力与分层优化  状态：**APPROVED / 2026-10-09 用户批准开工**。实施已授权；发布仍需另行授权。  ## 目标与基线  Workbench 在不配置模型提供商、不接入模型 API 时，也必须是完整、强大的手动分析工具。所有现有产品操作都有手动调用路径，Agent 通过同一份能力声明、校验和执行服务调用；自然语言生成和解释是模型增强能力，不成为本地分析的前置依赖。  本版负责该目标所需的后端：优先提供 v1.9.0 所需的三类新增接口，保持 v1.8.12 既有接口兼容；同时拆分 Agent 大文件，补齐数据操作 CLI，降低共享层的模型族分支，并以独立数值对照决定 LMM 后估计能力是否可开放。v1.9.0 负责所有界面入口、表单与交互，不自行补后端。  - 输入：\`docs/superpowers/handoffs/2026-10-08-v1.8.13-and-v1.9.0-kickoff.md\` 的 v1.8.13 一节、ADR-PD-001 并行规则、\`docs/superpowers/followups/BACKLOG.md\`。 - 新增输入：v1.9.0 工作目录中的 \`docs/superpowers/objectives/2026-10-08-v1.9.0-objective.md\` 与 \`docs/superpowers/specs/2026-10-08-v1.9.0-operation-interfaces.md\`。2026-10-08 已只读核对；接口文件是需求草案，最终以本线审定的合同提交为准。 - 精确代码基线：tag \`v1.8.12\` → \`91550d734fe9f4612c169708a69323bfb1df0c7c\`（2026-10-08 已核实）。main 已前移，不能用当前 main 替代。 - 确认后创建：分支 \`workbench-v1.8.13\`，工作目录 \`.worktrees/workbench-v1.8.13\`，唯一正式开发线 \`v1-8-13\`。 - 最新交接、规则与已确认 objective 若不在 tag 中，作为明确的治理输入带入新目录；不因此带入 tag 后的产品代码。  ## 范围取舍  推荐采用 **单机能力合同优先、原 P1/P2 保留、P3 受证据与边界约束**。仅拆大文件会继续阻塞前端 Analyze 与手写报告；在前端线各补一套执行逻辑又会让手动与 Agent 行为分叉。新增通用入口应薄接入既有能力，不另建计算引擎。  ## 首批交付：单机全功能合同（V1813-MANUAL-OPERATIONS）  用户已将这三类新增接口及后端优化交由本线负责。新增接口通过独立合同提交交付；旧接口的字段、来源校验与安全限制不因此放宽。路由和完整请求/响应在实施计划中冻结，报告路由为本线提案。  | 接口 | 后端职责 | 验收 | |---|---|---| | \`GET /operations\` | 从现有操作合同与能力目录推导全部操作，返回 id、类别、名称、说明、字段类型/控件提示、必填/默认/范围/枚举、列约束和目标要求；给定目标时返回适用性及具体拒绝原因。已有专用入口的能力声明对应调用方式，不重复实现。 | 覆盖 live registry 的全部操作，不硬编码草案所述的 109 个；逐项能定位参数合同与手动执行入口，新增已注册操作自动纳入。无模型提供商时结果不退化；读取目录不创建业务记录。 | | \`POST /operations/run\` | 接收明确项目/数据集/运行/节点目标与步骤，复用 \`compile_workflow\`、\`WorkflowExecutor\` 和既有服务；返回执行标识、步骤状态、产物引用和节点引用，记录真实 UI 来源。按操作语义复用预览/确认流程。 | 不调用 LLM；与 Agent/CLI 同输入得到同计算结果和持久化语义。覆盖数据与模型目标、多步依赖、无效参数、目标过期、不可用能力、部分失败及重复提交策略。不得直接信任客户端提供的准入、授权、产物归属或指纹。数据变更和自定义代码仍须已有确认/隔离规则。 | | \`POST /runs/{run_id}/manual-reports\`（拟定） | 新增用户作者的报告保存入口；从已计算的事实生成确定性草稿，允许手写修改正文，复用报告历史、版本与导出服务。明确区分用户正文、计算事实和模型生成内容，不伪造模型身份。历史读取/导出所需新增入口一并在合同中说明。 | 不配置模型也能创建草稿 → 编辑 → 保存 → 重开历史 → 导出；服务端校验引用的事实/图表和归属，正文编辑不能覆盖原始统计证据；旧 AI 报告保存、历史与导出继续通过。 |  能力覆盖清单逐项记录声明来源、手动入口、Agent 入口、执行服务、适用目标、参数、结果落点、拒绝原因和测试。工作流目录以外的导入、模型拟合、重跑/比较、表格、报告、脚本导出也纳入核对；发现其他“只有 Agent 可调用”的后端缺口须补入计划，不以菜单有条目代替可执行。  能力未准入、缺统计对照或缺本地运行依赖时，手动与 Agent 返回同一具体限制，不能为了“全部可点”强行开放。真正依赖模型的自然语言能力明确标注增强功能；对应计算、参数编辑和报告手写路径必须仍可用。  先提交合同和后端证据，再交付 commit SHA、生成类型、示例请求/响应及迁移说明。v1.9.0 明确切换并登记本线合同后做 UI 集成验收；本线不直接编辑它的工作目录或 devline。  ## 必做交付与顺序  每步先建立失败测试或能暴露缺陷的结构守卫，再实施、单独提交并保存验收记录。纯重构同时保留基线行为对照。顺序为下表第 1 步 gate 锁 → 上述单机能力合同 → 第 2–5 步；不让后续重构延迟前端合同交付。  | 顺序 | 交付 | 验收标准 | |---|---|---| | 1 | **V1813-GATE-LOCK-GLOBAL**：gate 使用整机共享的排他锁 | 不同工作目录、不同 TMPDIR 的两个调用仍互斥；第二个调用在重负载开始前明确拒绝；正常退出、失败与中断释放锁；陈旧锁处置不误杀进程。用轻量替身验证竞争，不实际并跑两套 full gate。旧版本 gate 未采用新锁时，人工独占规则继续有效。 | | 2 | **V1812-AGENT-GOD-FILES（必做）**：按工具类别拆分 \`backend/workbench/agent/context_tools.py\` | 按节点/操作、数据集、模型统计、图形证据、Notebook/分析循环等职责分组，具体依赖划分在实施计划中核定；公共请求类型与 provider 入口保持兼容，保留薄入口；入口和本次拆出的每个模块均 ≤ 2000 行。不得把大文件整体搬家、复制实现或新增循环依赖。工具注册、返回结构、错误、预算截断、只读边界、准入与外发脱敏行为保持一致。 | | 3 | **V1812-FAMILY-LITERAL-DOWN**：先修测量口径，再迁移旧模型族路径 | 单独提交正则修正：排除草稿节点 id，并在 tag 基线上复核交接中的 119 − 45 = 74；若不吻合先解释差异，不能静默改数。随后按同一口径降至 ≤ 54，逐族迁移旧 \`run_*\` / \`_fit_*\` 到模型包；明确列出迁移族与剩余项，区分正确分层迁移和真正去重，不靠扩大扫描排除范围达标。每个迁移族有结果、错误与导出回归。 | | 4 | **V1813-CLI-DATA-OPS**：从现有数据操作合同生成子命令 | 覆盖现有合同所声明的数据操作，包括 subset、recode、merge、reshape；复用同一服务、验证与持久化路径，不新增第二套参数表。真实 CLI 完成“数据操作 → 拟合 → 后估计 → 导出”；验证帮助、参数错误、无效列、合并键问题、reshape 错误及退出码，核对 Operation Record、谱系和 API 同输入结果。 | | 5a | **V1811-LMM-REMAINING**：可读分类项名 | 复用既有公式项解析；如 \`C(Q('arm'), Treatment(reference='a'))[T.b]\` 显示为 \`arm: b\`。覆盖参考组、交互项、引号/反斜杠/冒号列名与标签冲突；保留计算键和系数定位，不改已发布记录格式，不改变统计值。通过现有 HTTP/Agent 路径及原界面验证显示。 | | 5b | **V1811-LMM-REMAINING**：ML 似然比与边际效应独立对照 | 完成 R/Stata 同数据、同样本、同模型与同估计定义的对照，记录版本、命令、估计方法、数值、预定容差及误差。LR 检查 ML/REML、嵌套性、样本一致性及边界情形；边际效应检查估计对象、协方差和区间定义。证据充分且既有合同可承载时才开放；不一致或环境不可用时保留关闭并记 GAP，不改容差或估计定义凑通过。 |  ## P3 与边界冲突的处理  - **V1812-NB1-R-EXPORT**：先评估参照级 NB1 原生 R 实现，并与 Stata \`nbreg, dispersion(constant)\` 独立对照。满足定义与数值验证才接入；原生验收必须重新估计且明确 \`fully_native\`，不能用结果侧车重放冒充。未满足则维持现状并保留原因。 - **V1812-TYPES-FOLLOWUPS**：本线可收敛后端 ARMA-GARCH 变换 id 的重复来源，前提是值及接口输出不变。\`diff_ref\` 声明若改变 OpenAPI，先向用户说明影响与必要性，等待明确授权；\`frontend/\` 下 \`notebook/contracts.ts\` 的编译期一致性归前端线协调，本线不修改。 - LMM 能力开放若需要 HTTP 合同调整，同样先报告、等待授权。单机能力所需的三类新增接口属于本次新增范围，不扩展为其他接口变更的预授权。  ## 文件与行为边界  - 实施范围：上述交付直接涉及的 \`backend/\`、\`tests/\`、gate/检查/生成相关 \`scripts/\`，以及对应 objective、plan、evaluation、followup 和 release 文档。开 devline 前根据实施计划冻结具体 affected paths 和 allow paths。 - **不改前端实现**；唯一例外是独立合同提交所需的自动生成文件 \`frontend/src/generated/api-schema.ts\`。既有 v1.8.12 路由、方法、参数、响应形状与错误约定保持兼容，新增 schema 单独审查，不能借生成类型修改手写前端。 - 单机合同按交接要求单独提交、重新生成类型、跑漂移验证并登记两条线；v1.9.0 明确接受新合同后才能依赖它。跨线记录由各线正式 CLI 完成，不手改另一条线文件。其他新增接口或已有接口的变更先说明影响并取得授权。 - 不做界面重做、完整 LMM 固定效应卡片、CSS、会话令牌、Linux 支持或其他未列明能力。已有安全、准入、持久化权限和外发边界不得放宽。 - 不在 main 提交，不修改 v1.9.0 工作目录；不执行 merge、tag、push、Release 或删除工作目录。发布另需授权。  ## 验收与预算  - 聚焦回归从 \`tests/test_gate_script.py\`、\`tests/test_agent_context_tools.py\`、\`tests/test_family_literal_ratchet.py\`、\`tests/test_layering_guard.py\`、\`tests/test_cli_from_catalog.py\`、\`tests/test_lmm_result_adapter.py\`、\`tests/test_lmm_postestimation_v1811_reference.py\` 及对应合同/准入测试扩展；新增测试文件随实施计划登记。 - 合同验证覆盖实际返回分支，检查 OpenAPI 与生成类型漂移；新增接口之外的基线合同保持兼容，生成文件只通过正式生成流程更新。子进程显式固定本工作目录的 \`PYTHONPATH=backend\`，避免测到共享环境指向的另一版本。 - 浏览器使用本线 v1.8.12 前端、可见且独立的会话，在 8033/5193 完成“上传 → 数据操作 → 拟合 → Agent 查询已保存结果 → 后估计 → 导出”；LMM 项名、已开放能力与拒绝分支另做场景。使用临时验收项目，记录结果与限制。 - CLI 实跑、R/Stata 数值对照、浏览器验收、provider 验证、full gate 与 FMS 分开记录；未跑项标为 NOT VERIFIED。 - 单机专项：未配置 provider，并用测试阻止任何 LLM 调用，后端完成 recode → 描述统计 → t 检验 → IV → Wald → 弱工具诊断 → PCA，以及报告草稿 → 手写保存 → 重开 → 导出。后端逐项合同覆盖与代表性执行均验证。v1.9.0 接入新合同后，另做上述流程的真实点选验收及全目录表单覆盖；在此之前只声明后端已验收，不能宣称“全功能已可点”。 - 后端全套预算 **≤ 20:09**；每次 gate 保存墙钟时间及慢项。交接记录的 18:26 为历史值，不当作本版测量。不得放宽预算、删测试或跳过统计对照以求通过；新增 CLI 帮助/命令生成维持既有 < 0.5 s 启动预算并明确测量口径。 - 发布前在宿主终端运行 \`scripts/gate.sh --full\`，完成两轮自审；最终验收覆盖最终代码。FMS verify 只证明过程合规，不替代上述验收。  ## 并行与开工流程  1. 用户确认本 objective 后，才从精确 tag 创建工作目录，运行 \`bash scripts/link-shared-deps.sh <工作目录>\` 与 \`.venv/bin/python scripts/check_dev_env.py\`，验证导入来自本目录。禁止 \`pip install -e\` 或 \`npm install\`。 2. 形成实施计划、具体路径、测试和已知 gate；只用 \`PYTHONPATH=backend .venv/bin/python scripts/devline_control.py start\` 打开 \`v1-8-13\` 一条正式线。读取生成的 \`CONTEXT_PACK.md\`、global rules 及其指定历史材料，再实施；本轮已预读 v1.8.12 回顾，开线后按 Context Pack 补齐。 3. 配置本线端口：backend 8033、frontend 5193，后端允许对应前端源。主仓库 \`.claude/launch.json\` 是交接指定的共享配置例外：修改前重新读取，仅新增/维护本线 \`backend-v1813\`、\`frontend-v1813\`，保留另一线条目并核验并发修改，不在 main 提交。 4. **每次 gate 前确认另一线没有 gate、Vite 或重负载测试**，记录实时进程/锁证据；不能确认就询问用户。不能把工作目录存在、旧进程快照或本线加锁当作另一线空闲的证据。浏览器服务与 gate 分时运行，不擅停另一线进程。 5. 重大 FAILURE、ERROR、GAP、WASTE、REVIEW、GATE、STATE_CHANGE 通过 CLI 登记。范围变化只用 \`rescope-context\`；allowlist 变化显式给出重复的 \`--allow-path\`。不手写/改写 \`.agent/devlines/\`。收尾验证事件流并用 CLI 重生成 retrospective。  ## 确认记录  - 2026-10-08 用户要求：先起草并确认 objective；\`context_tools.py\` 拆分必做；从 v1.8.12 tag 开线；不改前端，需要接口变更先告知；gate 开跑前确认另一条线没有在跑。 - 2026-10-08 用户补充：Claude Code 继续 v1.9.0 前端，v1.8.13 后端优化全部由本线承担；所有功能必须不依赖模型 API、单靠 Workbench 手动可用，Agent 调用同一能力。已将三类接口加入首批交付，前端边界仅增加生成类型的合同例外；完整修订于 2026-10-09 获用户批准。 - 2026-10-09 用户：“好的，批准，开干吧”。按本修订版本建工作目录、开唯一 devline 并实施；不授权发布。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 3/22 (13.6%; 13.6 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=434540 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #8 2026-10-09T06:28:54.430Z `genesis_selected_dataset_ignored`; cause_status: `known`; cause: The original-upload shortcut compared the selected frame with itself instead of proving raw-upload identity.; resolution: `open`; lesson: Assert actual fitted sample size and immutable source bytes across data-operation to model execution, not only successful status.

## All errors

- None recorded.

## All gaps

- #10 2026-10-09T06:36:40.724Z `lmm_postestimation_native_evaluation`; cause_status: `known`; cause: Native R/Stata comparison exposes omitted interaction contribution in time margins; current LR provenance cannot establish admissible comparisons.; resolution: `accepted`; lesson: Recompute owner results against frozen native references and preserve actual failures; admission is separate from evidence-test success.
- #12 2026-10-09T06:55:40.902Z `remaining_acceptance_boundaries`; cause_status: `known`; cause: Existing mixed-plan source validation contradicts non-frame Wald semantics; original frontend lacks the new manual operation UI and cold first-use data help loads the existing numerical registry.; resolution: `open`; lesson: Distinguish composable service execution from every mixed-plan shape and from frontend acceptance; never claim measured warm-start timing as cold first-use timing.

## All waste

- None recorded.

## Root causes and solutions

- `lmm-postestimation-native-evidence`: occurrences=1; cause_status: `known`; root cause: Native R/Stata comparison exposes omitted interaction contribution in time margins; current LR provenance cannot establish admissible comparisons.; solution: `accepted`
- `offline-backend-acceptance-boundaries`: occurrences=1; cause_status: `known`; root cause: Existing mixed-plan source validation contradicts non-frame Wald semantics; original frontend lacks the new manual operation UI and cold first-use data help loads the existing numerical registry.; solution: `open`
- `selected-dataset-model-source-authority`: occurrences=1; cause_status: `known`; root cause: The original-upload shortcut compared the selected frame with itself instead of proving raw-upload identity.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `lmm-postestimation-native-evidence`: line experience occurrence(s)=1
- `offline-backend-acceptance-boundaries`: line experience occurrence(s)=1
- `selected-dataset-model-source-authority`: line experience occurrence(s)=1

## Future guidance

- Assert actual fitted sample size and immutable source bytes across data-operation to model execution, not only successful status.
- Distinguish composable service execution from every mixed-plan shape and from frontend acceptance; never claim measured warm-start timing as cold first-use timing.
- Exercise persisted dataset formats and require registered evidence at manual reporting boundaries.
- Public presentation names are not executable formula structure; keep verified design metadata separate from labels.
- Recompute owner results against frozen native references and preserve actual failures; admission is separate from evidence-test success.

## Event index

- #1: `f9856754-5aeb-452b-b8ee-b71b7f70f51b` | 2026-10-09T05:54:01.350Z | STATE_CHANGE/line_started | incident=`dc78d445-e0af-4a39-9dae-0481deb09477` | lesson_key=`frozen-context-before-start` | event_sha256=`fcb1e2f037957ab6fb1f5f778d7a1e8fd95ea071223e569b7f89e56d730ca264`
- #2: `16c4ded9-f988-4b2f-bd7c-776a8083abfd` | 2026-10-09T05:55:23.074Z | STATE_CHANGE/approved_kickoff | incident=`cd899113-9c21-46fd-b85f-e97ec7438617` | lesson_key=`release-baseline-and-manual-capability-contract` | event_sha256=`d13056a0ac759b6bf154aff5e09f414cbf6734c2b0a1628d1b50e0550bc02a31`
- #3: `ed937ac2-5e17-4235-a443-a87285bda99e` | 2026-10-09T05:58:47.194Z | GATE/global_lock_focused | incident=`79903d67-7b67-4ff7-83dd-11dffae0e6ff` | lesson_key=`machine-gate-lock-stable-inode` | event_sha256=`9323fde74e0bfb2cad5250ba364fc6c4db952172cb35d5575fc7738bba019a53`
- #4: `12eb3fc4-9498-4c27-a84e-b16e646afb2f` | 2026-10-09T06:06:40.622Z | STATE_CHANGE/context_tools_split | incident=`cc3c7017-8da0-4547-a374-04a4c7c2ce28` | lesson_key=`context-tool-responsibility-split` | event_sha256=`68fad43d5b214f10cc365df0cb2c6914ba7deaba20af89c9d312929493a28fbb`
- #5: `c6be40b9-d444-4748-bd87-38265b4cd9a3` | 2026-10-09T06:13:23.162Z | STATE_CHANGE/family_measurement_corrected | incident=`c9344821-ca90-49aa-ace5-0c0e609ecd26` | lesson_key=`family-ratchet-measurement-separation` | event_sha256=`0122ce0b2456f2099304586f2da48861beb21a2bb49829a98068d8ce2ec6799e`
- #6: `5df4abb5-ab94-4186-9925-705b431181b6` | 2026-10-09T06:23:47.875Z | STATE_CHANGE/manual_contract_delivered | incident=`1056dd3e-02cb-49fa-a2d4-26b9fe5b8508` | lesson_key=`manual-and-agent-shared-execution` | event_sha256=`14a8d7f9bbebab5c927e26bc1cfd86c2a4295ffd788eca552e035523fc8f683e`
- #7: `632c1611-bb7e-4daa-9fa3-fa6ac4c64ff7` | 2026-10-09T06:28:54.430Z | STATE_CHANGE/family_policy_and_fit_ownership | incident=`b309e0c6-e9ea-4268-8bb4-8c78563f53eb` | lesson_key=`family-owned-policies-and-fit-adapters` | event_sha256=`943dda5fbc18f012dcefd773071a47333e9cf9bed376b7d3fc7e83bd1f225920`
- #8: `b0ce0896-86c1-4067-ba25-be35d7b86800` | 2026-10-09T06:28:54.430Z | FAILURE/genesis_selected_dataset_ignored | incident=`8aa9cda2-4fd2-42ad-a224-7f9f6c0f1df9` | lesson_key=`selected-dataset-model-source-authority` | event_sha256=`2aa4e5b9bb7ca06995718e82dc0cbc35194784a0aa9a0ab6765c6d569db0a803`
- #9: `876a32ce-3ff2-47b9-8c84-58b6a191eb46` | 2026-10-09T06:36:08.970Z | STATE_CHANGE/genesis_selected_dataset_fixed | incident=`8aa9cda2-4fd2-42ad-a224-7f9f6c0f1df9` | lesson_key=`selected-dataset-model-source-authority` | event_sha256=`f4839daddf7c6d93bc7627f66e08ff3913d7ae96d1668ca1965eb07d1bc26187`
- #10: `6b9f3217-4f6c-4d77-a880-4f9dfb4545f1` | 2026-10-09T06:36:40.724Z | GAP/lmm_postestimation_native_evaluation | incident=`c0e10ff3-f0be-45dd-8486-5de61f1aa2bf` | lesson_key=`lmm-postestimation-native-evidence` | event_sha256=`a42e357875a035fc4a9894fdca22dd645a30b267123fa8603172708c9805485d`
- #11: `c2003749-2c38-4516-8a91-e0adcabce5b1` | 2026-10-09T06:51:11.416Z | REVIEW/independent_version_review_resolved | incident=`1ad9bdcf-372b-4ae9-8921-17f6ecba7693` | lesson_key=`manual-boundary-independent-review` | event_sha256=`9885e60147288571a8ecc6d663e91185ddb364bb63197235e2193745e39b360c`
- #12: `197932d7-3c5c-4ebf-9ab4-72f2e3826e32` | 2026-10-09T06:55:40.902Z | GAP/remaining_acceptance_boundaries | incident=`81e6f1dd-2e99-4867-b634-52fd23df7b29` | lesson_key=`offline-backend-acceptance-boundaries` | event_sha256=`a3072886eec506d661392aede85bbce4798ea4c61c9f6207feb321f1036b1966`
- #13: `a0aa2857-0529-40a9-8dc8-2e79a9b44f6c` | 2026-10-09T07:14:24.483Z | GATE/final_full_gate_failed | incident=`eb11d415-6bbc-409a-9022-28359c06ce68` | lesson_key=`notebook-dataset-source-family-ownership` | event_sha256=`0b592bb884569d80b1aa50d7b7ea239d78268c93701f939d31ede3480676a443`
- #14: `c68720db-f41e-4d1e-87f5-c82b6ece698e` | 2026-10-09T07:17:06.570Z | STATE_CHANGE/full_gate_findings_corrected | incident=`eb11d415-6bbc-409a-9022-28359c06ce68` | lesson_key=`notebook-dataset-source-family-ownership` | event_sha256=`074d8e89719f9b114b0d1b41561e87b2dac12a5df4130332d93f34488c48e780`
- #15: `57c7c794-7350-4b87-849b-ffd052d34606` | 2026-10-09T12:59:33.903Z | STATE_CHANGE/authorized_backend_closure | incident=`514f220b-a6b0-48b8-8f0a-5de385be77e9` | lesson_key=`manual-contract-consumer-adoption` | event_sha256=`c756c1e35e5ee1d9aac7520e706e93af1efeb182c6f7e30a1491d4f586eceda6`
- #16: `db3cb8b8-4476-43cd-9cf6-e1ea216d22c7` | 2026-10-09T13:03:38.765Z | STATE_CHANGE/context_rescope_required | incident=`7c9e1b84-acd8-49b9-94ec-3ae01a8d64a2` | lesson_key=`context-pack-rescope` | event_sha256=`78ab0a7e0c5ed5add5e0b6522d87bf9fb88f3a4086b3d0cac79147ace1fbbc59`
- #17: `1face047-79d9-4036-8bcf-e3c1b8d45e9f` | 2026-10-09T13:03:38.773Z | STATE_CHANGE/context_rescoped | incident=`2a63ff2a-c8ca-4928-81e0-8f263b522ce6` | lesson_key=`context-pack-rescope` | event_sha256=`f07edb6f358d3d9b227900b7c5aed15ddb32261e212bcb2c93dd9f545f0a7cf5`
- #18: `d18dbb28-bfcb-4b0a-9618-521f05ef89fd` | 2026-10-09T13:14:07.809Z | REVIEW/closure_diff_review_resolved | incident=`9a37bbd5-9d84-4940-afcc-aa783161a75c` | lesson_key=`verified-design-not-public-label` | event_sha256=`5a2657eec8294b7e043f5dd5a6c996afdd47a471463a8d272dcd3e5237a3ab93`
- #19: `6c6c354c-0175-43e4-832e-81d61c154d08` | 2026-10-09T13:32:14.012Z | STATE_CHANGE/context_rescope_required | incident=`939a47ad-845b-4aca-ab6c-46a499aa10bb` | lesson_key=`context-pack-rescope` | event_sha256=`c810a027856f08a7d8c103de78fdec526ee18e456c69702d5e654ca56991d111`
- #20: `5e88fd8c-ced9-46a8-8c99-38d4bcbfbce8` | 2026-10-09T13:32:14.026Z | STATE_CHANGE/context_rescoped | incident=`fe943901-86b6-4fe9-a0ac-5ec34198fe38` | lesson_key=`context-pack-rescope` | event_sha256=`d3f1bf6aa29164b045d26f1f8d0210c476bd4438ee023e1b060469bfa00ede50`
- #21: `8b8bd493-2acd-4f58-bcc6-e0ad751efce7` | 2026-10-09T13:33:21.449Z | GATE/final_closure_gate_documentation_corrected | incident=`7dad30d9-a6a6-48b0-a2a9-8578f6fe657d` | lesson_key=`registry-admission-generated-reference` | event_sha256=`93300e726a2e693433343bb9256f859af3bcbb5824c51505234d062581c71464`
- #22: `a5298097-7741-4594-8d18-5355860565c6` | 2026-10-09T13:34:05.023Z | STATE_CHANGE/backend_contract_ready_for_frontend_adoption | incident=`514f220b-a6b0-48b8-8f0a-5de385be77e9` | lesson_key=`manual-contract-consumer-adoption` | event_sha256=`9f3a1913f9b3962d5eb23a0a378d765a25d9609f84eb4212e0b721cf3ea989f2`
