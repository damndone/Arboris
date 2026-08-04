# Frozen Context Pack

Line: `v1-8-6-predictive-research-integration`
Baseline SHA: `bfeb346523c95facec8b0c2dd9f6915adef8abfc`

## Objective
# Workbench v1.8.6 Predictive Research Integration Objective

从本地 checkpoint `bfeb346` 继续完成 Workbench v1.8.6 predictive-research correctness
foundation 的 integration 收口。保留原 foundation formal line 的冻结证据，不编辑其
manifest 或历史事件。

必须完成：

1. 未声明 prediction data structure 的新 run 在拟合前以
   `PREDICTION_DATA_STRUCTURE_UNKNOWN` 阻塞，不得进入 legacy random split；legacy
   prediction 仅保留给历史 run 重放。
2. Temporal 与 panel 识别并校验必填列，但在 M0 通用 prediction 路径
   `PREDICTION_SPLIT_PROFILE_NOT_SUPPORTED` fail-closed，不得执行随机或 temporal ML。
3. 仅为 `frequency_weight` 实现明确的 sklearn `sample_weight` 正例；sampling_weight、
   analysis_weight、OLS、panel 与 econometric estimator 权重继续 fail-closed。
4. 缺少 payload contract 的历史 prediction 显示
   `legacy_random_split_v0`、`payload_not_evaluated`、`legacy_only`，使用规定英文 UI 文案，
   legacy 与 v1.8.6 Compare 以 `PREDICTION_LEGACY_RESULT_INCOMPARABLE` 拒绝。
5. MICE 与 prediction 同 run 时必须折内拟合，或在全表路径 fail-closed，并有诱饵测试。
6. Graph、Report、Compare、Table、Run、Agent 只读取同一经过 schema validation 的 typed
   evidence；Graph 至少显示 Dataset Snapshot → Prediction Task → Split Plan → Baseline +
   Candidate Models → Evaluation → Negative Controls → Result，Report 分区显示 development /
   final holdout / negative-control / limitations，Compare 只接受兼容 SplitPlan。
7. 完成 focused tests、formal verification、baseline `7e257f2` 对照归因、quick/full gate
   与 native browser evidence；不得 push、PR、merge、tag。

明确不做：PIT/Quant、实盘、自动调参、深度学习、任意 code.execute、reshape/merge、
temporal/panel prediction execution、OLS/Panel/econometric weights。

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/services/run_service.py`, `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/src/lineage/drafts/GenesisWizard.tsx`, `frontend/src/lineage/drafts/GenesisWizard.test.tsx`, `tests/test_api_run_params.py`
- Allowed paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/services/run_service.py`, `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/src/lineage/drafts/GenesisWizard.tsx`, `frontend/src/lineage/drafts/GenesisWizard.test.tsx`, `tests/test_api_run_params.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/predictive_research`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_prediction_models.py tests/test_prediction_request.py`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_statistical_tests_v186.py`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_fold_local.py`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_compare_node_api.py tests/test_report_contract.py tests/test_report_view_model.py`, `npm test -- --run`, `npm run typecheck`, `bash scripts/gate.sh --quick`, `bash scripts/gate.sh`
- Known gates: `native browser acceptance: NOT VERIFIED until performed`, `full backend gate must be compared against baseline 7e257f2`, `no push PR merge or tag without explicit authorization`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### integration-v1-7-3 (2026-07-20T17:43:14.000Z)

Completed formal devline integration-v1-7-3; final_state=CLOSED; failure_lesson_keys=c1-c2-execution-boundary, cross-boundary-fixture-parity, declared-owner-no-test-shadowing, entrypoint-contract-coverage, runtime-contract-assembly, versioned-result-visible-reader-adapter

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft
