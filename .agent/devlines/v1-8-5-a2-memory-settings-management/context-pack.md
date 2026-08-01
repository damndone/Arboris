# Frozen Context Pack

Line: `v1-8-5-a2-memory-settings-management`
Baseline SHA: `b5f2a9c3300ec89b7f551f0d6735af7f64116877`

## Objective
# v1.8.5 开工对接书（Claude Code / Codex 通用）

本文件是新会话的**唯一入口**。照 §1 → §2 → §3 顺序做，不要跳。
所有事实以仓库内文件为准；本文件里的路径都已核验存在。

---

## 0. 三十秒摘要

- **上一版 v1.8.4 已发布**：`origin/main` = tag `v1.8.4` = `9ff0551`。
- **本版 v1.8.5** 做两块，互不依赖：**Typed Memory 作用面** + **模型族契约**。
- **工作目录**：`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.5`
  branch `workbench-v1.8.5`，baseline `9ff0551`；当前 HEAD 是在该 baseline
  之上的 docs-only kickoff commit（开工前用 `git log -1` 核准，不把本文件里的
  自身提交号当作固定值）。
- **尚未开 FMS 开发线，尚未写任何代码。**

---

## 1. 必读文件（按顺序，共 4 份）

| 顺序 | 文件 | 读它干什么 |
|---|---|---|
| 1 | `docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md` | **本版范围的唯一权威**。含已拍板的四个决策与明确排除项 |
| 2 | `docs/superpowers/README.md` | 文档七类生命周期约定（handoff 只留最新 / BACKLOG 唯一滚动 / 发版归档） |
| 3 | `docs/superpowers/followups/BACKLOG.md` §1 | 当前所有欠账；`V1.8.5-TYPED-MEMORY` 是本版行 |
| 4 | `docs/releases/v1.8.4-release-notes.md` 的「明确不宣称」段 | 上一版留下的边界，本版不得悄悄跨过 |

读代码前先读 §1 的第 1 份。**不要**从 `git log` 或某条 devline 的 Context Pack
反推本版范围——v1.8.4 就是这么漂移的。

---

## 2. 开工前置（顺序不可换）

### 2.1 环境自检

```bash
cd "/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.5"
git status --short && git log --oneline -1     # 期望：干净，且 HEAD 仍为 docs-only commit
ls -l .venv frontend/node_modules              # 期望：两个都是符号链接
```

`.venv` 或 `node_modules` 不存在时：

```bash
bash scripts/link-shared-deps.sh "/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.5"
```

**worktree 一律共用主 checkout 的依赖，不得自己 `pip install` / `npm install`。**

### 2.2 沙箱自检（Codex 必做，Claude Code 也建议做一次）

```bash
/usr/bin/sandbox-exec -p '(version 1) (allow default)' /bin/echo sandbox-selftest-ok
```

**输出不是 `sandbox-selftest-ok` 就说明你在一个 Seatbelt 沙箱里。**
macOS 拒绝嵌套 `sandbox_apply`，产品的 Darwin containment 会 shell out 到
`/usr/bin/sandbox-exec`，于是约 20 个 containment 测试必然失败。

这**不是**本机限制，**不是**产品缺陷。v1.8.4 有一轮就把它误记成了「既知本机限制，
full gate 未绿」，事后被同主机同 commit 的重跑推翻。

- 自检失败 → 脱离沙箱（Codex：`--sandbox danger-full-access` 或在 Codex 之外的
  终端跑 gate）。
- **绝不允许**用 skip / xfail / 弱化 sandbox 让它「变绿」。

### 2.3 开 FMS 开发线（ADR-PD-001 硬约束）

**allowlist 必须一次列全。** v1.8.4 因为边做边 rescope 做了 12 次；更要命的是
**`backend/workbench/*.py` 这一层（3 段路径）事后根本 rescope 不进去**——校验器
拒绝 `len(parts) < 4` 的 backend 路径。想改 `model_terms.py` / `figure_context.py`
就只能在 `start` 时写死，否则只能另开一条线。

建议的 allowlist（宁多勿少，多列不产生代价）：

```
# 模型族契约
backend/workbench/agent/workflow_contracts.py
backend/workbench/agent/workflow_runtime.py
backend/workbench/agent/notebook/materialization.py
backend/workbench/agent/notebook/planning_agent.py
backend/workbench/agent/notebook/vocabulary.py
backend/workbench/econometrics/runner.py
backend/workbench/engine/capabilities.py
backend/workbench/figure_context.py          # 3 段路径，必须此刻声明

# Typed Memory
backend/workbench/domain_memory/contracts.py
backend/workbench/domain_memory/retrieval.py
backend/workbench/domain_memory/store.py
backend/workbench/domain_memory/candidate_store.py
backend/workbench/domain_memory/service.py
backend/workbench/domain_memory/context_projection.py
backend/workbench/domain_memory/curator_contracts.py
backend/workbench/domain_memory/review_service.py
backend/workbench/domain_memory/review_scheduler.py
backend/workbench/domain_memory/preferences.py
backend/workbench/agent/notebook/service.py
scripts/gate.sh

# 前端
frontend/src/notebook/domainMemoryContracts.ts
frontend/src/notebook/domainMemoryApi.ts
frontend/src/notebook/DomainMemoryControls.tsx
frontend/src/notebook/DomainMemoryEntryList.tsx

# 测试
tests/test_workflow_runtime.py
tests/test_panel_covariance.py
tests/test_notebook_routes.py
tests/test_notebook_planning_agent.py
tests/test_did_runner.py
tests/test_did_wiring.py
tests/test_cs_did_wiring.py
tests/test_domain_memory_candidate_store.py
tests/test_domain_memory_context_injection.py
tests/test_gate_script.py
```

命令形状（`--objective` 要一个**仓库相对**的文件路径）：

```bash
PYTHONPATH=backend .venv/bin/python scripts/devline_control.py start \
  --line v1-8-5-model-family-contract \
  --objective <仓库相对的 objective 文件> \
  --baseline-sha 9ff0551c2ecd68ac170b5d8c6550d47c74aca9a6 \
  --affected-path <每个一次> --allowed-path <每个一次>
```

**FMS 枚举坑（v1.8.4 全踩过一遍）**
- `type` 没有 `FIX` —— 用原 type + `resolution`
- `stage` 没有 `verification` —— 用 `gate`
- `resolution` 用 `resolved` / `not_applicable`，**不是** `fixed`
- 关线 = append `STATE_CHANGE` 且 `state_to: COMPLETED`（自动生成 RETROSPECTIVE）
- 事件文件必须在**仓库内**的相对路径
- **`timestamp` 用当前时刻**：关闭事件若早于被关闭的事件，按时间排序会读成仍 open
- 不手改 `.agent/devlines/`，一切走 CLI

两块可以开两条线（`v1-8-5-model-family-contract` / `v1-8-5-typed-memory-effect`），
也可以合一条。开两条的话 allowlist 各自列全。

---

## 3. 执行方式

### 3.1 交付顺序（依赖关系已定）

```
1 抽 ModelFamilyContract，ols/panel_ols 行为逐位不变   ← 纯重构，先做
2 DID 三族接入（cs_did / sa_did / dcdh）               ← 依赖 1
3 Registry 字段 + apply_mode 契约与不变量测试          ← 与 1 无依赖，可并行
4 运行时判定执行者                                      ← 依赖 3
5 gate preflight 执行者                                 ← 依赖 4
6 真机浏览器验收 + release notes + handoff
```

### 3.2 TDD 硬要求

**每个改动都要有一条先失败后通过的测试。**
提交前用 `git stash` 或临时回退实现，**贴出它失败时的输出**。
「测试通过了」不是证据——v1.8.4 有一轮就是靠引用早已存在的测试关闭了 6 条 incident。

自查方式（对任何声称「已修复」的条目都适用）：

```bash
git log -S "def <test_name>" -- <测试文件>   # 该测试是哪个 commit 引入的？
git show --stat <你的 commit>                # 对应生产模块有没有改动？
```

测试引入 commit 早于本次工作、或生产模块一行未改 —— 那就不是修复，
是**核实为既有行为**，必须如实这么记（见 §3.3）。

### 3.3 三种诚实的结论

不是每条都得改代码。判定顺序：

| 情形 | 何时 | 怎么记 |
|---|---|---|
| **A 已满足** | baseline 已经做到了 | `resolution: resolved`，`subtype` 用 `_verified_preexisting`，事件里给出**确切的 commit:file:line**；**不写进 release notes 交付段** |
| **B 需要修** | 确实缺 | 正常修 + 先失败后通过的测试 + 生产模块改动 |
| **C 诊断有误** | 前提不成立 | `resolution: not_applicable` + 反证；**不许为了有个结论硬安一个修复** |

### 3.4 关键实现约束

**模型族契约**
- `workflow_runtime.py:962 / :972` 的 `if model_family == "ols"` 与 `:966`
  **无条件**的 `ci_lower`/`ci_upper` 断言，都要收敛进契约。
- DID 产出 `EffectEstimateBundle` / `EventStudyBundle`，**不是**带 CI 的系数表。
  那条无条件 CI 断言对它们必然误报——这是接 DID 的第一个拦路石。
- DID 估计器在 `backend/workbench/econometrics/runner.py`
  （`run_cs_did:1262` / `run_sa_did:1289` / `run_dcdh:1315`），
  能力注册在 `backend/workbench/engine/capabilities.py:110-122`。
  **本版只做工作流准入，不碰估计器。**
- 现有 panel FE vs dummy FE 的 `1e-8` oracle 继续作护栏。注意它绕过
  materialization 直接调 `_compile`，证明的是 **runtime 支持 panel**，
  不是证明 materialization 的修复——别把它当后者的证据。

**Typed Memory**
- v1.8.3 已建 22 模块 3537 行，Registry 字段**大半已存在只是换了名**
  （`memory_kind` / `compact_lesson` / `source_summary_refs`+`evidence_status`
  / `expires_at`）。**先读 `contracts.py` 再动手，不要重建。**
- `confidence` **故意不加**：`evidence_status` 三档已承担，再加连续型置信度会造出
  两个可互相矛盾的可信度来源。
- 执行者两层职责不同：**运行时判定保正确性**（过期即不返回并记 `RetrievalOmission`；
  久未验证的降级为 `inform_only`，不许改默认值）；**gate preflight 保可见性且不阻塞**
  （一条记忆过期把 gate 弄红，与产品正确性无关）。只做 preflight 的话，过期记忆在
  两次 gate 之间仍会影响 Agent。

---

## 4. 验收标准

### 4.1 每个改动

- [ ] 有一条先失败后通过的测试，**失败输出已贴出**
- [ ] 结论按 §3.3 归入 A / B / C，事件用对应 `subtype`
- [ ] 情形 A / C **不进 release notes 交付段**

### 4.2 模型族契约

- [ ] 步骤 1 是**纯重构**：`golden 23 保持 0-drift`，ols/panel_ols 数值逐位不变
- [ ] DID 三族**各有一条**端到端：Notebook 一句话 → typed option → 确认 → 执行 →
      结果在 Table/Report 可见
- [ ] 把 DID 产物误当 OLS 产物、对 `EventStudyBundle` 断言 `ci_lower` —— **各有一条
      专门的拒绝测试**
- [ ] 缺必需字段（如 `cohort_col`）时 **fail-closed 且给出可执行的下一步**，
      不静默退化为 OLS

### 4.3 Typed Memory

- [ ] `inform_only` 记忆在**任何路径**上都不改变 proposal 字段（不变量测试）
- [ ] `suggest_default` 改了默认值时，proposal **必须携带来源**（`memory_id`+`revision`）；
      来源缺失即 fail-closed，不允许出现「无主的默认值」
- [ ] 记忆**永远不能**获得 `bypass_validation`，不改变 evidence / admission /
      推荐排序 / 执行授权
- [ ] 过期或 `vocabulary_version` 不符的记忆**不返回**，并记 `RetrievalOmission`
- [ ] gate preflight 列出即将过期 / 已失效 / 缺 verifier 的记忆，**且不阻塞**

### 4.4 收尾 gate（发版前必须）

```bash
# 先停 vite（gate.sh:86 见到 vite 就 REFUSING）
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 bash scripts/gate.sh --full
PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --all
PYTHONPATH=backend .venv/bin/python scripts/devline_control.py index --all
```

