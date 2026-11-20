# 下一版开工交接（v1.9.1 发布后）

> 写于 2026-11-20。新对话开工先读本文件，再读 `AGENTS.md`、`docs/superpowers/followups/BACKLOG.md` §0.0。
> 本文件只记“从哪里接、怎么开工、哪些坑”；下一版做什么由用户确认 objective 后才定。

## 1. 现在的状态

| 项 | 值 |
|---|---|
| 最新发布 | **v1.9.1**（2026-11-20）：main squash `10e3a175`，tag `v1.9.1`，冻结点 `de0dfba3` |
| 发布说明 / 完成报告 | `docs/releases/v1.9.1-release-notes.md`、`docs/releases/v1.9.1-completion.md` |
| 发版规则 | `docs/superpowers/plans/2026-11-20-v1.9.1-release-rules.md`（之后版本沿用：冻结、硬门/软指标、置信区间判资源、三层评测、决定默认执行） |
| 通过的 gate | `.worktrees/eval-v191-frozen/local/gate/20261120T130834-0brn_0i8`（后端 14,280，golden 23，前端 2,336，tsc，ESLint） |
| devline | `v1-9-1` 已 COMPLETED |
| 前端 lint | ESLint 10.15.0 + typescript-eslint 8.73.0 是 v1.9.1 的开发依赖；合并后主仓库 `frontend/package.json` 已含。**共享的 `frontend/node_modules` 在主仓库**，worktree 里不跑 npm |

## 2. 下一版候选（用户尚未选定，先问）

1. **v1.9.1 遗留的正式评测**（BACKLOG `V191-M5-FORMAL`）：开发集 198 位置、pass³、留出（只跑一次）、外部、复现、消融。建议作为第一个里程碑，用夜间自动循环在免费 NVIDIA 线路上分批跑，pass³ 不可能达标即停。
2. **v1.9.2 原定范围**：一般推断内核、HC/CR 默认策略、野自助法、各族最强默认、Rust 原生组件。
3. 每任务 prompt 体积、工具被拒率、“说继续”为 0（BACKLOG `V191-PROMPT-SIZE`、`V191-REFUSALS`、`V191-NUDGE-ZERO`）。

## 3. 开工流程

1. 用户确认 objective；按“只留最近 5 版”请用户决定退役哪个 worktree（`workbench-v1.8.8-final` 永久保留）。
2. 从 tag `v1.9.1` 开 `.worktrees/workbench-v1.9.2`，跑 `scripts/link-shared-deps.sh`；原生内核要在新 worktree 里重建（`scripts/build_native.py`，`--check` 验证）。
3. `scripts/devline_control.py start` 开一条 `v1-9-2` 线（基线 SHA 写 tag `v1.9.1` 的提交）。
4. 仓库体积上限回到默认 5 MiB（v1.9.1 的 8 MiB 是该版特批）。

## 4. 坑

- **硬门只认冻结 SHA 的干净检出**：v1.9.1 有一次提交漏暂存测试文件，开发工作树里测试照样通过。
- gate 必须在宿主终端独占运行（嵌套沙箱假报 containment 失败）；冻结检出要有 `local/perf-inputs`（用 `cp -c` 克隆，不复制）。
- 两个会话（Claude 与 Codex）不同时写同一个工作树；交给 Codex 的工作走 JSON 清单 + `scripts/handoff_check.py`。
- 证据体积检查以“最近的发布 tag”为基线，发版后在 main 上补的收尾文档也会算进下一版；v1.9.1 发版提交因此报 1,001/1,000 个文件（多的 2 个是 v1.9.0 收尾文档）。可考虑让检查以上一版 squash 提交而非 tag 为基线。
- 磁盘：`du` 会把 APFS 克隆重复计数；判断真实占用看 `df` 前后差。macOS 系统更新资产（`/System/Library/AssetsV2`）会占 20 GB 左右。
- 免费 NVIDIA 线路：评测驱动带断点续跑、限速退避和未知 usage 即停；正式准入要求空闲 ≥ 25 GiB。
