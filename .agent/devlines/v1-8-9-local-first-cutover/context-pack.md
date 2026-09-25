# Frozen Context Pack

Line: `v1-8-9-local-first-cutover`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# v1.8.9 local-first authority, resume, and clean cutover

## Objective

在现有 v1.8.9 hardening integration candidate 上完成本机 macOS/Darwin 的安全闭环：

1. 跨进程 Resume 使用服务端持久化状态，可在 backend 重启后继续，并绑定 project/session/plan/model branch。
2. authority 只由当前 backend 发行、持久化和校验；客户端与 LLM 只能提交意图，不能提交 authority、owner、host 或 evidence 身份。
3. bootstrap 生成并校验本机 server identity、host identity 和 evidence owner，使结果可以证明来自当前 Workbench backend，并绑定本机 project/session。
4. deterministic evaluator 在无 provider、无网络时提供可重复的 typed correctness baseline；Provider benchmark 只消费同一 compiler/evaluator seam，不把 deterministic 结果冒充真实 LLM 结果。
5. Agent、Notebook、Report UI 统一走 v1.8.9 compiler/cutover；旧状态不迁移，明确返回 `UNSUPPORTED_VERSION`；删除旧执行路径与隐式 raw-result fallback。
6. 使用 Codex 内置浏览器自动验收新路径；Linux、其他 Mac、云环境只记录 `NOT VERIFIED`，不阻塞本机完成。

## Safety and extensibility constraints

- 不读取、打印或写入 provider secret；真实 provider 不是本机 correctness gate。
- 只允许 server-owned typed references、closed capability vocabulary 和 admission-gated persistence；拒绝客户端伪造的 authority/evidence/host 字段。
- 统计执行仍由 typed operation registry 和确定性 runtime 负责；LLM 只负责受约束的意图理解、解释和组合建议。
- 不迁移历史状态；旧 schema、旧 execution route、缺少新身份绑定的 receipt 均 fail closed。
- 不新增第二套 Agent/Notebook 语义引擎；统一 compiler 是唯一计划入口，Report 只读正式 evidence projection。
- 修改范围限于 backend contracts/runtime/http/evidence/services、frontend Agent/Notebook/Report cutover、对应测试、目标文件和验收记录。

## Required verification

- focused backend contract/runtime/route tests；cross-process subprocess/restart probe；evidence tamper and identity-binding probes。
- deterministic evaluator fixed-seed repeatability and provider seam tests with `provider_called=false`.
- frontend typecheck and cutover route tests。
- internal browser automated acceptance for Agent, Notebook, Report; record exact URLs, visible markers, and failures.
- formal event verification and retrospective; clearly separate implemented/tested, browser-accepted, provider-backed, and release claims.

## Known non-blocking gates

- Linux/Darwin variants other than this host: `NOT VERIFIED`.
- Other macOS hosts and cloud deployment: `NOT VERIFIED`.
- Real external LLM provider quality benchmark: `NOT VERIFIED` until a provider is deliberately configured.
- Release merge/tag: not part of this implementation line.

## Boundary
- Affected paths: `backend/workbench/contracts`, `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/services`, `backend/workbench/http`, `backend/workbench/app.py`, `frontend/src/agent`, `frontend/src/notebook`, `frontend/src/report`, `tests`, `frontend/src`, `docs/superpowers/objectives/2026-08-23-v1.8.9-local-first-cutover-objective.md`
- Allowed paths: `backend/workbench/contracts`, `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/services`, `backend/workbench/http`, `backend/workbench/app.py`, `frontend/src/agent`, `frontend/src/notebook`, `frontend/src/report`, `tests`, `frontend/src`, `docs/superpowers/objectives/2026-08-23-v1.8.9-local-first-cutover-objective.md`
- Protected paths: `root-main`
- Dependencies: none
- Tests: none
- Known gates: `browser-acceptance`, `real-provider-benchmark`, `other-host-verification`, `release-merge-tag`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-9-contract-lock (2026-08-16T04:25:00.000Z)

Completed formal devline v1-8-9-contract-lock; final_state=COMPLETED; failure_lesson_keys=catalog-normalized-name-fixture-portability, formal-cli-command-surface-task2, formal-event-cli-generated-hash, formal-event-preventability-vocabulary, formal-event-source-repository-relative, formal-event-supported-stage, linked-worktree-git-index-permission, resolver-authority-slot-red, resolver-module-registry-red, shared-worktree-git-lock-permission, shared-worktree-git-staging-permission-repeat, task3-authority-slot-replacement-red, task3-compiled-projection-provenance-red, task3-failure-class-spec-red, task3-failure-vocabulary-red, task3-internal-snapshot-reflection-red, task3-reflection-provenance-hardening-red, task3-synchronized-authority-red, task4-catalog-spec-gap-red, task4-provider-contract-red, task5-compatibility-red, task5-formal-event-schema, task5-projection-contract-red, task5-projection-slot-shape-red, task5-quality-review-red, task5-slots-mutation-red, task5-timing-wrapper, task5-tuple-backed-red, v189-contract-ref-duplicate-mutation, v189-contract-ref-tdd-red, v189-duplicate-oracle-identity-mutation, v189-evidence-contract-quality-red, v189-evidence-contract-task2-red, v189-evidence-portable-integer-recursion-red, v189-evidence-public-shape-context, v189-fixture-command-error, v189-nested-evidence-portable-integer-red, v189-quality-fix-linked-worktree-index-permission, v189-semver-oversized-component-red, v189-task3-allowlist-assertion-alignment, v189-task3-capability-test-alignment, v189-task3-commit-index-lock-sandbox, v189-task3-commit-index-lock-sandbox-retry, v189-task3-compilation-capability-reflection-red, v189-task3-contract-red, v189-task3-durable-option-allowlist-assertion-alignment, v189-task3-durable-option-allowlist-compatibility, v189-task3-durable-option-allowlist-red, v189-task3-egress-selected-ref-error-vocabulary, v189-task3-egress-unknown-key-red, v189-task3-field-specific-ref-prefix, v189-task3-final-authority-and-field-kind-red, v189-task3-final-review-opaque-ref-private-issue-red, v189-task3-fourth-security-rereview-red, v189-task3-full-allowlist-assertion-alignment, v189-task3-git-index-sandbox-error, v189-task3-git-stage-sandbox-permission, v189-task3-holdout-capability-bypass-red, v189-task3-holdout-initial-state-compatibility, v189-task3-init-whitespace-check, v189-task3-opaque-prefix-binding-red, v189-task3-opaque-ref-camelcase-red, v189-task3-planning-cycle-error, v189-task3-public-wire-promotion-red, v189-task3-review-b-remaining-boundaries-red, v189-task3-second-security-focused-compatibility-failure, v189-task3-second-security-rereview-red, v189-task3-security-rereview-red, v189-task3-third-security-rereview-adversarial-red, v189-task3-typed-value-sensitive-red, v189-task3-validation-seam-implementation-gap, v189-validation-promotion-mutation

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause
