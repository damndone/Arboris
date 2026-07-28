# Frozen Context Pack

Line: `v1-8-3-cf4-notebook-planner-projection-r1`
Baseline SHA: `33f4cbdd04accce9e2088ed5ee66413d3f3bc6a6`

## Objective
# v1.8.3 CF4 Notebook planner projection

让真实 Notebook planner 能读取服务器拥有的、已准入 capability 的最小只读声明，
而不是只读取原生 `build_capabilities()`；同一份声明同时提供 capability 的 bounded
artifact vocabulary，供 NotebookPlanningAgent 和 NotebookService 使用。

CapabilityBindingCatalog 只输出 server-owned planner projection：capability id、
受限 planner metadata 和 artifact id/type，不输出 raw binding、entrypoint、路径、
依赖包或 authority 内部记录。projection 必须在生成前经过当前 binding verifier 和
scope 检查；binding 无效时不得出现在 planner catalog。Agent 仍只能提出 typed option，
service 仍必须再次解析并钉住 binding；`materialize_only`、execution_allowed=false、
proposal/risk authorization 和既有原生路径保持不变。

完成标准：

- custom capability 可通过受信 projection 出现在真实 planner catalog；
- planner 的 artifact contract 与 service 的 artifact validation 使用同一 bounded projection；
- projection 缺失、越界、失效或伪造字段 fail closed；
- 原生 capability、旧 Notebook contract、HTTP route 和命名 gate 不回归；
- 不新增 HTTP 注册、依赖安装、代码执行、confirm_and_execute 或自动执行面。

## Boundary
- Affected paths: `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/service.py`, `tests/test_notebook_routes.py`, `tests/test_notebook_capability_binding.py`, `backend/workbench/capability_factory/contracts.py`, `tests/test_capability_notebook_binding.py`, `tests/test_capability_admission_contract.py`
- Allowed paths: `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/service.py`, `tests/test_notebook_routes.py`, `tests/test_notebook_capability_binding.py`, `backend/workbench/capability_factory/contracts.py`, `tests/test_capability_notebook_binding.py`, `tests/test_capability_admission_contract.py`
- Protected paths: `backend/workbench/app.py`, `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/graph`, `backend/workbench/agent/operations.py`, `frontend/src`
- Dependencies: `.agent/devlines/v1-8-3-cf4-notebook-provider-injection/RETROSPECTIVE.md`, `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/service.py`, `docs/superpowers/specs/2026-07-25-v1.8.3-capability-factory-design.md`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_routes.py tests/test_notebook_capability_binding.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_option_lifecycle.py tests/test_notebook_materialization.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`
- Known gates: `macOS native containment may report unsupported when sandbox-exec/resource limits are unavailable; classify as host capability, not product pass`, `new worktrees require bash scripts/link-shared-deps.sh with an absolute path`, `do not use a shell pipeline when reading tsc exit status`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
