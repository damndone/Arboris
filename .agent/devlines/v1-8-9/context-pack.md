# Frozen Context Pack

Line: `v1-8-9`
Baseline SHA: `e0462acb9dc1dd87134cd0246517ed1fa25c1368`

## Objective
# v1.8.9 — 日常可用（重建版）

基线：`f3836408`（v1.8.8 发布提交 `f564de63` + v1.8.9 spec/plan 文档）。
零件库：tag `archive/v1.8.9-codex-wip`（`214dee95`），只按需移植，不整体合并。

## 一句话目标

研究员不写代码、不看菜单，用中文完成"导入数据 → 整理变量 → 建模 → 读懂结果"，
且每个数字都可信、可追溯。

## 为什么重建

Codex 的 integration 分支在主线上出现退化：Agent/Notebook 面板不再调用 LLM；
v1.8.6 四个模型族的结果对 Agent/Report 不可读；证据读取比 v1.8.8 慢约 200 倍；
full gate 未通过。数据层、分类 ML、抽样 GLM 等模块本身基本独立，可移植。

## 范围（按顺序交付，每步单独提交并验收）

| # | 交付 | 来源 | 验收场景（浏览器内真实操作） |
|---|---|---|---|
| 1 | 修正后估计的模型族错配：非 OLS 模型不得做 OLS 联合 F / White / 二次驻点 | 新写 | Logit 模型后请求联合 F 检验 → 明确"不适用于 logit"，不产出数字 |
| 2 | 恢复模型分支在 resume 时的绑定 | 参考零件库 P0-B | 模型后中断、重启 backend、继续 → 后续步骤绑定到同一模型 |
| 3 | Agent 基线核查：v1.8.8 LLM Agent 用 DeepSeek 跑 10 条中文请求，记录成功率与失败类型 | 新写（评测脚本） | 基线数字写入本文件末尾，作为后续改动的对照 |
| 4 | 变量元数据：变量标签、值标签、测量级别、缺失值定义 | 移植 `metadata.py` 等 | 在界面改 `gender` 的值标签，结果表与 Agent 回答使用新标签 |
| 5 | `.sav/.zsav/.dta` 导入导出（含标签），不能保留的元数据明确提示 | 移植 `data_interchange.py` | 导入 .sav → 改标签 → 导出 .dta → 再导入，标签一致 |
| 6 | 数据编辑器：数据视图 + 变量视图，数据操作（filter/sort/recode/split）以血缘节点记录 | 移植 `data_operations.py`、`filter_ast.py` + 新 UI | 在变量视图把 `age` 分三组 recode，生成新节点，可回溯 |
| 7 | Agent 驱动以上全部能力：LLM 负责理解与组合；写操作经服务端校验 + 用户确认 | 在 v1.8.8 Agent 上扩展工具 | 用中文让 Agent 完成场景 4–6 与一次 Logit 建模，成功率不低于第 3 步基线 |
| 8 | 外发管控 v1：内容来源处打标签、LLM 客户端唯一出口检查、原始行默认不外发、被拦截内容以占位说明替换 | 新写（参考 spec §7.7） | Agent 请求"把前 20 行发给我看"→ 本地显示，发往 DeepSeek 的请求中无原始行（审计日志可见） |

不在本版：分类 ML、抽样 GLM 扩展（v1.8.11 移植）、出版级表格与脚本导出（v1.8.10）、
P2 模型族、Codex 的分页/授权凭据/字节预算体系。

## 硬约束

- 正确性：统计数字只由确定性代码产生；不适用的方法明确拒绝，不静默降级。
- 性能预算：读取单个结果 < 1 秒；后端测试总时长不超过 v1.8.8 的 1.5 倍。
- 不退化：v1.8.8 已有的 UI、Agent、模型族、结果展示全部保留，除非本文件列出替代。
- 每个交付完成即提交；不留跨天未提交改动。

## 验证

- 每步：先写能复现问题的失败测试，再修；相关测试 + 前端 typecheck。
- 第 3、7 步：真实 DeepSeek 调用，结果与确定性测试分开记录。
- 发版前：宿主机 full gate（`scripts/gate.sh --full`），浏览器逐条走验收场景。

## 已知门槛

- 仅本机 macOS 验证；Linux / 其他主机 / 云端为 NOT VERIFIED。
- 真实 LLM 质量只对 DeepSeek 负责。
- merge / tag / push 需用户单独授权。

## Boundary
- Affected paths: `backend`, `frontend/src`, `tests`, `scripts`, `docs`
- Allowed paths: none
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest <focused tests>`, `cd frontend && npx tsc --noEmit`
- Known gates: `host full gate: scripts/gate.sh --full`, `browser acceptance per objective scenarios`, `real DeepSeek evaluation recorded separately`

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

### v1-8-3-cf3-validation-runtime (2026-07-27T12:25:00.000Z)

Completed formal devline v1-8-3-cf3-validation-runtime; final_state=COMPLETED; failure_lesson_keys=authoring-source-allowlist, cf3-validation-runtime-red, fms-event-draft-validation, protocol-identity-binding

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required
