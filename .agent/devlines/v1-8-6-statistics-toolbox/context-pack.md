# Frozen Context Pack

Line: `v1-8-6-statistics-toolbox`
Baseline SHA: `69a662369fc2f87e67f1608866f3ee8ef5a9fcec`

## Objective
# v1.8.6 S2/S9/S10 Statistics Toolbox Objective

将独立统计工具接入正常 Run 的 evidence packet，并完成回归表、Table 1、变量/值标签的
用户消费端。

## 必须完成

- `anova_posthoc`、Cohen's d、eta/omega squared、Levene/Bartlett/Shapiro 等由正常数据形状
  触发并进入 `workbench.statistics.evidence-packet` v1。
- one-sample/paired/Wilcoxon 只有在存在显式参考均值/配对语义时触发；缺语义 fail-closed，
  不能按列顺序猜配对。
- Table/Report/Agent 消费 assumptions、warnings、effect sizes、校正范围和 CI（适用时）。
- 多模型回归表、显著性标记、Table 1、变量/值标签贯通输出。

## 可证伪验收

- 含多分类分组的普通真实 Run 的 statistical_tests artifact 出现 `anova_posthoc` 与
  `cohens_d`；后端非自身引用数从 0 变为至少 1。
- 新 packet 可被 Table/Report/Agent 读到精确值；旧八类检验与 FDR/golden 不变。
- 标签从用户声明或支持的导入格式进入表格、报告和图形轴；不支持的导入标签能力明确降级。

## Boundary
- Affected paths: `docs/superpowers/plans/2026-08-03-v1.8.6-statistics-toolbox-objective.md`, `backend/workbench/statistical_tests.py`, `backend/workbench/engine/stages/statistical_tests.py`, `tests/test_statistical_tests.py`, `tests/test_statistical_tests_extended.py`, `tests/test_statistical_tests_v186.py`, `tests/test_statistics_api_e2e_v186.py`, `tests/test_lineage_invariants.py`
- Allowed paths: `docs/superpowers/plans/2026-08-03-v1.8.6-statistics-toolbox-objective.md`, `backend/workbench/statistical_tests.py`, `backend/workbench/engine/stages/statistical_tests.py`, `tests/test_statistical_tests.py`, `tests/test_statistical_tests_extended.py`, `tests/test_statistical_tests_v186.py`, `tests/test_statistics_api_e2e_v186.py`, `tests/test_lineage_invariants.py`
- Protected paths: none
- Dependencies: `baseline-69a6623`, `v186-statistics-kernel-present`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_statistical_tests.py tests/test_statistical_tests_extended.py tests/test_statistical_tests_v186.py tests/test_orchestrator_e2e.py tests/test_reporting_exports.py -q`
- Known gates: `TDD-red-before-statistics-loop-code`, `preserve-old-statistical-test-families-and-fdr-golden`, `normal-run-writes-evidence-packet`, `report-agent-consume-schema-validated-evidence`, `no-push-PR-merge-or-tag-without-authorization`

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

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none
