# Retrospective — v1-8-4-reopened-incident-truth

## Goal

# v1.8.4 重开的 6 条 incident + 沙箱执行环境 — Codex 对接指令（第二轮）  上一轮（commit \`6d88903\`）关闭的 10 条里，**6 条的关闭证据不成立**，已用原 incident_id 重开。本文件说明是怎么判定的、怎么重做、以及**为什么你每次都撞上 \`sandbox_apply: Operation not permitted\` 而我没有**。  ---  ## 0. 先解决执行环境：那 20 个 sandbox 失败不是本机限制  ### 事实  在**同一台主机、你的同一个 commit \`6d88903\`** 上独立重跑后端套件：  \`\`\` 11 failed, 4241 passed, 8 skipped, 1 xfailed   (8m56s) sandbox_apply / sandbox-exec 命中次数：0 \`\`\`  11 个失败全部在 \`tests/test_gate_script.py\`，是绕过 \`gate.sh\` 直接调 pytest 造成的 harness 依赖（那些测试测的就是 gate 脚本本身），经 \`gate.sh\` 时全绿。  同一主机上直接执行也成功：  \`\`\`bash printf '(version 1)(allow default)' > /tmp/p.sb /usr/bin/sandbox-exec -f /tmp/p.sb /bin/echo OK   # → OK, exit 0 \`\`\`  ### 原因  产品的 Darwin containment 走 \`/usr/bin/sandbox-exec\` （\`backend/workbench/native_containment/executor_darwin.py:161\`）。 macOS **不允许嵌套 sandbox**：在一个已经被 Seatbelt 约束的进程里再调 \`sandbox_apply\`，内核直接返回 \`Operation not permitted\` （\`platform_darwin.py:269\` 把它归类为 \`NATIVE_CONTAINMENT_SANDBOX_APPLY_FAILED\`）。  **你的命令默认跑在 Codex 自己的 Seatbelt 沙箱里**（macOS 上的 \`workspace-write\` 等模式就是用 \`sandbox-exec\` 实现的）。所以产品想再套一层沙箱时 必然被拒。我的执行环境没有这层外壳，因此那 20 个测试正常通过。  **这是执行环境问题，不是宿主限制，也不是产品缺陷。** 上一轮把它写成 「既知的本机 containment 限制，因此 full gate 未绿」是错的，已在 release notes 订正。  ### 你要怎么做  跑 gate **必须脱离 Codex 自身的沙箱**，二选一：  \`\`\`bash # A. 提升本次会话的沙箱级别（推荐；具体参数以你的 Codex 版本为准） codex --sandbox danger-full-access # 或在 config 里对该仓库放行，再跑 gate \`\`\`  \`\`\`bash # B. 直接在 Codex 之外的终端里跑 gate，把日志贴回来 cd "/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.4" LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 bash scripts/gate.sh --full \`\`\`  **验收标准（硬性）**： - [ ] 提交前必须有一次 \`sandbox_apply\` 命中为 **0** 的 full gate。 - [ ] 若仍然复现 20 个 sandbox 失败，**先确认自己是否在沙箱里**：       跑上面那三行 \`sandbox-exec\` 自检。自检失败 = 你在沙箱里，先解决环境，       **不要**把它记成产品或宿主问题，更不要据此宣布 full gate「因本机限制未绿」。 - [ ] **绝不允许**用 skip、xfail 或弱化 sandbox 让它「变绿」。  ### 顺带  跑 gate 前要停掉 vite（\`scripts/gate.sh:86\` 见到 vite 就 \`REFUSING\`）。 上一轮结束时 5177/8000 还开着，导致我无法给出经 \`gate.sh\` 的对照数字。 **跑完 gate 再把服务起回来，别留着占端口。**  ---  ## 1. 判定标准：为什么这 6 条不算修好  我对每条 closing 事件引用的测试做了 \`git log -S "def <test_name>"\`，看它是哪个 commit 引入的，再对照 \`git show --stat 6d88903\` 看对应生产模块有没有改动。  \`6d88903\` 的**全部后端生产改动是 40 行、2 个文件**： \`agent/navigation.py\`(15) 和 \`agent/notebook/materialization.py\`(25)。 \`workflow_contracts.py\`、\`workflow_runtime.py\`、\`context_tools.py\`、 \`agent_routes.py\`、\`core.py\`、\`figure_context.py\`、\`planning_agent.py\` **一行未动**。  | incident | 引用的测试 | 引入 commit | 对应生产模块 | |---|---|---|---| | \`64ec6d96\` predictor_residual | \`..._binned_numeric_facts_not_rows\` | \`6607c2d\` baseline | 未改 | | \`8ff5b466\` figure_evidence | \`..._not_raw_vectors\` | \`6607c2d\` baseline | 未改 | | \`9aac0586\` proposal_ready | \`..._even_at_step_budget\` | \`6607c2d\` baseline | 未改（测试文件都不在 diff 里） | | \`2c20a717\` covariance 边界 | \`test_main_role_turn_exposes_only_read_only_project_evidence_tool\` | \`a5a5f49\` baseline | 未改；且该测试与本 incident 无关 | | \`33c552d6\` 八候选 | 新测试 | — | 未改；\`run_ids\` maxItems 自 \`6607c2d\` 起就是 **16**，断言 \`>= 8\` 必然通过 | | \`11a22915\` depends_on | 新测试 | — | 未改；形状发布(\`planning_agent.py:700\`)与纠正分支(\`:1281\`)都出自 \`6607c2d\` |  \`6607c2d\` / \`a5a5f49\` 是**本轮工作开始前**的 baseline。  **规则**：closing 事件引用的证据必须是**这次工作产生的**。 早于本线存在的测试、或对未修改模块既有行为的断言，记录的是一次没发生过的验证。  ---  ## 2. 重做方法：每条先做「归类」，再决定动作  **不要一上来就改代码。** 对每条先回答一个问题：  > baseline \`6607c2d\` 是否已经满足这条 incident 描述的需求？  ### 情形 A：baseline 已满足 → 记「核实为已满足」，不改代码  这是**完全合格的交付**，很可能是这 6 条里多数的真实归宿。  **方法**： 1. 找出提供该能力的确切 commit 与代码位置。 2. 写一条**能证明该能力存在**的测试（若已存在就引用它，但要说明它是既有测试）。 3. append 事件：\`resolution: resolved\`，但 \`lesson\` 与 \`impact\` 里**明确写出**    「本 incident 的需求由 commit \`<sha>\` 的 \`<file:line>\` 提供，本轮未作改动，    核实为已满足」。  **验收标准**： - [ ] 事件里有确切的 commit sha 和文件位置。 - [ ] **不得**出现在 release notes 的「本版本交付」里——那是 baseline 能力。 - [ ] 事件的 \`subtype\` 用 \`<原名>_verified_preexisting\`，不要用 \`_remediated\`。  ### 情形 B：baseline 不满足 → 按正常流程修  **验收标准**： - [ ] 有一条**先失败后通过**的测试。提交前用 \`git stash\` 或临时回退实现，       **贴出它失败时的输出**。只说「测试通过」不算。 - [ ] 生产模块确实有改动，且改动与 incident 描述的因果对得上。  ### 情形 C：incident 的诊断本身就是错的 → 记「诊断有误」  **方法**：写清楚原始诊断错在哪、正确的事实是什么。 \`resolution: not_applicable\`，\`cause_status: known\`。  **验收标准**： - [ ] 有反证原始诊断的具体证据（代码位置 / 测试 / 观测）。 - [ ] **不要**为了让它「有个结论」而硬安一个修复。  ---  ## 3. 逐条：已知事实与需要判定的点  ### 3.1 \`2c20a717\` covariance 解释边界 —— 最可能是情形 A  **已知**：所需的边界文案**已存在**于 \`backend/workbench/http/agent_routes.py:141-142\`，出自 \`6607c2d\`：  > 不得说 nonrobust 显著性是假的、虚假的、或由异方差引起，除非有单独的诊断确立该更强主张。  **但**任务书要求的**负向测试不存在**——上一轮引用的 \`test_main_role_turn_exposes_only_read_only_project_evidence_tool\` 说的是只读工具 暴露，跟这条毫无关系。  **要做**： - [ ] 补一条**负向**测试：喂入真实的 robust/nonrobust 对比证据，断言回答       **不含**因果归因措辞（「说明存在异方差」「原结果是假显著」等）。 - [ ] 若该测试直接通过 → 情形 A，如实记「protocol 已由 \`6607c2d\` 提供，本轮补测试」。 - [ ] 若失败 → 情形 B，修 protocol。  ### 3.2 \`33c552d6\` Global Agent 答案路径 —— 一半 A、一半未做  **已知**：\`inspect_project_notebook_workflow_results\` 的 \`run_ids\` maxItems **自 \`6607c2d\` 起就是 16**（\`context_tools.py:1147\`）。所以断言 \`>= 8\` 恒真， incident 里「拒绝超过四个候选运行」的说法要么指的是**别的工具** （\`inspect_project_model_coefficients\` 的 maxItems 确实是 4，见 \`:978\`）， 要么是误诊。  **incident 的另一半完全没碰**：「protocol 没有让 receipt → branch evidence 的路径足够直接」。  **要做**： - [ ] 先判定 4-run 限制到底出在哪个工具上。若是       \`inspect_project_model_coefficients\`，那才是要处理的对象。 - [ ] **步数有上界的测试**（这是 incident 的实质）：项目里 8 个 run 与 20 个 run，       从提问到答案的**工具调用次数不变**。这条不能靠 maxItems 断言替代。 - [ ] 证据不存在时仍然拒答，不得为了能答而放宽有界证据边界。  ### 3.3 \`9aac0586\` proposal-ready 终态 —— 需要先复现  **已知**：\`core.py\` 未改；引用的测试在 \`tests/test_agent_tools.py\`，出自 \`6607c2d\`，而该文件**根本不在 \`6d88903\` 的 diff 里**。  **要做**： - [ ] 先**复现** incident 的主张：确认门控的 proposal 产出后是否真的还强制多走       一轮 model turn 并耗尽 step budget。 - [ ] 复现到 → 情形 B（改 \`core.py\`），并断言这一轮**没有**额外 provider       round-trip（\`test_proposal_ready_test_expectations_stale\` 里已有这个断言范式）。 - [ ] 复现不到 → 情形 C，写清楚为什么原诊断不成立。  ### 3.4 \`64ec6d96\` predictor-residual 证据 / 3.5 \`8ff5b466\` figure 证据 —— 一起做  **已知**：两条引用的测试都出自 \`6607c2d\`，说明「有界分箱、不发行级向量」这个 **性质在 baseline 就成立**。  **但 incident 描述的是另外两件事**，都没被验证： 1. \`64ec6d96\`：**planner 不知道** \`model.genesis\` 已经为每个声明的 predictor    持久化了 residual-vs-predictor 图，于是会声称做不了用户要的残差诊断。 2. \`8ff5b466\`：该证据在 node context 层可用，但**没接进 Global Agent 的    project-scoped 只读工具注册表**。  **要做**： - [ ] \`64ec6d96\`：测 planner 的**行为**——对「给我 X 对残差的图」的回应应当指向       已持久化产物，而**不是**新增一个画图 step。这是 planner 提示/纠正逻辑的测试，       不是产物 payload 的测试。 - [ ] \`8ff5b466\`：测 **Global Agent 工具注册表**是否暴露该 reader       （\`provider.global_tool_definitions(...)\` 里有没有）。       node-scoped 可用**不等于** project-scoped 可用——要有一条测试钉死这个边界。 - [ ] ⚠️ \`backend/workbench/figure_context.py\` **在 allowlist 之外**：       \`rescope-context\` 会拒绝 \`backend/workbench/*.py\`（\`len(parts) < 4\`）。       要改它必须**新开一条开发线**，在 \`start\` 时就把路径写进 allowlist。  ### 3.6 \`11a22915\` depends_on 形状 —— 最可能是情形 A 或 C  **已知**：形状发布（\`planning_agent.py:700-701\`）和纠正分支（\`:1281\`）都出自 \`6607c2d\`，本轮未改该文件。新测试断言的是既有行为。  **要做**： - [ ] 判定 incident 的前提（「形状说明不够具体」）在 \`6607c2d\` 之后是否还成立。 - [ ] 若已具体 → 情形 A 或 C，如实记录并说明是哪个 commit 提供的。 - [ ] 若仍不够 → 情形 B，改提示并保留三种输入（省略 / \`[]\` / \`"step_1"\`）       各不相同且可执行的纠正消息。服务端**仍然拒绝**畸形值——修的是提示与恢复，       不是放宽校验。  ---  ## 4. FMS 操作要点（上一轮踩过的）  - 事件、rescope、verify 一律走 \`scripts/devline_control.py\`，不手改   \`.agent/devlines/\`。 - 枚举：\`type\` 无 \`FIX\`（用原 type + \`resolution\`）；\`stage\` 无 \`verification\`   （用 \`gate\`）；\`resolution\` 用 \`resolved\` / \`not_applicable\`，不是 \`fixed\`；   关线 = append \`STATE_CHANGE\` 且 \`state_to: COMPLETED\`（自动生成 RETROSPECTIVE）。 - **每条都用原 incident_id**：   \`64ec6d96\` · \`8ff5b466\` · \`9aac0586\` · \`2c20a717\` · \`33c552d6\` · \`11a22915\`。 - \`backend/workbench/*.py\` 顶层文件加不进 allowlist，只能新开线时写进去。   上一轮为此做了 12 次 rescope——**开线时一次把路径列全**，别边做边 rescope。  ---  ## 5. 收尾验收清单  - [ ] 6 条各自归类为 A / B / C 并有对应证据，事件用原 incident_id。 - [ ] 情形 B 的每条都贴出**修复前的失败输出**。 - [ ] 一次 \`sandbox_apply\` 命中为 **0** 的 \`gate.sh --full\`，且跑之前 vite 已停。       基线：backend 4245 passed / 8 skipped / 1 xfailed（commit \`fdf47a4\` 实测），       golden 23 0-drift，frontend 171 files，tsc 0。**只许涨不许跌。** - [ ] release notes：情形 A/C 的**不得**写进「本版本交付」；       情形 B 的才可以写，并注明证据。 - [ ] BACKLOG 的 \`V1.8.4-OPEN\` 行按实际剩余更新。 - [ ] handoff 只留最新一份，旧的移 \`archive/handoff/\` 并修好指向它的链接。 - [ ] 服务恢复（backend 8000 / vite 5177）。  **push / PR / merge / tag 不要自己走**，交回用户决定。

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/13 (15.4%; 15.4 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=5524000 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #10 2026-07-31T06:27:56.000Z `outside_sandbox_gate_unavailable`; cause_status: `external`; cause: The required elevated sandbox self-test was rejected by the execution platform due to the agent usage limit before it could establish a non-nested Seatbelt environment.; resolution: `open`; lesson: When the execution authority cannot leave the nested workspace sandbox, retain the full-gate boundary and obtain equivalent evidence only from an explicitly authorized external terminal.
- #11 2026-07-31T08:00:00.000Z `outside_sandbox_gate_unavailable`; cause_status: `known`; cause: The elevated sandbox self-test was rejected inside the agent platform, so no non-nested Seatbelt environment was available to that session.; resolution: `resolved`; lesson: macOS refuses nested sandbox_apply, so a product that shells out to sandbox-exec cannot be gated from inside an agent sandbox; run the gate on the host.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `full-gate-requires-non-nested-seatbelt`: occurrences=1; cause_status: `external`; root cause: The required elevated sandbox self-test was rejected by the execution platform due to the agent usage limit before it could establish a non-nested Seatbelt environment.; solution: `open`
- `gate-requires-non-nested-sandbox`: occurrences=1; cause_status: `known`; root cause: The elevated sandbox self-test was rejected inside the agent platform, so no non-nested Seatbelt environment was available to that session.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `full-gate-requires-non-nested-seatbelt`: line experience occurrence(s)=1
- `gate-requires-non-nested-sandbox`: line experience occurrence(s)=1

## Future guidance

- A terminal-state incident must be reproduced at its exact budget boundary before any remedy is named.
- Classify planner-awareness claims against the published prompt and recovery path, not only the artifact payload boundary.
- For generated statistical prose, distinguish a tested instruction boundary from an unprovable guarantee about all future provider output.
- Measure tool-call count across differing overview sizes; a maxItems assertion alone cannot establish bounded path length.
- Node-context evidence and Global Agent registry admission are separate properties; verify both exact registry scope and protocol before declaring a gap.
- When the execution authority cannot leave the nested workspace sandbox, retain the full-gate boundary and obtain equivalent evidence only from an explicitly authorized external terminal.
- Wire-shape incidents need evidence for both published schema guidance and the invalid-input recovery path.
- macOS refuses nested sandbox_apply, so a product that shells out to sandbox-exec cannot be gated from inside an agent sandbox; run the gate on the host.

## Event index

- #1: `9f6fe44a-5bbe-4d45-a89c-5463a72970f7` | 2026-07-31T06:18:48.750Z | STATE_CHANGE/line_started | incident=`4b6f7be8-106a-4a99-a578-8ffe9b230174` | lesson_key=`frozen-context-before-start` | event_sha256=`e39aafe40af3109cf55d2df3be09dc705679f7f851e152ac78d3434e9b86fffe`
- #2: `bb67b5c6-279c-4da0-9775-34400085b533` | 2026-07-31T06:23:38.206Z | STATE_CHANGE/context_rescope_required | incident=`d9215780-e21f-4089-8ed1-cbe8f07da4cb` | lesson_key=`context-pack-rescope` | event_sha256=`c68c1329e0d086fb266cf4be6f2710d20b51f879ce307d1f4df9e2303ef3f8ee`
- #3: `ce1874f3-52b3-4227-a433-b85b32e0e367` | 2026-07-31T06:23:38.210Z | STATE_CHANGE/context_rescoped | incident=`b2aa38bc-d848-4a39-9db3-c4daa3ea6791` | lesson_key=`context-pack-rescope` | event_sha256=`2692f5cff694a858a0eb3a146c5366c14d9b2d0bf694f5fa5d9811039c25ddc7`
- #4: `6aa3d7c0-91d9-419c-b83f-a51157947432` | 2026-07-31T06:27:56.000Z | REVIEW/predictor_residual_verified_preexisting | incident=`64ec6d96-b9bb-4e36-ac51-a6a312a9d5c8` | lesson_key=`baseline-behavior-must-not-be-released-as-remediation` | event_sha256=`ab5323a3ccc327956860e04df519c87c44cb8f926be07e79f2791d7cf02926d7`
- #5: `b327d4d6-aab3-41ab-a1f0-b066a44dad86` | 2026-07-31T06:27:56.000Z | REVIEW/global_figure_evidence_verified_preexisting | incident=`8ff5b466-6718-4b26-afcd-e4d4cc238452` | lesson_key=`baseline-behavior-must-not-be-released-as-remediation` | event_sha256=`59b810ac808c59671982b3cda920116c45ec42243c673fac6eefdfdf2031966c`
- #6: `3a38dafc-1e3f-4409-b7e3-2c25103e3cb4` | 2026-07-31T06:27:56.000Z | REVIEW/proposal_ready_diagnosis_not_applicable | incident=`9aac0586-f9d6-45b2-8129-ccc6c19a789f` | lesson_key=`diagnosis-must-be-reproduced-before-remediation` | event_sha256=`41345f516e375c10f208caf8731a39e837533d2a2e11245077d653a55b5f253a`
- #7: `86c9f66e-3862-4a30-82f4-b3db5003d17c` | 2026-07-31T06:27:56.000Z | REVIEW/covariance_interpretation_verified_preexisting | incident=`2c20a717-147f-4c09-9b91-df8a0037ab5e` | lesson_key=`model-protocol-boundaries-require-honest-claims` | event_sha256=`f0072427aa63b5414b58751879c03f79eb62aedc11719cb025fd2f90feea69f0`
- #8: `6b732e1c-85cb-4091-8875-c0ec62526ac1` | 2026-07-31T06:27:56.000Z | REVIEW/global_workflow_answer_verified_preexisting | incident=`33c552d6-6d98-4cec-b651-5bb71a4f91c9` | lesson_key=`bounded-agent-paths-need-call-count-evidence` | event_sha256=`17108345c385e127455be060977ad93db55afae994f84dcddced065460c3c6d1`
- #9: `eb8196da-d1a5-476d-be45-78478f87f5f9` | 2026-07-31T06:27:56.000Z | REVIEW/workflow_dependency_shape_verified_preexisting | incident=`11a22915-b003-4bf7-90c8-dff34cf0643a` | lesson_key=`baseline-behavior-must-not-be-released-as-remediation` | event_sha256=`daf4cc0a00cda23ed18aec20381d7d57c3123ec9cd5c71f671d6163ed0ee4192`
- #10: `d727937f-35ef-4876-a333-28d238b192a8` | 2026-07-31T06:27:56.000Z | ERROR/outside_sandbox_gate_unavailable | incident=`80efaa5f-8307-42d5-aefb-bab67ed95eb2` | lesson_key=`full-gate-requires-non-nested-seatbelt` | event_sha256=`e6cc742cf6106b0ac7c92981710ed512572a3daf6e89edfde8d2da6a6ce1d152`
- #11: `7a435401-9cfc-46e9-bf9e-e852e3022e60` | 2026-07-31T08:00:00.000Z | ERROR/outside_sandbox_gate_unavailable | incident=`80efaa5f-8307-42d5-aefb-bab67ed95eb2` | lesson_key=`gate-requires-non-nested-sandbox` | event_sha256=`df59b548974bac37ba2a3cca7b4a0b6a41207356953793fc7ec9a625633dc24d`
- #12: `171f5a4a-ddbe-4d25-815b-6829166d7626` | 2026-07-31T08:00:00.000Z | GATE/v1_8_4_release_gate_on_host | incident=`926517bf-62cf-47df-ab5b-f3d64faa677c` | lesson_key=`v1-8-4-release-gate-on-host` | event_sha256=`76652fe4c977a712a0bc720b2347c7020ab651d77d96110cea0d515ffb9c3388`
- #13: `e4319d1d-eb54-424d-8def-beb621ba91d9` | 2026-07-31T08:10:00.000Z | STATE_CHANGE/reopened_incident_truth_completed | incident=`79bfe6ff-1a8e-4329-839b-fe0d8f81c9d3` | lesson_key=`verified-preexisting-is-not-remediated` | event_sha256=`322c768580ef09fecaf8cd86e24817fc43f870ef3fa59c241d92c3e0d48b3ca9`
