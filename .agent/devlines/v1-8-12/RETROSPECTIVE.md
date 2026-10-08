# Retrospective — v1-8-12

## Goal

# v1.8.12 — 基础加固：本地服务安全、证据存放、生成类型、CLI 与分层  基线：main \`7d176e1f\`（v1.8.11 发布 + 收尾仪式）。来源：\`followups/BACKLOG.md\` §0.4（v1.8.11 发版后自检）； 交接 \`handoffs/2026-10-07-v1.8.12-kickoff.md\`；用户 2026-10-07 决定先做本版、再做 v1.9.0 界面重做。  ## 一句话目标  堵住本地服务可被任意网页驱动的漏洞，让证据不再撑大仓库和磁盘，并为 v1.9.0 新界面准备好生成的 API 类型、 从能力目录推导的 CLI 和干净的合同分层。  ## 现状（2026-10-07 核实）  - 后端没有任何中间件：外来 Host、外来 Origin 的请求都返回 200（读服务商配置、新建项目均实测）；API key 不明文返回。   前端开发服务器是 Vite 5.4.21，默认已拒绝外来 Host；界面经 Vite 代理访问 \`:8000\`（\`changeOrigin\` 改写 Host，Origin 原样转发）。   缺口是直接访问 \`:8000\`：DNS rebinding 可同源读写；\`/runs\` 等表单上传接口可被跨站提交（不触发预检）。 - 仓库一个版本从 32 MB 涨到 84 MB；\`local/\` 下测试证据每次运行都复制、从不清理。 - 前端类型手写（\`api.ts\` 60 个、\`notebook/contracts.ts\` 50 个）；CLI 缺 \`model_options\`、加权、后估计、导出；   \`ModelFamilyContract\` 定义在 \`agent/\`，被 engine、orchestrator、admission 反向依赖；共享代码族名分支 165 处。  ## 范围（按顺序交付，每步单独提交并验收）  | # | ID | 交付 | 验收场景 | |---|---|---|---| | 1 | V1812-LOCAL-API-SECURITY（P0） | ① Host 白名单：只接受 \`127.0.0.1\`、\`localhost\`、\`[::1]\`（含端口），可用环境变量追加。② 改状态的请求（POST/PUT/PATCH/DELETE）：带 Origin 时必须在允许列表（默认本机 UI 源，可配置），同时拒绝 \`Sec-Fetch-Site: cross-site\`；不带 Origin 的本机客户端（CLI、脚本）照常。③ 审计有副作用的 GET 并改正。④ 拒绝时返回明确的错误码与原因，记入外发审计。⑤ 回归测试覆盖：外来 Host、外来 Origin 的 JSON 与表单提交、\`cross-site\`、CLI 无 Origin、经 Vite 代理的正常界面流程 | 浏览器经开发服务器正常完成“上传 → 拟合 → 后估计 → 导出”；另起一个其他端口的网页对 \`:8000\` 发表单提交和 fetch，均被拒绝；用伪造 Host 模拟 DNS rebinding 被拒绝 | | 2 | V1812-LOCAL-EVIDENCE-RETENTION（P1） | 测试与评测写入 \`local/\` 的证据按类别只保留最近 N 次（默认 N 待定）；LMM 准入测试不再每次整目录复制，只在失败或显式要求时保留 | 连跑三次相关测试，\`local/\` 对应目录不增长超过 N 份 | | 3 | V1812-REPO-EVIDENCE-POLICY（P1） | 规范：大体量证据不入库，仓库只留清单与哈希；新增“每版新增入库证据体积”守卫测试；评估证据与回归测试分目录（\`tests/eval_*\` 不被默认收集的脚本挪出 \`tests/\` 收集面） | 守卫测试在新增超额证据时失败并给出位置 | | 4 | V1812-OPENAPI-TYPES（P1） | 由 FastAPI 的 OpenAPI 生成 TypeScript 类型；\`api.ts\`、\`notebook/contracts.ts\` 的接口类型改为引用生成结果；漂移测试（后端改了接口而前端类型未重新生成即失败） | tsc 通过；故意改一个后端返回字段，漂移测试失败 | | 5 | V1812-CLI-FROM-CATALOG（P1） | CLI 参数从能力目录生成；补 \`--model-options\`（JSON）、加权、\`postestimation\` 与 \`export-script\` 子命令 | 命令行完成：负二项 NB1 → Wald → 导出 Stata 脚本并本机实跑通过 | | 6 | V1812-CONTRACT-LAYERING（P2） | \`ModelFamilyContract\` 与族合同表移到 \`contracts/model/\`；engine、orchestrator、admission 不再导入 \`agent/\` | 分层守卫测试：下层模块导入 \`agent\` 即失败 | | 7 | V1812-FAMILY-LITERAL-DOWN（P2） | 族名分支棘轮从 165 降到 ≤ 145（优先 \`workflow_contracts.py\`、\`notebook/vocabulary.py\`） | 棘轮测试基线下调 | | 8 | 可选 | V1811-PUBLIC-TERM-QUOTE 修复；V1811-LMM-REMAINING 中“可读项名”；拆分 \`context_tools.py\`（按工具类别） | 各自测试 |  ## 不在本版  界面重做、CSS 架构、深色模式、多语言、前端大文件拆分、LMM 完整固定效应卡片（v1.9.0）；LMM 的 ML 似然比检验与边际效应对照； Linux 隔离方案；wild cluster bootstrap、双向聚类。  ## 硬约束  - **安全**：默认拒绝；放行规则只认显式白名单；不得因兼容性放宽；外来请求被拒时不泄露内部信息。 - **不退化**：v1.8.11 已有界面、Agent、模型族、脚本导出、外发管控与三档主题全部保留。 - **性能预算**：中间件每个请求开销 < 1 ms；后端测试总时长 ≤ 20:09；CLI 生成参数不影响启动（< 0.5 s）。 - **秘密值**：Stata 日志入库前脱敏；不在入库文件里写原始日志 SHA；推送受 \`.git/hooks/pre-push\` 护栏约束。  ## 验证  - 先写失败测试再修；后端 \`PYTHONPATH=backend\`；前端 \`tsc\` 与相关 vitest。 - 第 1、5 步做浏览器 / 命令行真实验收；第 1 步另做“外来网页”实测。 - 发版前：宿主 full gate（带耗时记录），Claude 两轮自审。  ## 已知门槛  仅本机 macOS 验证；LMM 依赖宿主隔离，gate 在宿主终端跑；merge / tag / push / Release 需用户授权。  ## 开发线  worktree \`.worktrees/workbench-v1.8.12\`（分支 \`workbench-v1.8.12\`），devline \`v1-8-12\`，known gate \`scripts/gate.sh --full\`。  ## 确认记录  - 2026-10-07（用户）：先做 v1.8.12 加固、再做 v1.9.0 界面重做。 - 2026-10-07（objective 评审，用户逐项确认）：   - **会话令牌本版不做**：Host 白名单 + Origin / \`Sec-Fetch-Site\` 校验已挡住 DNS rebinding 与跨站提交；后端改为非回环监听或打包发布时再加令牌。   - **\`local/\` 测试证据每类保留最近 3 份**，失败那次始终保留；只限测试与评测自己写的证据目录，是“绝不自动删”的有限例外。   - **类型生成用 \`openapi-typescript\`**（新增一个 npm 开发依赖，装在主仓库共享 \`node_modules\`）。   - **已入库的 v1.8.11 证据保留原位**，只约束今后新增。

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `73a9c3c9-1204-47ab-82cd-bdfb7d68226d` | 2026-10-07T14:31:22.393Z | STATE_CHANGE/line_started | incident=`9f0cce99-8219-4bc3-a2ab-3ad67053888f` | lesson_key=`frozen-context-before-start` | event_sha256=`36fb27edc12eb5942144e47fc6028ed545eb122e8077d06fa6aaded9822b1f12`
