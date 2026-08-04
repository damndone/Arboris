# Frozen Context Pack

Line: `v1-8-6-predictive-research-foundation`
Baseline SHA: `7e257f2e4fc7ac3b75d68dd270c33021dffad530`

## Objective
# Workbench v1.8.6 Predictive Research Foundation 实施计划

状态：设计范围已由接手说明确认；本计划是唯一中央实施计划。生产改动必须在正式 FMS
开发线建立后进行，并遵守每阶段先红后绿。

## Objective

从 `origin/main=7e257f2e4fc7ac3b75d68dd270c33021dffad530` 建立 v1.8.6 正式线，在不修改
v1.8.5 release、main 本地证据或历史 artifact 的前提下，为通用表格回归建立可复现且
fail-closed 的 Predictive Research 正确性基础：持久化 typed SampleSpec（含抽样权重、
结构、可得性、FeatureRecipe）、显式 SplitPlan 与 fold 隔离预处理，可信 OOS prediction、
baseline、permutation/noise controls、最小 payload schema gate，并把证据投影到 Graph、
Table、Report、Compare、Agent；另以不重叠的 statistical_tests.py slice 提供统一统计
证据。不得把 temporal/panel/完整 PIT/Quant/自动调参/任意 code.execute 或实盘能力伪装为
本版交付。

## 固定基线与约束

- 工作树：`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.6`
- 分支：`workbench-v1.8.6`
- 基线：`origin/main`、`v1.8.5` 与工作树创建点均为 `7e257f2e4fc7ac3b75d68dd270c33021dffad530`
- 正式线：只用 `PYTHONPATH=backend python3 scripts/devline_control.py start`
- 依赖：复用链接的 `.venv` 与 `frontend/node_modules`；不安装依赖、不访问网络、不暴露密钥
- 核心原则：TDD；先观察真实失败，再实现；未知结构、权重语义、recipe、schema、可得性
  或 split profile 均不得静默降级；旧 prediction 只读兼容且与新结果不可比
- 禁止：push、PR、merge、tag、修改 main/v1.8.5、重写历史证据、删除 durable worktree、
  任意 Python/SQL/code.execute、Quant/PIT/交易、深度学习、超参数平台、数据 reshape/merge

## 交付阶段

### 1. Contracts and schema gate

新增共享 contract 内核，定义 SampleSpec/SamplingSpec/StructureSpec/AvailabilitySpec、
FeatureRecipe、SplitPlan 与新 packet 的 `payload_schema/schema_version` envelope。扩展
artifact registry 校验，使 producer 在 index 更新前验证，consumer 对未知版本保留身份但
拒绝解释。sampling_weight、analysis_weight、frequency_weight 必须分别表达；不支持时
fail-closed，不能转换或忽略。

红测：缺字段/类型/非有限数/未知版本、未知结构、权重冲突、缺可得性 reservation、未知
recipe 和重复运行 hash 不变量。

### 2. Split and fold preprocessing

实现随机/分组声明与可复用 SplitPlan；持久化 random/grouped/temporal 参数（含 group/time/
entity、ratio、fold、seed、shuffle、gap、embargo 和来源）。IID/Grouped 可执行；unknown
阻塞；temporal/panel 仅校验并拒绝随机执行。共享 fold kernel 保证 imputation/MICE/均值中位数
填补、scaling、feature select、PCA、target encoding 等 fit-state 只在当前训练 fold 拟合。
保留 `stateless` 与 `date_local` 语义，不把后者当作 period fit。

红测：global scaling、test-fold imputation、先 fit 后 split、group 泄漏、final holdout 进入
CV，以及 temporal/panel 误走 random。

### 3. Prediction, baseline, controls and legacy boundary

在既有 prediction 入口接入协议，不新增 fixed test_size/alpha/cv 常量。所有候选与 mean
baseline 共享同一 SplitPlan；新 PredictionPacket/EvaluationPacket 记录 assumptions、fit
folds、各 partition n、row predictions、OOS metrics、baseline、controls、limits。实现 seeded
permutation target、seeded noise feature 和 future-shift conformance；legacy artifact 不
生成伪 SplitPlan、不回写、不与新结果 Compare。

红测：final holdout 隔离、同 seed 可复现、置换/噪声退化、future-shift 在 estimator.fit 前
拒绝且不产生 packet、legacy/new Compare 稳定拒绝。

### 4. FeatureRecipe

注册 deterministic derived variable、recode、interaction、log、ratio；记录输入/输出/类型/
参数/version/fit scope/source artifact/parent/missing/outlier/reproducibility。零值、负值、
缺失、异常值策略必须显式；未知操作、动态表达式、dataset/exercise 分支和默认 code.execute
拒绝。recipe 输出绑定 SampleSpec/TaskSpec，消费者不临时重算。

### 5. Independent statistical slice

只修改 `backend/workbench/statistical_tests.py` 及对应测试/证据投影。新增 posthoc ANOVA、
Tukey/Bonferroni、Cohen d、eta/omega squared、one-sample t、paired t、Wilcoxon signed-rank、
Levene/Bartlett、Shapiro-Wilk；统一输出 assumptions、warnings、effect size、CI（适用时）、
校正范围和 finite/degenerate 状态。保持既有检验/FDR/估计器行为，不自动参与 prediction
model selection。

### 6. Consumers, UI and release evidence

让 Graph/Table/Report/Compare/Agent 只读取已验证、版本匹配的 packet，引用同一 Sample/Split/
Evaluation/Control lineage。更新预测 UI 以显示结构确认、实际 SplitPlan 参数、OOS/baseline/
control/limits；未知结构提供可执行下一步。最后分别记录自动化测试、native browser（未做前
均为 `NOT VERIFIED`）和 `bash scripts/gate.sh` full gate；不把其中任一证据替代另一项。

## 验证顺序

每个阶段均执行：

1. 新增或改写测试并确认修复前真实失败；
2. 实现最小改动；
3. 运行阶段 targeted pytest/TypeScript/Vitest（不直接 TypeScript `| tail`）；
4. `git diff --check`、allowlist 检查、FMS event append/verify；
5. 记录 changed files、红证据、绿证据、能力、gap、风险和是否 scope expansion。

收尾前运行相关 targeted gate、`bash scripts/gate.sh --quick`，最后在允许的本机服务状态下
运行 full gate；browser interaction、性能、containment、release/merge/tag 分别记账。任何
网络/依赖/沙箱能力问题单独记录，不得 skip/xfail 冒充产品通过。

## Allowlist / protected boundary

Allowlist 由正式 Context Pack 固定，覆盖本计划、既有 v1.8.6 design、
`backend/workbench/predictive_research`、预测/artifact/domain/engine/agent/report 相关现有
文件、`statistical_tests.py`、预测 UI 和对应 tests。统计独立阶段不能扩展到预测主链路。

Protected：`.agent/devlines` 中既有线、`.worktrees/workbench-v1.8.5`、v1.8.5 release notes/
handoff/design、main 本地证据 `7e011cb/82dab81` 所涉及文件、backup branch、所有未列入
allowlist 的 estimator/consumer/test 文件。冻结范围若确需扩展，只能通过
`scripts/devline_control.py rescope-context --line ... --affected-path ... --allow-path ...`，
并先记录 RESCOPE/STATE_CHANGE 事件。

## 完成定义

完成必须同时满足修订设计文件第 13、14、15、17 节验收：新协议 evidence 可复现、可追溯、
可比较且 fail-closed；legacy 可读但明确未验证；统计 slice 独立且不改变既有估计器；
Graph/Table/Report/Compare/Agent/UI 从同一证据读取；自动化、browser、full gate、FMS 验证
分别有证据。未 push/PR/merge/tag，除非用户另行明确授权。

## Boundary
- Affected paths: `docs/superpowers/specs/2026-08-01-v1.8.6-predictive-research-correctness-foundation-design.md`, `docs/superpowers/plans/2026-08-02-v1.8.6-predictive-research-foundation-plan.md`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/notebook/artifact_contract.py`, `backend/workbench/agent/notebook/vocabulary.py`, `backend/workbench/report_contract.py`, `frontend/src/runForm/PredictionControls.tsx`, `frontend/src/runResult/PredictionResultCard.tsx`, `frontend/src/runResult.tsx`, `tests/predictive_research/test_agent_evidence_v186.py`, `tests/test_prediction_request.py`, `tests/test_artifacts.py`, `tests/test_agent_context_tools.py`, `tests/test_report_contract.py`, `tests/test_report_view_model.py`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.6-predictive-research-correctness-foundation-design.md`, `docs/superpowers/plans/2026-08-02-v1.8.6-predictive-research-foundation-plan.md`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/notebook/artifact_contract.py`, `backend/workbench/agent/notebook/vocabulary.py`, `backend/workbench/report_contract.py`, `frontend/src/runForm/PredictionControls.tsx`, `frontend/src/runResult/PredictionResultCard.tsx`, `frontend/src/runResult.tsx`, `tests/predictive_research/test_agent_evidence_v186.py`, `tests/test_prediction_request.py`, `tests/test_artifacts.py`, `tests/test_agent_context_tools.py`, `tests/test_report_contract.py`, `tests/test_report_view_model.py`
- Protected paths: `.agent/devlines`, `.worktrees/workbench-v1.8.5`, `docs/releases/v1.8.5-release-notes.md`, `docs/superpowers/handoff/2026-07-31-v1.8.5-kickoff-handoff.md`, `docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`, `docs/superpowers/specs/2026-08-01-v1.8.6-predictive-research-correctness-foundation-design.md`, `docs/superpowers/handoff/2026-07-25-v1.8.2-to-codex.md`, `findings.md`, `progress.md`, `task_plan.md`
- Dependencies: `origin/main and v1.8.5 tag both resolve to 7e257f2e4fc7ac3b75d68dd270c33021dffad530`, `v1.8.5 release worktree remains read-only at .worktrees/workbench-v1.8.5`, `shared .venv Python 3.14.6 has pytest, pandas, scipy, jsonschema; sklearn and imblearn are absent`, `frontend/node_modules is linked from main; no dependency installation or network access`, `v1.8.5 release notes, handoff, design, FMS Context Pack and retrospective were read before start`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/predictive_research`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_prediction_models.py tests/test_prediction_request.py`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_statistical_tests.py tests/test_statistical_tests_extended.py`, `bash scripts/gate.sh --quick`, `bash scripts/gate.sh`
- Known gates: `TDD: each production change requires fresh red evidence before implementation`, `full gate historically passed v1.8.5 but must be rerun on changed code`, `native browser selection and interaction evidence is NOT VERIFIED until performed`, `sandbox-exec failure is an environment symptom, not a skip or xfail`, `pgrep is unavailable because sysmond is missing; gate preflight must classify process-state evidence`, `local macOS only; do not expose or install DeepSeek credentials`

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

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-b3-recipe-default-materialization (2026-08-01T20:48:00.000Z)

Completed formal devline v1-8-5-b3-recipe-default-materialization; final_state=COMPLETED; failure_lesson_keys=external-memory-projection-utf8-budget, generic-memory-omissions-must-fit-context-contract, memory-payload-budget-is-utf8-bytes, memory-projection-budget-must-cover-envelope, recipe-default-bridge-currentness-and-omission-budget, recipe-default-groups-must-be-budget-atomic, recipe-default-materialization-before-provider-choice, recipe-default-truncation-must-fail-closed, recipe-defaults-not-generic-provider-hints

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox
