# Completion Report — Lane C (UI/UX)：Notebook 表面 + 可见切片

```yaml
work_package: v181-ui-notebook
lane: ui
branch: feat/v181-ui-notebook
worktree: /Users/jiayuanren/项目规划/.worktrees/v181-ui-notebook
contract_lock_commit: 481fc2e30730395093fc0f8699843e1002d64aa3
branch_start_commit: e76f3898941d888467a8630cd11b881d357f46f1
```

按 ADR-PD-001 §10.2 的七项。

---

## 1. 实现了什么、没有实现什么

### 实现

- **Notebook 叙事流 + option 卡片**（`NotebookSurface`）：叙事条目、≤3 张 option
  卡片、超出上限时显式说明"第 4 条未显示"，rank 1 视觉区分（`data-recommended`
  + 左边框），但视觉区分**只是排版**，能否执行仍由后端三条状态轴决定。
- **三条正交状态轴分开可见**（`OptionCard` / `statusAxes.ts`）：
  `lifecycle` / `freshness` / `validation` 各自一枚 chip，各带各自的说明文案，
  没有合成单一 badge。`stale + valid` 的组合会同时显示
  "freshness stale — the context it depends on has moved" 与
  "validation valid — valid for the context it was generated against"。
- **stale 的诚实呈现**：`executability()` 对 `stale` / `revalidating` /
  `invalid` / `unvalidated` / 终态 lifecycle 一律返回不可执行，
  "Review and confirm" 按钮 disabled，并渲染具体阻断原因；只有 `stale` 才启用
  "Request revalidation"。系统不会自动把 stale 刷成 fresh（spec §4.3）。
- **确认前的 PlanDiff 与 required artifact 预期**（`PlanDiffConfirmation`）：
  字段级 diff（`from → to`，缺省显示 `(unset)`）、required / optional 产物分列、
  钉死的 `option_id + option_revision + proposal_id + proposal_revision`，
  以及"完成时会检查哪些维度、不会检查哪些维度"。
- **执行后的契约满足情况**：`ArtifactContractOutcome` 由后端给出，卡片逐条渲染
  `expected N · observed M · satisfied / not satisfied · ISSUE_CODE`，
  并把 `execution_status` 与 `validation_status` 作为两个维度并列显示
  （spec §5.3）。`执行成功 + 契约失败` 不渲染成结果，而是渲染
  `notebook-contract-failure`："this is not a result"。
- **六态可见**：loading / error / empty / pending / confirmation / success，
  外加第七种"执行成功但契约失败"的诚实态。`data-state` 属性同步标注，便于 Lane D
  的 E2E 断言。
- **选中文本交互（Gate 6）**（`SelectionActions`）：加入提问 / 解释 / 定向追问 /
  存为备注 / 存为 deferred option 五个动作，每个动作把选中文本原文与
  `source_ref` 一起回传；deferred 动作明确标注为"存为 deferred option"，
  不是执行入口。
- **可见切片**（`ContextSlicePanel`）：
  - 两个 hash 分列显示且附注"只有第二个 gate 执行"；
  - `omissions` 渲染成 `artifact_summaries: 5 of 59 included, 54 omitted
    (section_budget_exceeded)` + 逐类型明细 `36 time_series_json omitted`；
  - 全量 artifact type counts（被截断的那一层仍保留计数）；
  - 逐 section 的 `used / budget bytes` 与总计；
  - `source_manifest`（source_ref / revision / 选择原因 / 是否 never truncated）；
  - trace 决策链按 `sequence` 渲染 `#N event_type · summary · occurred_at`，
    事件类型取自 spec §13.3 的清单，并附注"记录的是发生了什么，不是对错判断"
    （spec §13.3 的 ⚠️）。
- **合同边界解析器**（`contracts.ts`）：`NotebookOptionRevision@1.0` /
  `OptionExecution@1.0` / `ArtifactContract@1.0` / `ETSResultContract@1.0`
  在进入组件前做版本、枚举、类型校验，不匹配就抛错而不是渲染半空卡片；
  `schema_ref` 在解析阶段直接拒为 `ARTIFACT_SCHEMA_CONTRACT_UNSUPPORTED`
  （spec §5.3），不接受后静默忽略。

### 没有实现（有意）

- 未把 Notebook 挂进任何路由 / 布局。挂载点位于本 Lane 不拥有的文件
  （`WorkbenchRouteContainer` / `WorkbenchMain` / `AgentSurfaceContext`），
  按 work order 的 `owned_files` 不能改。为此导出了 `frontend/src/notebook/index.ts`
  作为单一挂载入口，Integration 一行 import 即可接入。
- 未接任何真实 endpoint。所有组件是纯组件，数据从 props 进；换数据源是 adapter 的事。
- 未做浏览器 E2E 的通过判定（属于 Lane D）。
- 前端不重算任何系数、诊断、比较或结论；`success` 卡片逐字渲染 ETS packet
  （`ETS(A,Ad,N)` / `n_obs 2610` / `excluded 3 (missing_endog 3)` / AIC / BIC /
  `converged` / `result_identity`）。唯一的算术是"omitted = available − included"
  这类展示层减法。

---

## 2. 精确修改的文件和提交

全部为**新增**，全部落在 `owned_files` 内（`frontend/src/notebook/**`、
`frontend/src/**/*.notebook.test.tsx`）；无一个既有文件被修改。

```
frontend/src/notebook/contracts.ts
frontend/src/notebook/statusAxes.ts
frontend/src/notebook/OptionCard.tsx
frontend/src/notebook/PlanDiffConfirmation.tsx
frontend/src/notebook/SelectionActions.tsx
frontend/src/notebook/ContextSlicePanel.tsx
frontend/src/notebook/NotebookSurface.tsx
frontend/src/notebook/notebook.css
frontend/src/notebook/index.ts
frontend/src/notebook/fixtures/canonicalMocks.ts
frontend/src/notebook/fixtures/provisionalContextSlice.ts
frontend/src/notebook/contracts.notebook.test.tsx
frontend/src/notebook/OptionCard.notebook.test.tsx
frontend/src/notebook/ContextSlicePanel.notebook.test.tsx
frontend/src/notebook/SelectionActions.notebook.test.tsx
frontend/src/notebook/NotebookSurface.notebook.test.tsx
docs/superpowers/release-trains/v1.8.1/evidence/completion-report-lane-c.md
```

提交：见分支 `feat/v181-ui-notebook` 上位于 `e76f389` 之上的单个 commit
`feat(v1.8.1/ui): notebook surface, three status axes and the visible slice`。

---

## 3. 是否修改合同、使用哪个 lock

- lock：`481fc2e30730395093fc0f8699843e1002d64aa3`（work order 声明），
  分支起点 `e76f389`。
- **没有修改任何合同**。`backend/**` 一行未碰；
  `backend/workbench/contracts/agent/notebook_option.py` 只读参考、未 import。
- `frontend/src/notebook/contracts.ts` 是该合同的**只读 TS 镜像**，不是新合同：
  版本常量、枚举、字段名逐一对齐 Python 端。它是 UI 侧的边界校验，
  不是第二份事实来源。

### Contract Change Request

**CCR-C1 — 可见切片缺 canonical mock（阻塞"只用 canonical mock"这条验收）**

work order 的 `consumes` 列了 `NotebookPlanningContextV1` 的
`budget_report` / `omissions`，`produces` 要求把它们做成可见切片；
spec §13 还要求 trace 决策链可核对。但
`tests/fixtures/contracts/v181/` 在 lock `481fc2e` 只有三个文件：
`notebook_option_revision.json` / `option_execution.json` / `ets_result.json`。
**`NotebookPlanningContextV1` 与 `agent-trace-event/v1` 没有 canonical mock。**

处理（ADR §11 "记录 → 最小复现 → 继续可推进的工作"）：没有停摆，而是按 spec
§12.3 / §13.2 的文本落了 TS 类型，并新增
`frontend/src/notebook/fixtures/provisionalContextSlice.ts`，
数值直接采用 spec §12.3 自己标定的 v1.8.0 真机口径（59 artifacts / 36 个
`time_series_json` / ≈24 KB 预算）。文件名带 `provisional`、文件头写明
"此文件在 canonical mock 落地后必须删除"，避免被误当成锁定合同。

**请求 Integration 补锁三样：**

1. `NotebookPlanningContextV1@1.0` 的 canonical mock，至少含
   `context_id` / `context_profile` / `generation_context_hash` /
   `freshness_dependency_fingerprint` / `omissions[]`（含逐类型明细）/
   `budget_report`（逐 section used/budget）/ `source_manifest`；
2. `agent-trace-event/v1` 的 canonical mock（§13.3 的事件序列，
   至少 `context.compiled → agent.plan.* → option.revision.created →
   proposal.validation.completed → user.decision.recorded`）；
3. **artifact contract 的执行后判定 packet**（spec §5.4 的
   `validation_profile` / `validation_status` / `checked_dimensions` /
   `not_evaluated_dimensions`，外加逐 artifact 的 `observed_count` /
   `satisfied` / `issue_code`）。目前它在 UI 侧以
   `ArtifactContractOutcome` 存在，但同样没有 canonical mock；
   若后端定成别的形状，卡片的"执行后是否满足"这一段需要重接。

另有一条**小口径歧义**（不阻塞）：canonical mock 的 `ArtifactContract` 用的是
`expected[] + count`，spec §5.2 写的是 `expectations[] + min_count/max_count +
contract_profile`。本 Lane 按 **canonical mock**（即 Python 合同）实现，
建议 Integration 把 spec §5.2 的文本改成与锁定合同一致，免得下一个 Lane 照 spec
写出对不上的字段。

---

## 4. 执行过的命令及精确结果

### 实现前的可失败验收证据（work order `preimplementation_acceptance_evidence`）

```
$ cd frontend && npx vitest run src/notebook
 Test Files  5 failed (5)
      Tests  no tests
Error: Failed to resolve import "./contracts" from
  "src/notebook/contracts.notebook.test.tsx". Does the file exist?
```

与 work order 的 `initial_observation: "组件不存在"` 一致：五个测试文件全部无法解析，
因为组件尚未存在。测试先写、后实现。

### 实现后

```
$ cd frontend && npx vitest run src/notebook
 ✓ src/notebook/contracts.notebook.test.tsx        (9 tests)
 ✓ src/notebook/ContextSlicePanel.notebook.test.tsx (7 tests)
 ✓ src/notebook/OptionCard.notebook.test.tsx       (11 tests)
 ✓ src/notebook/NotebookSurface.notebook.test.tsx  (10 tests)
 ✓ src/notebook/SelectionActions.notebook.test.tsx  (4 tests)

 Test Files  5 passed (5)
      Tests  41 passed (41)
   Duration  704ms
```

```
$ cd frontend && npx tsc --noEmit
（无输出，exit 0）
```

```
$ git diff --check
（无输出）
```

### 变异检查（证明测试不是"确认已写好的东西"）

把 `statusAxes.ts` 里 stale 的分支改成永假（即让 stale option 变成可直接执行），
重跑：

```
 × OptionCard — a stale option is never directly executable
   > disables execution and says revalidation is required
 Tests  1 failed | 40 passed (41)
```

随即还原，41/41 恢复通过。这条断言确实咬住了"stale 不得显示为可执行"这条硬规则。

### 未执行

- `scripts/gate.sh`：按任务说明禁止（互斥、其它 Lane 在跑）。
- 前端全量 `npx vitest run`：本 Lane 只新增文件、没有既有模块 import
  `src/notebook/**`，不存在回归面；且并行波次下全量 suite 是重负载
  （见项目既有教训：全量 gate 叠跑曾把内存打到 40G）。Lane-local gate 与
  `tsc --noEmit` 已覆盖本包。**建议 Integration 在合并前跑一次全量 FE suite。**

---

## 5. 已知限制、失败路径和性能观测

1. **可见切片依赖 provisional fixture**（CCR-C1）。类型形状来自 spec 文本，
   不是锁定合同；后端一旦定形，`contracts.ts` 里
   `NotebookContextSlice` / `TraceEvent` 及对应测试需要重接。
2. **未挂进应用，因此没有真机可见性**。这与"可见切片提前做"的初衷有张力：
   本 Lane 交付的是可挂载的组件，真正的人眼核对要等 Integration 挂载后
   或 Lane D 的 E2E。这不是能在本 Lane 内解决的问题——挂载点文件不属于本 Lane。
3. **`ArtifactContractOutcome` 是 UI 侧先行定义的形状**，后端未锁。
4. **`option-execute` 的 testid 在多卡片场景下不唯一**（每张卡片一个）。
   Lane D 写 E2E 时请用 `option-card-<option_id>` 作用域内定位，
   或提出改成 `option-execute-<option_id>` 的请求。
5. **`canonicalMocks.ts` 用 `node:fs` 读仓库根的 fixture**，只能在 vitest/node
   下运行；它是测试支撑文件，生产代码不 import。这样做的原因是
   `frontend/tsconfig.json` 未开 `resolveJsonModule`，而 tsconfig 不在本 Lane
   的 `owned_files` 内——**不改不属于自己的文件**优先于图省事。
   好处是测试直接咬住 canonical JSON，fixture 改形状会立即失败，
   而不是测一份漂移了的手抄副本。
6. 性能：本包测试 704 ms / 41 tests，`tsc --noEmit` 全项目通过；无新增依赖，
   `node_modules` 未动（共享 symlink）。

---

## 6. 潜在集成风险、建议合并顺序和回滚方式

**风险**

- 若 Gate 2（Context Compiler）/ Gate 3（Trace）落地后的字段名与
  `provisionalContextSlice` 不同，可见切片需重接（局部，仅
  `ContextSlicePanel` + 类型 + 一个 fixture）。
- 若后端 artifact 验证结果的形状与 `ArtifactContractOutcome` 不同，
  `OptionCard` 的 outcome 段需重接。
- 与 Integration 的挂载工作可能在同一批次落地；本包不含挂载，因此**不会**与
  Integration 对 `AgentSurfaceContext.tsx` / 路由文件的改动冲突。

**建议合并顺序**：本包可**先合**，且可与其它 Lane 任意顺序合并——
纯新增、零共享文件、零既有文件改动，冲突面为空。Integration 的挂载改动
应排在本包之后。

**回滚方式**：`git revert` 该单个 commit，或直接删除 `frontend/src/notebook/`。
因为没有任何既有模块 import 它，删除后前端行为与合并前逐字节等价。

---

## 7. 是否触碰 forbidden/protected files

**否。**

- `backend/**`：未读写（仅按 `read_only_contracts` 阅读
  `backend/workbench/contracts/agent/notebook_option.py` 作参考，未 import、未修改）。
- `frontend/src/workbench/agent/AgentSurfaceContext.tsx`：未触碰。
- `scripts/gate.sh`：未触碰、未执行。
- `frontend/package.json` / `node_modules`：未触碰，无依赖安装或升级。
- `frontend/tsconfig.json`：未触碰（见 §5.5，为此绕开了 JSON import）。
- 未 push、未开 PR、未 merge、未打 tag。
