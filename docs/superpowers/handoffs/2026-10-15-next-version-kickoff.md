# 下一版开工交接（v1.9.0 发布后）

> 写于 2026-10-15。新对话开工先读本文件，再读 `AGENTS.md`、`docs/superpowers/followups/BACKLOG.md` §0.0。
> 本文件只记“从哪里接、怎么开工、哪些坑”；下一版做什么由用户确认 objective 后才定。

## 1. 现在的状态

| 项 | 值 |
|---|---|
| 仓库 | `/Users/jiayuanren/项目规划`（Arboris / Econometrics Workbench），远端 `damndone/Arboris` |
| 最新发布 | **v1.9.0**（2026-10-14）：main squash `402d2d3e`，tag `v1.9.0`；记录提交 `40927bc5` |
| 上一发布 | **v1.8.13**（同日单独发布，未重跑 gate，说明里写明）：main squash `c81fc89f`，tag `v1.8.13` |
| 发布说明 | `docs/releases/v1.9.0-release-notes.md`、`docs/releases/v1.8.13-release-notes.md` |
| 完成报告 | `docs/releases/v1.9.0-completion.md`（末节是 10-13 之后的增量与发布检查） |
| 最近一次通过的 gate | `.worktrees/workbench-v1.9.0/local/gate/20261014T211421-jjhjtobt`（后端 8367 / 15:58，Golden 23，前端 1935，tsc） |
| devline | `v1-8-13`、`v1-9-0` 均已 COMPLETED |
| 设计输入 | `docs/superpowers/specs/2026-10-14-v1.9.0-agent-context-design.md`（Agent 压缩/指令/回忆）、`specs/2026-09-30-composable-capabilities-and-research-workspace-design.md` |

## 2. 下一版候选（用户尚未选定，先问）

按已记录的遗留与方向列出，不代表优先级：

1. **OLS（及其他线性族）HC0–HC3 协方差**：目前 robust 固定 HC1，OLS 选项词表没有 HC3；需要核心估计、结果信封、Stata/R/Python 脚本导出与 R/Stata 数值对照。Agent 现在会如实说明“不支持”。
2. **压缩切分单个超长回合**：之前没有可切分的提问时无法压缩（pi 的做法是拆分回合并合并两段摘要）。1M 窗口 + 200k 预算下罕见。
3. **Agent 继续增强**（参考 pi / Hermes / Codex，见设计文档）：可复用的“分析技能”、界面显示执行计划、Agent 工作中途插话改方向（core 已有 steer/follow_up 队列，界面未接）。
4. **量化研究方向**：产品定位里的下一个垂直方向（AI 驱动的量化研究/策略验证），设计在用户的 Obsidian，需要用户提供。
5. **既有延后**：线性混合模型似然比检验（缺可信比较前提）、NB1 原生 R（缺 glmmTMB）、Linux、会话令牌、大文件技术债（`notebook/service`、`workflow_runtime`、`orchestrator`）。
6. **小项**：手写报告草稿接口一次返回 736 kB（每条证据重复来源信息，需改数据格式）。

## 3. 开工流程（按 AGENTS.md 与历次约定）

1. **先和用户确认版本号与 objective**（写到 `docs/superpowers/objectives/<日期>-v<版本>-objective.md`），获批后才开工。
2. 从 tag `v1.9.0` 开独立工作目录：
   ```bash
   git worktree add .worktrees/workbench-vX.Y.Z -b workbench-vX.Y.Z v1.9.0
   bash scripts/link-shared-deps.sh .worktrees/workbench-vX.Y.Z
   .venv/bin/python scripts/check_dev_env.py
   ```
   **工作目录里绝不 `pip install -e` 或 `npm install`。**
3. 只用 `PYTHONPATH=backend .venv/bin/python scripts/devline_control.py start` 开一条版本线；读生成的 `CONTEXT_PACK.md`、`.agent/development/global_rules.md` 和 v1-9-0 的 `RETROSPECTIVE.md`。
4. 预览端口：在主仓库 `.claude/launch.json` 新增本版条目（已占用 5189–5194、8029–8034、9999；建议 5195/8035），后端设 `WORKBENCH_ALLOWED_ORIGINS=http://127.0.0.1:<前端端口>`。
5. 发布前：宿主终端跑 full gate（独占机器）→ 两轮自审 → 用户授权 → squash 合入 main、tag、push、`gh release create`、versions.md、devline 记录发布并关闭。

## 4. 环境事实（容易踩的坑）

- **gate 必须在宿主终端跑**（嵌套沙箱会假报 containment 失败）。路径含中文，`run_in_terminal` 的命令只能是 ASCII：用 `cwd` 参数指向工作目录，命令写 `time bash scripts/gate.sh --full 2>&1 | tee local/<名>.log`。跑前停掉本版 Vite/uvicorn 预览并确认没有其他 pytest/vitest/gate。
- 共享虚拟环境已装 **`highspy==1.12.0`**（honest-DID 直接调 HiGHS；没有时自动回退 scipy）。
- 模型配置：设置里的 provider 列表（`~/.config/econometrics-workbench/llm-providers.json`）优先于 `llm.env`；当前活动的是 DeepSeek `deepseek-flash`，已标 `supports_1m`。实测窗口 1,048,576；Agent 压缩工作预算默认 200k（`WORKBENCH_AGENT_COMPACT_AT`）。真实调用要花钱，尽量少。
- **结构守卫测试**（改动后常在 gate 里才暴露）：
  - 新增改状态的接口 → 在 `tests/test_analysis_ledger_routes.py` 里登记（写入台账或带理由豁免）。
  - `backend/workbench/agent/` 下的模块不得读 `artifacts_index.json`、`graph.json`、`data_profile.json`（`tests/test_context_compiler_entry_point.py`）；给人用的读取放 `services/`。
  - 新增 Agent 工具 → 在 `backend/workbench/egress.py` 的 `TOOL_CONTENT_CLASSES` 登记，并重生成手册：`PYTHONPATH=backend .venv/bin/python scripts/generate_manual_reference.py`。
  - 后端响应结构变了 → `PYTHONPATH=backend .venv/bin/python scripts/generate_api_types.py`。
  - 前端棘轮：内联样式上限只降不升（降了要同步改 `designTokens.test.ts` 的上限）；没有组件用的 CSS 类、只被测试引用的模块、首屏不该静态导入的模块都会失败（`cssUsage.test.ts`、`moduleUsage.test.ts`、`bundleBoundaries.test.ts`）。
  - 删文件前搜索 `tests/`（含 evidence manifest，它绑定测试文件自身的哈希）。
- devline 事件文件要放在仓库相对路径（如 `local/`），字段含 `event_id`、`preventability`；文字里出现 “token 加空格” 会被当成疑似密钥拒收。
- 浏览器验收：受控输入用真实键入；预览面板隐藏时 `requestAnimationFrame` 不跑；测试数据用项目副本（如 `local/v190-agent-live`）。
- 磁盘只剩约 9 GB（2026-10-14）。

## 5. 待用户决定（v1.9.0 发版后遗留）

- worktree 清理：`workbench-v1.8.13`、`workbench-v1.9.0` 保留还是归档；按“只留最近 5 版”退役更早的（`workbench-v1.8.8-final` 永久保留）；先存 tag 并推送，绝不自动删。
- 废纸篓 `script-export-local-runs-2026-10-14`（旧数据核对证据，已备份到主仓库 `local/archive/`）。
- 是否清理旧 gate 记录与缓存以释放磁盘。

## 6. 新对话开场白（可直接粘贴）

> 继续 Arboris 的下一个版本。先读 `docs/superpowers/handoffs/2026-10-15-next-version-kickoff.md`、`AGENTS.md` 和 `docs/superpowers/followups/BACKLOG.md` §0.0，然后告诉我你理解的现状，再和我确认下一版的版本号和 objective；确认前不要开工作目录或写代码。
