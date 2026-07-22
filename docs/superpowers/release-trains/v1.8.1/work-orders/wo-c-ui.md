# Work Order C — UI/UX Lane：Notebook 表面 + 可见切片

```yaml
work_package: v181-ui-notebook
lane: ui
release_baseline_commit: d86bf30195ccf315ce9e9ae3948722ac64202b28
integration_base_commit: d86bf30195ccf315ce9e9ae3948722ac64202b28
contract_lock_commit: __C1__
branch_start_commit: __C1__

owned_files:
  - frontend/src/notebook/**
  - frontend/src/workbench/notebook/**
  - frontend/src/**/*.notebook.test.tsx

read_only_contracts:
  - tests/fixtures/contracts/v181/**            # canonical mock，唯一数据源
  - backend/workbench/contracts/agent/notebook_option.py   # 只读参考，不 import

forbidden_files:
  - backend/**
  - frontend/src/workbench/agent/AgentSurfaceContext.tsx
  - scripts/gate.sh

consumes:
  - NotebookOptionRevision@1.0 (mock)
  - ArtifactContract@1.0 (mock)
  - ETSResultContract@1.0 (mock)
  - NotebookPlanningContextV1 的 budget_report / omissions（可见切片用）

produces:
  - Notebook 视图：叙事流 + option 卡片（≤3，rank 1 视觉区分）
  - 三条正交状态轴的可见状态：lifecycle / freshness / validation
  - stale 的诚实呈现（不得把 stale 显示为可直接执行）
  - 确认前的 PlanDiff 与 required artifact 预期
  - 选中文本交互（Gate 6）：加入提问 / 解释 / 定向追问 / 存为备注或 deferred option
  - **可见切片**：把 Agent 实际看到的上下文摘要与 trace 决策链显示出来
    （"5 of 59 artifacts, 36 time_series_json omitted" 这类信息必须可见）

preimplementation_acceptance_evidence:
  kind: failing component test
  command: "npx vitest run src/notebook"
  initial_observation: "组件不存在"

acceptance:
  - 只依赖 tests/fixtures/contracts/v181/ 的 mock，不读后端内部 JSON
  - loading / error / empty / pending / confirmation / success 六态可见
  - stale option 不能显示为可直接执行；必须提示需重新验证
  - option 卡片显示 required artifact 预期，执行后显示是否满足
  - 可见切片让"Agent 看到了什么"与"当时发生了什么"可被人眼核对
  - tsc --noEmit 干净

non_goals:
  - 在前端重算任何系数、诊断、比较或结论
  - 依赖未版本化的后端内部字段
  - 跳过 confirmation，或把 pending/error 显示成成功
  - 用视觉"推荐"替代后端 validator 判断
  - 浏览器 E2E 的通过判定（属于 Lane D）
```

## 可见切片为什么在这条 Lane

用户 2026-07-22 拍板：前三个 Gate 全是地基，用户可见的东西要到 Gate 4 才出现，
而这个项目历史上最有效的纠错手段是真机验收（v1.8.0 抓到的 5 个缺陷全部来自真机，
确定性测试一个都没盖住）。因此把"Agent 看到什么 / 当时发生了什么"提前做成可见，
不等 Gate 4 全部完成。
