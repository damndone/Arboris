# Frozen Context Pack

Line: `v1-8-6-report-evidence`
Baseline SHA: `5a4df4f58bf8b67ad2066e203fdfffe185fcb135`

## Objective
# Workbench v1.8.6 Report Evidence 与安全编辑 Objective

## 目标

在不修改任何 Run 数据结果、模型结果、诊断、图表 artifact 或 Graph lineage 的前提下，
把现有 Report 页升级为可扩展的证据驱动报告工作台：

1. 引入版本化的 Report Evidence/Quality 合同，支持未来模型族通过 provider/module 扩展；
2. 将 `journal_full_v1` 的章节覆盖、引用、图表、限制和篇幅底线做成确定性校验；
3. 将当前事实 checkbox 改成分组、可读标签、只读详情和可审计排除；
4. 允许用户编辑标题、摘要、正文、章节顺序、caption 和作者备注，保存为独立 report revision；
5. 服务端拒绝任何试图通过报告 API 覆盖数据、模型、诊断、artifact 或 lineage 的 payload；
6. 普通 Run 默认不再生成 PDF/XLSX，Report 页提供用户主动的报告/结果表导出入口；
7. 保持既有历史 AI report 可读，并为后续模型、诊断和预测证据保留版本化注册点。

## 可证伪验收

- 编辑 report revision 前后，source Run 的数据、模型结果、诊断、图表、Graph lineage 和
  artifact content hash 不变；
- report revision 持久化 source run、fact snapshot hash、artifact IDs、excluded fact IDs、
  revision id 和 validation status；Run/evidence 变化后旧 revision 标为 stale；
- 带有 `dataset`、`model_results`、`diagnostics`、`artifact_payload` 或 `lineage` 覆盖字段的
  report mutation 请求在服务端 fail-closed；
- 取消事实只影响 LLM packet，完整快照和排除记录仍然保存；
- 未知 fact、已排除 fact、未知 figure、重复 figure 或 fact table 之外的数字不能进入正式导出；
- `journal_full_v1` 缺少必需章节、citation、适用 capability module 或 limitation 时不能标记
  为 exportable；证据不足时输出 `insufficient_evidence` 而不是填充虚构内容；
- 新增 provider/module 可以在不增加 `ReportView` 模型专用条件分支的情况下进入分组证据和报告
  coverage；unknown/unavailable provider 显示缺失原因；
- 普通 Run 的 artifacts 中没有自动 `report_pdf` 或默认 `tables_xlsx`；用户从 Report 页主动
  导出时才创建相应文件；
- 既有 Report/LLM/export/AI-store 测试、前端 Report 测试、typecheck、`git diff --check` 和
  formal FMS verification 通过；不 push、PR、merge、tag 或发布。

## 允许的范围

- `backend/workbench/report_contract.py`、新增 report quality/evidence/revision 合同模块；
- `backend/workbench/report_store.py` 与 `backend/workbench/http/runs_routes.py` 的报告 revision
  持久化和不可变校验；
- `backend/workbench/engine/stages/report.py` 的默认导出策略；
- `frontend/src/report/` 的证据分组、编辑器、revision history、导出入口及对应测试；
- 对应的 backend/frontend tests、报告设计文档和本实施计划。

## 明确不做

- 不修改任何估计器、数据操作、预测协议、模型族算法或统计检验算法；
- 不允许 Report API 更新事实 value、数据集、model result、diagnostics、artifact 或 lineage；
- 不新建 Run/Data/Export 页面；
- 不实现自由代码、外部论文数字自动纳入 Workbench evidence；
- 不把 Agent `report.compose` 改成自主论文写作或执行入口；
- 不在本 objective 中新增模型族，只提供扩展接口。

## 已知门槛

- 当前 worktree 有 v1.8.6 既有 dirty changes；不得 reset、clean 或覆盖无关文件；
- 当前 `ReportView` 仍是大组件，优先新增小型纯函数/子组件，避免继续增加模型族分支；
- 历史 AI report schema 必须兼容读取，新增字段使用默认值或版本迁移；
- 导出策略改变会触及既有测试中对 `report_pdf`/`tables_xlsx` 的断言，必须先写红测试再调整；
- native browser 验收、full gate 和 baseline attribution 分别记录，不能互相替代。

