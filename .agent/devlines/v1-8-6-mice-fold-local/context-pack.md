# Frozen Context Pack

Line: `v1-8-6-mice-fold-local`
Baseline SHA: `4e4118e3615a1c473ebf5dc6fba771d7502717e4`

## Objective
# v1.8.6 S4 MICE Fold-local Objective

将 prediction + MICE 从当前全表路径直接拒绝，改为每个训练 fold 独立拟合、应用到验证与
最终 holdout；全表先插补再切分必须继续被拒绝。

## 可证伪验收

- 全表 MICE 后切分诱饵测试失败，不产生 prediction packet。
- fold-local MICE + prediction 的真实 typed run 成功并持久化 preprocessing scope、
  prediction/evaluation packet。
- 每个 fold 的 fitted state 只来自该 fold training rows；final holdout 不参与拟合。
- 缺少可用 MICE 依赖时返回结构化 optional-dependency/next-step evidence，不绕过安全边界。

## Boundary
- Affected paths: `backend/workbench/engine/stages/diagnostics.py`, `backend/workbench/predictive_research/prediction_protocol.py`, `backend/workbench/predictive_research/preprocessing.py`, `backend/workbench/imputation.py`, `backend/workbench/engine/imputation_registry.py`, `backend/workbench/engine/stages/imputation.py`, `tests/predictive_research/test_prediction_entrypoint_v186.py`, `tests/predictive_research/test_prediction_request_boundary_v186.py`, `tests/predictive_research/test_prediction_protocol_v186.py`, `tests/test_imputation_mice.py`, `tests/test_e2e_imputation_flow.py`, `tests/test_imputation_fold_local.py`
- Allowed paths: `backend/workbench/engine/stages/diagnostics.py`, `backend/workbench/predictive_research/prediction_protocol.py`, `backend/workbench/predictive_research/preprocessing.py`, `backend/workbench/imputation.py`, `backend/workbench/engine/imputation_registry.py`, `backend/workbench/engine/stages/imputation.py`, `tests/predictive_research/test_prediction_entrypoint_v186.py`, `tests/predictive_research/test_prediction_request_boundary_v186.py`, `tests/predictive_research/test_prediction_protocol_v186.py`, `tests/test_imputation_mice.py`, `tests/test_e2e_imputation_flow.py`, `tests/test_imputation_fold_local.py`
- Protected paths: none
- Dependencies: none
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests/predictive_research tests/test_imputation_mice.py tests/test_e2e_imputation_flow.py -q`
- Known gates: `python -m compileall -q backend/workbench`, `bash scripts/gate.sh`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
