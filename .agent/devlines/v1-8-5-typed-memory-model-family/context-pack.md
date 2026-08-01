# Frozen Context Pack

Line: `v1-8-5-typed-memory-model-family`
Baseline SHA: `9ff0551c2ecd68ac170b5d8c6550d47c74aca9a6`

## Objective
# v1.8.5 设计 — Typed Memory 作用面 + 模型族契约

> Baseline：`9ff0551`（`origin/main`，tag `v1.8.4`）。worktree
> `.worktrees/workbench-v1.8.5`，branch `workbench-v1.8.5`。

## 为什么先写这份

v1.8.4 的范围漂移不是执行问题：三条 devline 对着各自冻结的 objective 都交付了，
个别还超额。问题是**从来没有一份文档回答过「这个版本整体交付什么」**——
`specs/` 里 v1.8.1/8.2/8.3 都有设计文档，v1.8.4 一份没有，范围只活在逐线的
Context Pack 里。于是版本号被复用成了另一个主题，roadmap §5 至今没同步。

这份文档就是那个缺失的层。**范围以本文件为准，devline 的 objective 是它的切片。**

## 目标

两块互不依赖，可并行，但同属「让已建成的子系统真正作用到 Agent 行为上」：

1. **Typed Memory 作用面**：v1.8.3 建了 3537 行的 `domain_memory` 子系统，但它
   目前只能「被看见」，不能改变任何默认值，且没有任何东西执行它自己的有效期。
2. **模型族契约**：workflow 已能按 `model_family` 分派，但产物准入写成了
   `if model_family == "ols"` 的跳过。加一个族就要加一堆 `if`，DID 家族因此进不来。

## 非目标（明确排除，防止再次漂移）

- **Context Compiler 六层检索链**（Graph 邻域 → 元数据过滤 → 有界投影 → 关键词 →
  语义 → rerank）。`domain_memory/retrieval.py` 现有的谓词匹配够本版用；六层检索
  是另一个量级，单列后续版本。**本版不宣称实现了项目历史检索。**
- 向量库、语义检索、rerank。
- `require_confirmation` 档（与既有 Proposal/Risk 生命周期职责重叠，见 §1.2）。
- 任意公式、代码执行、原始数据浏览、自动执行。
- 新估计器。DID 家族复用既有实现，本版只做工作流准入。

---

## 1. Typed Memory 作用面

### 1.0 现状（v1.8.3 已有，不重建）

`DomainMemoryContentRevision` 已带 `memory_id` / `revision` / `scope` /
`memory_kind`(5 类) / `applicability_predicates` / `compact_lesson` /
`recommended_effect_kind` / `source_summary_refs` / `evidence_status`(3 档) /
`review_after` / `supersedes_revision` / `conflicts_with` / `content_hash`；
`MemoryCandidate` 带 `expires_at`；另有 candidate/approval/validity 记录、
scope、冲突、脱敏、curator、review scheduler。

### 1.1 补齐 Registry 字段

| 新增 | 语义 | 为什么需要 |
|---|---|---|
| `memory_kind` 增 `project_domain_fact` | 财年 4 月起、`customer_id` 是分析单位、某字段单位 mg/L | roadmap 四类分级里唯一没有对应 kind 的一类 |
| `apply_mode` | `inform_only` \| `suggest_default` | 见 §1.2 |
| `vocabulary_version` | 记忆断言所依赖的词汇表版本 | 词汇表变了，记忆的 `recommended_target_refs` 可能指向已不存在的字段 |
| `verifier` | 指向能重新判定该记忆是否仍然成立的具体检查 | 没有 verifier 的 `last_validated_at` 是无法维护的 |
| `last_validated_at` | 上次**验证**通过的时刻 | 与既有 `review_after`（计划性）区分：一个是「该复查了」，一个是「确实还成立」 |

`confidence` **不新增**：既有 `evidence_status` 三档已经承担这个角色，再加一个
连续型置信度会产生两个可互相矛盾的可信度来源。

### 1.2 apply_mode：记忆能改什么

```
apply_mode ∈ { inform_only, suggest_default }
```

- `inform_only`：只作为可见提示进入上下文。当前全部记忆的隐式语义。
- `suggest_default`：**可以改变 typed proposal 的默认值**，但
  - 用户仍必须确认（不绕过 Proposal/Risk 生命周期）；
  - 界面必须显示「这个默认值来自哪条记忆」，带 `memory_id` 与 `revision`；
  - 记忆**永远不能获得 `bypass_validation`**——改默认值不等于跳过当前数据检查。

不做 `require_confirmation`：Workbench 已有 Proposal/Risk 确认生命周期，再引入
一档「记忆要求确认」会产生两套确认语义，谁覆盖谁没有非任意的答案。

**不变量（必须有测试钉死）**
- 一条 `inform_only` 记忆在任何路径上都不改变 proposal 字段。
- 一条 `suggest_default` 记忆改了默认值时，proposal 必须携带其来源；
  来源缺失即 fail-closed，不允许出现「无主的默认值」。
- 记忆不改变 evidence、admission、推荐排序或执行授权（v1.8.3 已有的边界，
  本版扩大 apply_mode 后要重新钉一遍）。

### 1.3 有效性执行者（两层，都要）

**A. 运行时判定（兜底）**
`retrieve_domain_memory` 返回前判定 `expires_at` / `review_after` /
`vocabulary_version`：
- 已过期 → 不返回，记一条 `RetrievalOmission`（现有类型，复用）；
- `vocabulary_version` 与当前词汇表不符 → 不返回，omission 说明版本不符；
- `last_validated_at` 早于 verifier 要求的窗口 → 降级为 `inform_only` 返回，
  **不允许一条久未验证的记忆去改默认值**。

保证：**过期或失效的记忆永远影响不到 Agent**，无需外部调度。

**B. gate.sh preflight（可见性）**
在 gate 里判定仓库内所有已批准记忆的有效性，把「即将过期 / 已失效 /
verifier 缺失」列出来。CI 层可见，但**不阻塞**——阻塞会让一条记忆过期直接把
gate 弄红，与产品正确性无关。

两层职责不同：A 保证正确性，B 保证可见性。只做 B 的话，一条过期记忆在两次
gate 之间仍会影响 Agent；只做 A 的话，没有人会知道记忆正在批量失效。

---

## 2. 模型族契约

### 2.0 现状

`workflow_contracts.py:868` 白名单 `{"ols","panel_ols"}`；panel 必须有
entity/time、ols 必须没有；`workflow_runtime.py:814` 产物 id 由 `model_family`
推导。**但**产物准入与 `model_params` 构造是硬编码分支：

- `:917` `if model_family == "ols"` → 否则填 entity/time
- `:962` `if model_family == "ols" and "diagnostic_summary" not in ids`
- `:966` 无条件要求 `ci_lower`/`ci_upper`
- `:972` `if model_family == "ols" and missing_figures`

panel 没有自己声明的预期产物集，只是**跳过了 ols 的检查**。

### 2.1 `ModelFamilyContract`

把上述硬编码收敛成每族一份声明：

```
ModelFamilyContract:
  family:                  "ols" | "panel_ols" | "cs_did" | "sa_did" | "dcdh"
  required_spec_fields:    ("entity_col","time_col") / ("cohort_col",...) / ()
  forbidden_spec_fields:   ols 拒绝 entity_col/time_col
  build_model_params:      族专属的 model_params 构造
  expected_artifacts:      该族必须产出的 artifact id 集合
  result_shape:            coefficient_intervals | effect_estimate_bundle | event_study_bundle
```

`_run_model_branch` 变为族无关：查契约 → 校验 spec → 构造 params → 执行 →
按契约声明的产物集与结果形状准入。

**关键点**：DID 家族产出的是 `EffectEstimateBundle` / `EventStudyBundle`，
不是带 `ci_lower`/`ci_upper` 的系数表。现在那条无条件的 CI 检查对它们必然误报，
所以 `result_shape` 必须由契约声明，不能继续无条件断言。

### 2.2 扩到 DID 家族

`cs_did` / `sa_did` / `dcdh` 已注册、手动 run form 可跑、各有 golden 护栏。
本版只做**工作流准入**，不碰估计器。

**验收（每族一条，不可省）**
- 该族能从 Notebook 一句话请求 → typed option → 确认 → 执行 → 结果在
  Table/Report 可见。
- 该族的产物**按自己的契约**准入；把 DID 产物误当 OLS 产物、或对
  `EventStudyBundle` 断言 `ci_lower` 的情况，各有一条专门的拒绝测试。
- 缺 `cohort_col` 之类必需字段时 **fail-closed 且给出可执行的下一步**，
  不静默退化为 OLS。
- **golden 23 保持 0-drift**：本版不改任何估计器，数值必须逐位不变。

### 2.3 与 panel 的关系

现有 panel FE 与 dummy FE 的 `1e-8` oracle 继续作为回归护栏。注意它绕过
materialization 直接调 `_compile`，所以它证明的是 **runtime 支持 panel**，
不是证明 materialization 的修复——不要把它当成后者的证据。

---

## 3. 交付顺序

1. `ModelFamilyContract` 抽取 + ols/panel_ols 行为逐位不变（纯重构，golden 0-drift）
2. DID 三族接入 + 每族验收
3. Registry 字段 + `apply_mode` 契约与不变量测试
4. 运行时判定执行者
5. gate preflight 执行者
6. 真机浏览器验收 + release notes + handoff

1 与 3 无依赖，可并行；2 依赖 1；4 依赖 3；5 依赖 4。

## 4. 本版不宣称

- 不宣称实现了项目历史检索 / Context Compiler。
- 不宣称记忆经过独立事实核验——`evidence_status` 是来源分级，不是真值判定。
- DID 家族只宣称**工作流可达**，不重新宣称估计器数值性质（那些由既有 golden
  与各自的 R 对照承担）。

## Boundary
- Affected paths: `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/vocabulary.py`, `backend/workbench/econometrics/runner.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/figure_context.py`, `backend/workbench/domain_memory/contracts.py`, `backend/workbench/domain_memory/retrieval.py`, `backend/workbench/domain_memory/store.py`, `backend/workbench/domain_memory/candidate_store.py`, `backend/workbench/domain_memory/service.py`, `backend/workbench/domain_memory/context_projection.py`, `backend/workbench/domain_memory/curator_contracts.py`, `backend/workbench/domain_memory/review_service.py`, `backend/workbench/domain_memory/review_scheduler.py`, `backend/workbench/domain_memory/preferences.py`, `backend/workbench/agent/notebook/service.py`, `scripts/gate.sh`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/domainMemoryApi.ts`, `frontend/src/notebook/DomainMemoryControls.tsx`, `frontend/src/notebook/DomainMemoryEntryList.tsx`, `tests/test_workflow_runtime.py`, `tests/test_panel_covariance.py`, `tests/test_notebook_routes.py`, `tests/test_notebook_planning_agent.py`, `tests/test_did_runner.py`, `tests/test_did_wiring.py`, `tests/test_cs_did_wiring.py`, `tests/test_domain_memory_candidate_store.py`, `tests/test_domain_memory_context_injection.py`, `tests/test_gate_script.py`
- Allowed paths: `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/vocabulary.py`, `backend/workbench/econometrics/runner.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/figure_context.py`, `backend/workbench/domain_memory/contracts.py`, `backend/workbench/domain_memory/retrieval.py`, `backend/workbench/domain_memory/store.py`, `backend/workbench/domain_memory/candidate_store.py`, `backend/workbench/domain_memory/service.py`, `backend/workbench/domain_memory/context_projection.py`, `backend/workbench/domain_memory/curator_contracts.py`, `backend/workbench/domain_memory/review_service.py`, `backend/workbench/domain_memory/review_scheduler.py`, `backend/workbench/domain_memory/preferences.py`, `backend/workbench/agent/notebook/service.py`, `scripts/gate.sh`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/domainMemoryApi.ts`, `frontend/src/notebook/DomainMemoryControls.tsx`, `frontend/src/notebook/DomainMemoryEntryList.tsx`, `tests/test_workflow_runtime.py`, `tests/test_panel_covariance.py`, `tests/test_notebook_routes.py`, `tests/test_notebook_planning_agent.py`, `tests/test_did_runner.py`, `tests/test_did_wiring.py`, `tests/test_cs_did_wiring.py`, `tests/test_domain_memory_candidate_store.py`, `tests/test_domain_memory_context_injection.py`, `tests/test_gate_script.py`
- Protected paths: none
- Dependencies: none
- Tests: `tests/test_workflow_runtime.py`, `tests/test_panel_covariance.py`, `tests/test_did_runner.py`, `tests/test_did_wiring.py`, `tests/test_cs_did_wiring.py`, `tests/test_domain_memory_candidate_store.py`, `tests/test_domain_memory_context_injection.py`, `tests/test_gate_script.py`
- Known gates: `link-shared-deps uses absolute worktree path`, `stop vite before scripts/gate.sh --full`, `run native containment gate only outside nested Seatbelt`, `preserve golden 23 at zero drift; do not modify estimators`, `tsc exit status must not be read from a piped tail command`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-mem2-domain-memory (2026-07-27T11:05:00.000Z)

Completed formal devline v1-8-3-mem2-domain-memory; final_state=COMPLETED; failure_lesson_keys=domain-memory-contract-first, frontend-api-awaits-response

### v1-8-3-cf4-notebook-planner-projection-r1 (2026-07-26T23:16:01.000Z)

Completed formal devline v1-8-3-cf4-notebook-planner-projection-r1; final_state=COMPLETED; failure_lesson_keys=bounded-planner-projection-inputs, consumer-admission-facts-align-across-contracts, scope-aware-bound-option-revalidation, tdd-red-before-planner-projection

### v1-8-3-cf4-binding-provenance (2026-07-27T06:42:00.000Z)

Completed formal devline v1-8-3-cf4-binding-provenance; final_state=COMPLETED; failure_lesson_keys=binding-provenance-contract-red
