# v1.6.9 起手 handoff — 前置债清理（Preflight Debt Cleanup）

> 写于 2026-07-09。目标读者：Claude 接手在 **v1.6.9 worktree 分支里**实现本版。
> 当前 checkout：`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.6.9`，branch `workbench-v1.6.9`，从 **main `71e2759`** 起（干净起跑线）。
> 依赖：已用 `scripts/link-shared-deps.sh` 符号链接主仓库 `.venv` + `frontend/node_modules`（勿在此 worktree 重装）。

---

## 0. 一句话

v1.6.9 = **前置债清理版**，不是产品新功能版。把版本级 backlog（followups §4.1/§1/§5）里的工程债，和架构债台账（`roadmap/architecture-debt.md`）里**低风险高 ROI** 的两项，一起清掉，给下一版（B：图内对比 / 节点 AskAI / 引用报告）铺干净地基。**B 顺延 v1.6.10+**，因为它三样都要后端新契约，是大工程，且 AskAI 后端选型（roadmap §5 开放问题 #3）还没拍板。

**范围已由用户拍板（2026-07-09）：全三束（Bundle 1+2+3）。**

## 1. 起手前必读的三份源文档

- `docs/superpowers/followups/v1.6.8-followups.md` — live 滚动 backlog（本版要清的债在 §1 / §4.1 / §5）
- `docs/superpowers/roadmap/architecture-debt.md` — 架构债台账（D1 前端对称项 + D3 是本版候选）
- `docs/superpowers/roadmap/2026-07-01-unified-graph-workbench-roadmap.md` — 产品主线方向（解释 B 为何顺延）

## 2. v1.6.9 范围（拍板 = 全三束）

### Bundle 1 — rerun/轮询状态机（用户价值最高，且逼出前端对称拆分）
- **rerun-child 统一到 run-pending 状态机**（followups §4.1 第 1 条）：`handleExecuteDraft` 目前 execute POST 返回即移除 draft 节点并 refetch，但 run 是后台异步的。长 run（honest-DID ~157s）期间新 head 未入 index、`pendingFocusTarget` 4s（20×200ms）就放弃，用户观感是"draft 消失了、什么都没发生"。genesis 路径 v1.6.8 已修（running 不烧重试预算 + failed/blocked 标记 draft 失败）；**rerun 路径要统一到同一个 run-pending 状态机，而非两套轮询**。
- **`WorkbenchRouteContainer` 拆分**（台账 D1 前端对称项 + followups §4.3）：轮询逻辑就住在这个承重容器里，"本轮轮询修复又 +40 行"已把拆分优先级上调。修 rerun 状态机和拆容器是**同一片代码，一起做**。
- 顺带（followups §4.1）：RUNS rail 30s 轮询延迟（forest index 命中时主动触发 rail refresh）；pending 轮询补 Playwright smoke（fake-timer 单测过脆）。

### Bundle 2 — 后端/CLI 边界对齐（纯透传，ROI 高）
- **`POST /runs` project_root 校验对称**（followups §1）：`/uploads`、`/graph` 已显式校验项目根；`POST /runs` 仍沿旧路径语义。统一成同一套 `PROJECT_NOT_FOUND`/权限边界。
- **D3 CLI 补参数**（台账 D3，ROI 最高）：引擎里 DID/CS/SA/dCDH/IV/Panel 全实现了，但 CLI 只有 `--x --model-type --mode --imputation`，entity/time/treatment/endog/iv 一个都传不进。复用 `_submit_run` 同套 form 解析透传，**不动引擎**，golden 护栏在。

### Bundle 3 — 纯减法 + gate 稳定
- 删 dead `runHistory.tsx` / `RunHistoryPanel`（followups §1）：App 路由倒转后无生产调用方（`RunHistoryRail` 是另一套组件）。先确认无引用再删。
- 修 `useCapabilities.test.tsx` 负载 flake（followups §1）：全量 vitest 偶发只红 `fetches /capabilities`，单跑稳定 → 测试隔离 / 网络 mock 生命周期。
- 修后端 `-k "draft or upload or genesis"` 429 flake（followups §1）：组合选择器偶发 run-slot 泄漏 → 测试清理纪律。
- （可选，同族）REV-3 `classifyError` 误报 network（followups §5）：`useGraphData.ts` 的 `classifyError` 把 adapter 层 bug 误判 network。加 `adapter_error` 分类 + 单测。

### 明确不做（本版排除，避免贪多）
- **api.py 全拆（台账 D1 后端）/ OpenAPI codegen（D6）**：台账纪律「单版本别贪多，D1 或 D6 任一个就够一个版本的重构预算」——各自值一个独立版本，不塞进 v1.6.9。
- **followups §4.2 三条需拍板 UX**（裸 nodeKey / role `X` 二义 / covariance 默认耦合）：不是纯清债，需产品拍板，单列。
- **B：图内对比 / 节点 AskAI / 引用报告** → v1.6.10+。

## 3. 落地纪律（MEMORY 已有，此处备查）

1. **spec → plan → 用户过目 → TDD 实现 → 三级评审（Implementer → Test&QA → Reviewer）→ gate → commit → push → PR**。
2. 每版 commit 后**立即 push** 分支。
3. 子代理用 **`opus`**（haiku/sonnet 在此环境不可用）。
4. Bundle 1 是中等风险（改承重容器 + 状态机），单独 spec + 充分 brainstorm；Bundle 2/3 是小而确定的活。
5. 若碰模型家族（本版 D3 CLI 会碰到 DID/CS/SA/dCDH/IV/Panel），**顺手销掉 followups §4.1 那条「全模型族真机执行 smoke（含估计方程渲染）」债**。

## 4. Gate（必须在 worktree 内跑）

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.6.9
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 <gate 命令>
```

- **铁律**：`LANG=LC_ALL=en_US.UTF-8`，否则中文路径假失败；且必须在 worktree 内跑（主目录无独立依赖，靠符号链接）。
- 看 **golden 0-drift**（数值不漂移）+ **FE / BE 测试数字** + `tsc 0`。
- v1.6.8 gate 基线参照：BE 1351 passed / golden 23 / FE 919 / tsc 0（本版应 ≥ 此，删 dead code 后 FE 数可能略降属正常）。

## 5. 关卡验收点（用户会在这几处喊停检查）

1. **plan 出来时**：范围是否收敛到一个版本装得下（没把 D1 后端全拆 / D6 塞进来）。
2. **gate 绿后、合并前**：**真机 smoke 有没有做**（不是只有单测绿）——尤其 Bundle 1 的 rerun 长 run 窗口期要真机复验"draft 不再消失"，Bundle 2 的 CLI 新参数要真跑一个 DID/IV run。
3. **PR 合并 + tag 后**：确认 **tag peel 指向 merge commit**（v1.6.8 就核过一次：`git rev-parse v1.6.9^{commit}` == merge commit）。

## 6. 协调提醒（重要）

- **桥对话（起手这份 handoff 的对话）保持不动仓库**，除非用户回去让它查东西。v1.6.9 的活全部在**本 worktree 分支**里做，避免两个会话同时改 main 撞车。
- main 此刻干净停在 **`71e2759`**，是干净起跑线。本 handoff + 归档旧 handoff 的改动**提交在 `workbench-v1.6.9` 分支上**（不在 main），随 v1.6.9 PR 走。
- 收尾发版时：本 handoff 按约定移进 `archive/handoff/`；followups 里清掉的债**直接删行**（git 历史留痕，不靠 `[x]`）。

## 7. 前置动作已完成（起手对话已做）

- [x] worktree `.worktrees/workbench-v1.6.9` 从 `71e2759` 建好，branch `workbench-v1.6.9`。
- [x] `scripts/link-shared-deps.sh` 已链接共享 `.venv` + `frontend/node_modules`。
- [x] 旧 v1.6.8 handoff 归档进 `archive/handoff/`（本分支）。
- [x] 本 handoff 写好。
- [ ] （下一步，交给实现对话）brainstorm → spec → plan → 用户过目。
