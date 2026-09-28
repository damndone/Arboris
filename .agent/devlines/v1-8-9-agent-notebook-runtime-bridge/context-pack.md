# Frozen Context Pack

Line: `v1-8-9-agent-notebook-runtime-bridge`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# Workbench v1.8.9 Agent / Notebook Runtime Bridge Objective

## Objective

把 Wave C 的安全共享编译器接到正式的应用启动配置和 Notebook 自然语言入口，
并让 ReportWorkspaceContext 自动消费已持久化的分类证据。Agent 与 Notebook 仍然
共享同一个 `AnalysisIntentV1 -> CompilationRecordV1 -> confirmation -> admission ->
trusted provider -> evidence` 链路；本线不创建假 provider、不绕过旧执行内核、
不把客户端文本或路径变成执行权限。

## Required outcome

1. 应用启动可以显式注册 server-owned `AgentNotebookCompilerV1`，HTTP 只按精确的
   project/session scope 查找；未绑定时继续返回明确的 503，不隐式回退到旧路径。
2. runtime composition helper 只能把服务端传入的真实
   `ProviderRuntimeContributionV1` 加入可信 registry；缺失、重复、合同不一致或
   没有 evidence committer 时 fail closed。不得从 manifest 导入 callable，也不得
   用 fixture/no-op 冒充生产能力。
3. Notebook 有一个薄的自然语言 compile adapter，校验 Notebook scope 后委托共享
   compiler；它不维护第二套 capability 表、不直接调用 provider、不接受客户端确认
   对象。确认和执行继续使用 server-retained receipt。
4. ReportWorkspaceContext 自动从已索引、hash 校验的分类 artifact 读取 typed
   `workbench.prediction.classification-evidence` packet；缺失、损坏或未知 schema
   只显示 `UNAVAILABLE`，不计算、不 dump raw JSON。
5. 旧 Notebook route、受保护 workflow runtime 和已有 provider/模型代码保持不变；
   本线只增加 bridge，不宣称全历史 runtime 已迁移。

## Safety boundary

- 自然语言只能触发 typed intent normalization；未知字段、prompt injection、未知
  sensitivity、跨 scope record、stale snapshot 和伪造 confirmation 都拒绝。
- 默认进程不凭空获得数据执行能力。只有 deployment/bootstrap 明确注入真实 provider
  contributions 后，相关 scope 才可执行；否则保留 503/typed unavailable。
- Report 只读已持久化 evidence；前端永远不从 artifact 标题猜测 packet，也不在浏览器
  端重算统计量。

## Acceptance boundary

需通过本线后端定向测试、既有 cutover/Notebook 回归、前端定向测试、typecheck、
compileall、diff check 和 formal devline verify。浏览器、外部 provider、host full
gate、merge、push、tag、release 仍分别记为 `NOT VERIFIED`，除非实际执行。

## Boundary
- Affected paths: `backend/workbench/agent/cutover_runtime.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/app.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/prediction.py`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/ClassificationEvidence.tsx`, `tests/test_v189_agent_notebook_runtime_bridge.py`, `tests/test_v189_notebook_cutover_route.py`, `tests/test_v189_artifact_integrity.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/predictive_research/test_classification_consumers_v189.py`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`, `frontend/src/report/ReportView.v189.test.tsx`, `frontend/src/report/ClassificationEvidence.test.tsx`, `docs/superpowers/objectives/2026-08-16-v1.8.9-agent-notebook-runtime-bridge-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-agent-notebook-runtime-bridge.md`, `docs/superpowers/plans/2026-08-16-v1.8.9-agent-notebook-runtime-bridge-implementation-plan.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-agent-notebook-runtime-bridge-handoff.md`
- Allowed paths: `backend/workbench/agent/cutover_runtime.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/app.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/prediction.py`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/ClassificationEvidence.tsx`, `tests/test_v189_agent_notebook_runtime_bridge.py`, `tests/test_v189_notebook_cutover_route.py`, `tests/test_v189_artifact_integrity.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/predictive_research/test_classification_consumers_v189.py`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`, `frontend/src/report/ReportView.v189.test.tsx`, `frontend/src/report/ClassificationEvidence.test.tsx`, `docs/superpowers/objectives/2026-08-16-v1.8.9-agent-notebook-runtime-bridge-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-agent-notebook-runtime-bridge.md`, `docs/superpowers/plans/2026-08-16-v1.8.9-agent-notebook-runtime-bridge-implementation-plan.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-agent-notebook-runtime-bridge-handoff.md`
- Protected paths: `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/data_operations.py`, `backend/workbench/evidence`, `backend/workbench/predictive_research`
- Dependencies: `v1-8-9-agent-notebook-cutover`, `v1-8-9-provider-catalog-integration`, `v1-8-9-p1-classification-ml-core`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_runtime_bridge.py tests/test_v189_notebook_cutover_route.py -q`, `cd frontend && npm test -- --run src/report/ReportWorkspaceContext.v189.test.tsx`, `cd frontend && npm run typecheck`
- Known gates: `bridge tests do not prove browser, external provider execution, host full gate or release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-cf4-notebook-provider-injection (2026-07-26T22:45:00.000Z)

Completed formal devline v1-8-3-cf4-notebook-provider-injection; final_state=COMPLETED; failure_lesson_keys=formal-rescope-boundary, tdd-red-before-provider-injection

### v1-8-5-notebook-capability-admission (2026-08-01T22:35:30.000Z)

Completed formal devline v1-8-5-notebook-capability-admission; final_state=COMPLETED; failure_lesson_keys=notebook-admission-must-require-published-contract

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox
