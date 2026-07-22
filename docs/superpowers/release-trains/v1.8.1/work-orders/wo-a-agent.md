# Work Order A — Agent Lane：Notebook Option 生成与生命周期

```yaml
work_package: v181-agent-notebook-options
lane: agent
release_baseline_commit: d86bf30195ccf315ce9e9ae3948722ac64202b28
integration_base_commit: d86bf30195ccf315ce9e9ae3948722ac64202b28
contract_lock_commit: __C1__
branch_start_commit: __C1__

owned_files:
  - backend/workbench/agent/notebook/**
  - backend/workbench/http/notebook_routes.py
  - tests/test_notebook_*.py

read_only_contracts:
  - backend/workbench/contracts/agent/notebook_option.py
  - backend/workbench/contracts/model/ets.py
  - backend/workbench/contracts/common/**
  - backend/workbench/agent/context_compiler.py
  - backend/workbench/agent/trace.py
  - backend/workbench/lineage/run_family.py

forbidden_files:
  - backend/workbench/agent/orchestrator.py
  - backend/workbench/agent/operations.py
  - backend/workbench/engine/registry.py
  - backend/workbench/engine/capabilities.py
  - backend/workbench/engine/packs/**
  - backend/workbench/graph_store.py
  - frontend/**
  - scripts/gate.sh
  - tests/test_honest_did_adversarial.py
  - tests/test_honest_did_sd_adversarial.py

consumes:
  - NotebookOptionRevision@1.0
  - OptionExecution@1.0
  - ArtifactContract@1.0
  - NotebookPlanningContextV1 (Gate 2)
  - agent-trace-event/v1 (Gate 3)

produces:
  - Notebook 对象与持久化（一 notebook 一 run_family_id）
  - NotebookOption / NotebookOptionRevision 的 append-only 存储
  - 读时 freshness 求值 + confirm 时 fail-closed 拒绝
  - 每批 ≤3 条、至多一条 rank 1

preimplementation_acceptance_evidence:
  kind: failing test
  command: "pytest tests/test_notebook_option_lifecycle.py -q"
  initial_observation: "模块不存在 / 断言失败，非语法错误"

acceptance:
  - spec §9.1 criterion 1（无 Run 的 Notebook）现在必须真正通过，
    并删除 tests/test_run_family_acceptance.py 里那条 xfail(strict=True)
  - 每批最多 3 条、至多一条 rank 1、同批 canonical proposal hash 不重复
  - 旧 option_revision 永不被覆盖；stale 重新验证产生新 revision
  - 读时判 fresh 不构成执行许可：读时 fresh、确认时上游已变仍须拒绝
  - sibling option 不得互相判 stale（spec §4.0 自引用命门）
  - 跨 family 的 run 设为 active head → RUN_FAMILY_MISMATCH
  - 每条决策链写出 Gate 3 的 12 类 trace 事件

non_goals:
  - 实现 estimator 或任何模型（Lane B）
  - 任何前端实现（Lane C）
  - 修改 Graph 持久化结构
  - 无确认的连续分支执行
  - 调用真实 LLM provider
```

## 关键约束

**1. Notebook 必须能先于任何 Run 存在**（DEC-NB-001）。创建 notebook 时：
若项目已迁移，绑定既有 family；未迁移则先建 family（`origin="notebook"`）。
按用户 2026-07-22 拍板，**建 Notebook 时自动触发迁移**——
调 `migrate_project_families()`，不要自己写第二套迁移。

**2. 两个 hash 不可合一。** `NotebookOptionRevision` 契约在 C1 已经强制
两者不得相等。执行门禁**只**比对 `freshness_dependency_fingerprint`；
`generation_context_hash` 只作证据。合并它们会让新生成的 option 自己把自己判 stale。

**3. 用户决策不是标签。** 写 trace 时 `user.decision.recorded` 的 payload
不得含 reward/label/correct/score——Gate 3 的 schema 会直接拒绝，别绕过它。
