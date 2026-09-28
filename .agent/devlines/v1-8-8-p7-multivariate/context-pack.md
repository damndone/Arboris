# Frozen Context Pack

Line: `v1-8-8-p7-multivariate`
Baseline SHA: `baab5938ebe4eff68b4a34ef66483e719ef1f67a`

## Objective
# v1.8.8 P7-C 多元统计 pack 目标

## 目标

建立可被后续 `CapabilityContract` 接入的多元统计基础 pack，覆盖 PCA、探索性因子分析（EFA）和 Cronbach's α。第一阶段只实现模块化、可组合、可验证的统计内核与结果合同，不注册 Agent operation，不修改 orchestrator，不修改 P0 workflow seam。

## 产品边界

- PCA 必须显式选择相关阵或协方差阵，不提供隐式默认；支持明确的成分数/选择策略，并返回载荷、得分和解释方差。
- EFA 必须先通过 KMO 与 Bartlett 适用性硬闸；提取法、因子数、旋转法均为显式选项，支持 varimax、promax、oblimin 的可扩展接口。
- Cronbach's α 返回总体 α、item-total 统计和删除各项后的 α；反向计分必须显式声明，不能从列名或数据猜测。
- 所有结果为确定性、可 JSON 化的公共结果，不暴露原始行；错误使用稳定的 reason code。
- 不安装新依赖；优先使用仓库已有的 NumPy/SciPy/pandas 能力。

## 隔离边界

本切片不得修改 Claude P0 的 workflow 文件、P0 测试、Agent operation 注册表、orchestrator、context tools、前端或 release 文件。Agent/CapabilityContract 接入留给后续 P1/P2 对接波次。

## 验证边界

先运行新增 pack 的红绿测试，再运行相关 backend 回归和 `git diff --check`。本切片的绿色测试不代表 Agent 自然语言可达、浏览器验收或 full gate 已完成。

## Boundary
- Affected paths: `backend/workbench/engine/packs/multivariate`, `backend/workbench/contracts/model/multivariate.py`, `tests/test_multivariate_pack.py`, `docs/superpowers/plans/2026-08-07-v1.8.8-p7-multivariate-objective.md`, `docs/superpowers/plans/2026-08-07-v1.8.8-p7-multivariate-implementation-plan.md`
- Allowed paths: `backend/workbench/engine/packs/multivariate`, `backend/workbench/contracts/model/multivariate.py`, `tests/test_multivariate_pack.py`, `docs/superpowers/plans/2026-08-07-v1.8.8-p7-multivariate-objective.md`, `docs/superpowers/plans/2026-08-07-v1.8.8-p7-multivariate-implementation-plan.md`
- Protected paths: `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/workflow.py`, `tests/test_workflow_seam.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/context_tools.py`, `frontend/src/workbench/agent/AgentPanel.tsx`
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_multivariate_pack.py -q -p no:cacheprovider`
- Known gates: `backend targeted tests; full gate deferred until P1/P2 integration`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### wo-b-model-pack (2026-07-20T17:44:54.000Z)

Completed formal devline wo-b-model-pack; final_state=CLOSED; failure_lesson_keys=versioned-public-result-contract