**基线（v1.8.4 实测，只许涨不许跌）**

| 阶段 | 基线 |
|---|---|
| backend | 4253 passed / 8 skipped / 1 xfailed |
| golden / invariants | 23 passed，**0-drift** |
| frontend | 171 files / 1513 tests |
| tsc | 通过 |
| `sandbox_apply` 失败 | **0** |

- [ ] `>>> GATE PASSED`，且**在非嵌套 Seatbelt 的宿主终端**跑出
- [ ] `verify --all` 通过，所有新线 COMPLETED + indexed
- [ ] golden **0-drift**——本版不改估计器，数值必须逐位不变

### 4.5 文档收尾

- [ ] 新建 `docs/releases/v1.8.5-release-notes.md`：只写情形 B 的交付；
      「明确不宣称」段必须包含「**本版不宣称实现了项目历史检索 / Context Compiler**」
- [ ] BACKLOG 的 `V1.8.5-TYPED-MEMORY` 行按实际剩余更新
- [ ] 新 handoff 写好后，把本文件移进 `docs/superpowers/archive/handoff/`
      （handoff 只留最新一份），并修好指向它的链接
- [ ] 服务恢复

---

## 5. 边界（违反即作废）

1. **不手改 `.agent/devlines/`**，一切走 `scripts/devline_control.py`。
2. **不只改测试让它通过。** 两份测试互相矛盾时，先判定哪份编码的是**已实现的契约**，
   把过期的改写到实现契约上，并把它原本主张的东西**拆成独立断言保留**，不要删。
   结构性护栏若必须放宽，每处豁免要配一条**新的真实断言**。
3. **不宣称没验的东西。**「测试通过」「浏览器验收」「发版」是三件事，分开写。
   真机验收只用 Workbench 内置浏览器，不得用 HTTP 直连或外部浏览器替代
   （那样得到的不是 UI 验收）。
4. **不改估计器。** DID 只做工作流准入；`golden 23` 是这条的护栏。
5. **记忆不得获得 `bypass_validation`**，也不得跳过当前数据检查。
6. **六层检索链不在本版。** 不得顺手引入向量库 / 语义检索 / rerank。
7. **push / PR / merge / tag 不要自己走**，交回用户决定。

---

## 6. 常见坑速查

| 症状 | 原因 | 处理 |
|---|---|---|
| 约 20 个 containment 测试失败 `sandbox_apply: Operation not permitted` | 你在 Seatbelt 沙箱里，macOS 拒绝嵌套 | 跑 §2.2 自检；脱离沙箱重跑 |
| `gate.sh` 立即 `REFUSING` | vite 或 vitest 在跑 | 先停掉 |
| `rescope-context` 拒绝 `backend/workbench/xxx.py` | 校验器拒绝 `len(parts) < 4` | 只能新开一条线并在 `start` 时写进 allowlist |
| 中文路径下测试假失败 | 缺 UTF-8 locale | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8` |
| 全套件才失败、单跑通过 | `EventManager` 单例 run-slot 泄漏 | 加 autouse 的 `get_event_manager()._reset_for_testing()` fixture |
| 新 worktree 缺依赖 | 没 link | `bash scripts/link-shared-deps.sh <绝对路径>` |
| shell `cd` 后又回到主 checkout | cwd 会重置 | 每条命令用绝对路径，或 `cd ... && ...` 串起来 |

## Boundary
- Affected paths: `backend/workbench/app.py`, `backend/workbench/domain_memory/local_runtime.py`, `backend/workbench/domain_memory/local_preferences.py`, `backend/workbench/domain_memory/confirmation.py`, `backend/workbench/domain_memory/contracts.py`, `backend/workbench/domain_memory/preferences.py`, `backend/workbench/domain_memory/scope.py`, `backend/workbench/domain_memory/store.py`, `backend/workbench/domain_memory/candidate_store.py`, `backend/workbench/domain_memory/conflicts.py`, `backend/workbench/domain_memory/service.py`, `backend/workbench/domain_memory/review_service.py`, `backend/workbench/domain_memory/retrieval.py`, `backend/workbench/domain_memory/context_projection.py`, `backend/workbench/http/memory_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/agent/notebook/service.py`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/MemorySettingsPanel.tsx`, `frontend/src/workbench/MemorySettingsPanel.test.tsx`, `frontend/src/llm/LlmProviderManager.tsx`, `frontend/src/notebook/DomainMemoryControls.tsx`, `frontend/src/notebook/domainMemoryApi.ts`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `tests/test_domain_memory_local_preferences.py`, `tests/test_domain_memory_confirmation.py`, `tests/test_domain_memory_local_runtime.py`, `tests/test_domain_memory_routes.py`, `tests/test_memory_review_routes.py`, `tests/test_domain_memory_candidate_store.py`, `tests/test_memory_integration_context.py`, `tests/test_notebook_routes.py`
- Allowed paths: `backend/workbench/app.py`, `backend/workbench/domain_memory/local_runtime.py`, `backend/workbench/domain_memory/local_preferences.py`, `backend/workbench/domain_memory/confirmation.py`, `backend/workbench/domain_memory/contracts.py`, `backend/workbench/domain_memory/preferences.py`, `backend/workbench/domain_memory/scope.py`, `backend/workbench/domain_memory/store.py`, `backend/workbench/domain_memory/candidate_store.py`, `backend/workbench/domain_memory/conflicts.py`, `backend/workbench/domain_memory/service.py`, `backend/workbench/domain_memory/review_service.py`, `backend/workbench/domain_memory/retrieval.py`, `backend/workbench/domain_memory/context_projection.py`, `backend/workbench/http/memory_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/agent/notebook/service.py`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/MemorySettingsPanel.tsx`, `frontend/src/workbench/MemorySettingsPanel.test.tsx`, `frontend/src/llm/LlmProviderManager.tsx`, `frontend/src/notebook/DomainMemoryControls.tsx`, `frontend/src/notebook/domainMemoryApi.ts`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `tests/test_domain_memory_local_preferences.py`, `tests/test_domain_memory_confirmation.py`, `tests/test_domain_memory_local_runtime.py`, `tests/test_domain_memory_routes.py`, `tests/test_memory_review_routes.py`, `tests/test_domain_memory_candidate_store.py`, `tests/test_memory_integration_context.py`, `tests/test_notebook_routes.py`
- Protected paths: none
- Dependencies: `v1-8-5-a1-local-memory-bootstrap`, `v1-8-5-typed-memory-model-family`, `v1-8-5-workflow-memory-integration`
- Tests: `tests/test_domain_memory_local_preferences.py`, `tests/test_domain_memory_confirmation.py`, `tests/test_domain_memory_routes.py`, `tests/test_memory_review_routes.py`, `tests/test_memory_integration_context.py`, `frontend/src/workbench/MemorySettingsPanel.test.tsx`
- Known gates: `all local and project memory toggles default off and may only change after a short-lived bound confirmation`, `deleting a memory tombstones future use but preserves historical run provenance`, `the browser never provides scope, owner identity, or durable preference authority`, `local state must reject unsafe roots and never fall back to temporary unaudited storage`, `full gate requires stopping user-owned Vite and a non-nested Seatbelt host`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-mem2-domain-memory (2026-07-27T11:05:00.000Z)

Completed formal devline v1-8-3-mem2-domain-memory; final_state=COMPLETED; failure_lesson_keys=domain-memory-contract-first, frontend-api-awaits-response

### v1-8-3-cf4-server-recommendation-stage (2026-07-27T06:24:00.000Z)

Completed formal devline v1-8-3-cf4-server-recommendation-stage; final_state=COMPLETED; failure_lesson_keys=server-recommendation-red

### v1-8-3-cf4-notebook-planner-projection-r1 (2026-07-26T23:16:01.000Z)

Completed formal devline v1-8-3-cf4-notebook-planner-projection-r1; final_state=COMPLETED; failure_lesson_keys=bounded-planner-projection-inputs, consumer-admission-facts-align-across-contracts, scope-aware-bound-option-revalidation, tdd-red-before-planner-projection

### v1-8-3-cf4-notebook-provider-injection (2026-07-26T22:45:00.000Z)

Completed formal devline v1-8-3-cf4-notebook-provider-injection; final_state=COMPLETED; failure_lesson_keys=formal-rescope-boundary, tdd-red-before-provider-injection

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work
