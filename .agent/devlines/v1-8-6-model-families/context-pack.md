# Frozen Context Pack

Line: `v1-8-6-model-families`
Baseline SHA: `5ce61715f37dae07b264cdf449ae7bce3f757441`

## Objective
# v1.8.6 S6/S7/S8 Model Families Objective

在 S0 可追加 registry 上增加 ordinal/nominal y_type、有序/多项 logit、生存分析和分位数
回归；每族独立契约、pack、诊断和 evidence，不改变既有三种 y_type。

## 可证伪验收

- ordinal/nominal 真实 Run 分别产出预测概率、优势比/相对风险比、边际效应；有序模型有平行线诊断。
- Kaplan–Meier、log-rank、Cox 与 Schoenfeld 诊断使用独立 survival contract，risk set/censoring
  证据可追溯。
- QuantReg 支持多个 quantile、区间/bootstrap 和跨 quantile 比较。
- 既有 golden 23 逐位 0-drift；Stata/R oracle 验证等级如实记录，不能以内部测试冒充外部一致。
- Graph/Report/Table/Agent 读取新增 packet 的精确数值，不只显示 artifact metadata。

## Boundary
- Affected paths: `backend/workbench/agent/context_tools.py`
- Allowed paths: `backend/workbench/agent/context_tools.py`
- Protected paths: `backend/workbench/predictive_research`, `backend/workbench/engine/stages/diagnostics.py`
- Dependencies: none
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_model_families_v186.py -q`
- Known gates: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_orchestrator_e2e.py tests/test_reporting_exports.py tests/test_lineage_invariants.py -q`, `npm run typecheck (cwd frontend)`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### v1-8-5-workflow-memory-integration (2026-08-02T11:23:33.067Z)

Completed formal devline v1-8-5-workflow-memory-integration; final_state=COMPLETED; failure_lesson_keys=browser-memory-projection-contract-must-roundtrip, complete-v11-fields-when-removing-memory-provenance, did-genesis-empty-predictors-contract, did-model-family-contract-before-workflow-admission, did-notebook-family-contract-wiring, did-planner-family-contract-wiring, memory-default-target-registry-before-application, memory-provenance-version-from-new-proposal-on-revalidation, opaque-vocabulary-id-before-consumer-wiring, tdd-domain-memory-preflight-before-gate-wiring, tdd-memory-default-provenance-ui-before-persistence

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-3-cf3-validation-runtime (2026-07-27T12:25:00.000Z)

Completed formal devline v1-8-3-cf3-validation-runtime; final_state=COMPLETED; failure_lesson_keys=authoring-source-allowlist, cf3-validation-runtime-red, fms-event-draft-validation, protocol-identity-binding

### v1-8-3-mem2-domain-memory (2026-07-27T11:05:00.000Z)

Completed formal devline v1-8-3-mem2-domain-memory; final_state=COMPLETED; failure_lesson_keys=domain-memory-contract-first, frontend-api-awaits-response
