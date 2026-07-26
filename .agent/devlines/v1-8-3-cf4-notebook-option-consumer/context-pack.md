# Frozen Context Pack

Line: `v1-8-3-cf4-notebook-option-consumer`
Baseline SHA: `92914cce8a0a5f0b1df30abff44c4b2b26949148`

## Objective
# v1.8.3 CF4 Notebook Option consumer wiring

将已通过 Capability Factory admission 的 `CapabilityResolutionBinding` 接入
NotebookService 的 Option proposal 生成：由服务端持有的 binding catalog 按
Agent 提供的 capability id 解析 binding，生成 notebook-option/v1.2，并持久化
binding digest；未注册的原生能力继续使用既有 v1.0/v1.1 路径。

本切片只实现 proposal/revision 的受信绑定，不开放 Notebook 执行、确认执行、
materialization 新能力、HTTP/Graph/Run 接线，也不允许 Agent 提供或伪造 binding。
绑定缺失、失效、身份不一致、推荐决策缺失或执行模式非 `materialize_only` 时
必须 fail closed，并保持 batch 原子性与 replay 语义。

完成标准：

- catalog 是服务端拥有的唯一 binding lookup，不从 Agent payload 恢复 authority；
- 已注册 binding 生成 v1.2，包含稳定 binding digest，且 `execution_allowed` 为 false；
- 原生 Option、旧 v1.0/v1.1 读取和现有 replay 行为不回归；
- 失效/伪造/缺失/冲突输入有稳定拒绝测试；
- targeted notebook、capability、命名 gate 与 devline verify 通过。

## Boundary
- Affected paths: `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/agent/notebook/service.py`, `tests/test_notebook_capability_binding.py`
- Allowed paths: `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/agent/notebook/service.py`, `tests/test_notebook_capability_binding.py`
- Protected paths: `backend/workbench/capability_factory/notebook_binding.py`, `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/operations.py`, `backend/workbench/http`, `backend/workbench/graph`, `frontend/src`
- Dependencies: `.agent/devlines/v1-8-3-cf4-notebook-option-binding/RETROSPECTIVE.md`, `backend/workbench/capability_factory/notebook_binding.py`, `backend/workbench/agent/notebook/service.py`, `docs/superpowers/specs/2026-07-22-v1.8.1-agent-notebook-analysis-option.md`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_capability_binding.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_option_lifecycle.py tests/test_notebook_materialization.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`
- Known gates: `macOS native containment may report unsupported when sandbox-exec/resource limits are unavailable; classify as host capability, not product pass`, `new worktrees require bash scripts/link-shared-deps.sh with an absolute path`, `do not use a shell pipeline when reading tsc exit status`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
