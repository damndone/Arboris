# Frozen Context Pack

Line: `v1-8-3-cf4-notebook-provider-injection`
Baseline SHA: `9fd9efb3f01d071bcd79cd3d499e8dbdd5e21748`

## Objective
# v1.8.3 CF4 Notebook provider injection

将已完成的服务器拥有 `CapabilityBindingCatalog` 接入 Notebook 的 HTTP 服务入口。
路由从应用级、受信注入点取得 catalog，并把它传给每个按项目创建的 `NotebookService`，
使已登记且仍有效的 capability 可沿既有 proposal 生命周期生成
`NotebookOptionRevision@1.2`；未配置 catalog 时保留原生 v1.0/v1.1 路径。

本切片不创建或持久化 authority，不允许 HTTP/Agent 注册、替换或伪造 binding，不开放
`confirm_and_execute`、自动执行、网络 fetch 或新的执行面。注入值必须是服务端拥有的
`CapabilityBindingCatalog`；错误配置 fail closed。覆盖 HTTP 路由真实请求、旧路径兼容、
跨请求使用同一受信 catalog，以及注入状态不影响其他项目。

完成标准：

- 生产 Notebook 路由具备明确的 server-owned catalog injection seam；
- 注册 capability 经 HTTP proposal 生成 v1.2 并保留 binding digest；
- 未配置 catalog 的现有路由行为不回归；
- 不合规注入不会降级为普通能力或改变执行授权；
- targeted notebook、capability、命名 gate 与正式 devline verify 通过。

## Boundary
- Affected paths: `backend/workbench/app.py`, `backend/workbench/http/notebook_routes.py`, `tests/test_notebook_routes.py`
- Allowed paths: `backend/workbench/app.py`, `backend/workbench/http/notebook_routes.py`, `tests/test_notebook_routes.py`
- Protected paths: `backend/workbench/capability_factory`, `backend/workbench/agent/notebook`, `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/graph`, `backend/workbench/agent/operations.py`, `frontend/src`
- Dependencies: `.agent/devlines/v1-8-3-cf4-notebook-option-consumer/RETROSPECTIVE.md`, `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/agent/notebook/service.py`, `docs/superpowers/specs/2026-07-25-v1.8.3-capability-factory-design.md`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_routes.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_capability_binding.py tests/test_capability_notebook_binding.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`
- Known gates: `macOS native containment may report unsupported when sandbox-exec/resource limits are unavailable; classify as host capability, not product pass`, `new worktrees require bash scripts/link-shared-deps.sh with an absolute path`, `do not use a shell pipeline when reading tsc exit status`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