## Boundary
- Affected paths: `frontend/src/styles.css`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`, `backend/workbench/http/llm_routes.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_quality.py`, `backend/workbench/report_store.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `frontend/src/report/FamilyEvidence.test.tsx`, `frontend/src/report/FamilyEvidence.tsx`, `frontend/src/report/RegressionTable.test.tsx`, `frontend/src/report/RegressionTable.tsx`, `frontend/src/report/ReportComposer.test.tsx`, `frontend/src/report/ReportComposer.tsx`, `frontend/src/report/ReportPreviewPanel.test.tsx`, `frontend/src/report/ReportPreviewPanel.tsx`, `frontend/src/report/ReportView.test.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/factTable.ts`, `frontend/src/report/report.css`, `frontend/src/report/reportClient.ts`, `frontend/src/report/reportDocument.test.ts`, `frontend/src/report/reportDocument.ts`, `frontend/src/report/reportEvidence.test.ts`, `frontend/src/report/reportEvidence.ts`, `frontend/src/report/reportHistory.ts`, `frontend/src/report/reportSelection.ts`, `frontend/src/report/reportSelection.test.ts`, `frontend/src/report/ReportFigureSelection.tsx`, `frontend/src/report/ReportFigureSelection.test.tsx`, `tests/test_ai_report_store.py`, `tests/test_llm_chat.py`, `tests/test_report_contract.py`, `tests/test_report_export.py`, `tests/test_report_quality.py`, `tests/test_reporting_exports.py`, `tests/test_orchestrator_e2e.py`
- Allowed paths: `frontend/src/styles.css`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`, `backend/workbench/http/llm_routes.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_quality.py`, `backend/workbench/report_store.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `frontend/src/report/FamilyEvidence.test.tsx`, `frontend/src/report/FamilyEvidence.tsx`, `frontend/src/report/RegressionTable.test.tsx`, `frontend/src/report/RegressionTable.tsx`, `frontend/src/report/ReportComposer.test.tsx`, `frontend/src/report/ReportComposer.tsx`, `frontend/src/report/ReportPreviewPanel.test.tsx`, `frontend/src/report/ReportPreviewPanel.tsx`, `frontend/src/report/ReportView.test.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/factTable.ts`, `frontend/src/report/report.css`, `frontend/src/report/reportClient.ts`, `frontend/src/report/reportDocument.test.ts`, `frontend/src/report/reportDocument.ts`, `frontend/src/report/reportEvidence.test.ts`, `frontend/src/report/reportEvidence.ts`, `frontend/src/report/reportHistory.ts`, `frontend/src/report/reportSelection.ts`, `frontend/src/report/reportSelection.test.ts`, `frontend/src/report/ReportFigureSelection.tsx`, `frontend/src/report/ReportFigureSelection.test.tsx`, `tests/test_ai_report_store.py`, `tests/test_llm_chat.py`, `tests/test_report_contract.py`, `tests/test_report_export.py`, `tests/test_report_quality.py`, `tests/test_reporting_exports.py`, `tests/test_orchestrator_e2e.py`
- Protected paths: `backend/workbench/predictive_research`, `frontend/src/runForm`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-6-consumer-entries`, `v1-8-6-crosscut-foundation`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_report_quality.py tests/test_report_contract.py tests/test_ai_report_store.py tests/test_report_export.py tests/test_orchestrator_e2e.py`, `npm test -- --run frontend/src/report/reportEvidence.test.ts frontend/src/report/reportDocument.test.ts frontend/src/report/ReportView.test.tsx`, `npm run typecheck`, `git diff --check`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --all`
- Known gates: `TDD red evidence is required before production code`, `Run artifacts must not be mutated by report editing or export`, `普通 Run 默认不生成 PDF/XLSX; explicit Report actions may create them`, `Existing dirty v1.8.6 changes are user-owned and must be preserved`, `Native browser, full gate, and baseline attribution are separate evidence`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
