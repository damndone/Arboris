# Agent Operations Foundation v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `model.rerun` 和 `graph.fork` 收敛到同一套可注册、可恢复、并发安全的 Typed Operation lifecycle，并让 LLM、后端验证、Operation Record、AI Activity 和 UI 能力目录共享同一份 capability contract。

**Architecture:** `OperationDefinition`/`OperationRegistry` 是唯一 capability source of truth，保存 scope、risk、proposal/editable schema、confirmation policy、UI 文案和 lifecycle hook identity。新增通用 lifecycle 负责 execution key、claim/lease、effect binding 和 deterministic reconcile；具体 operation 只提供 executor、reconciler、diff 和 verification hook。前端通过只读 capabilities projection 展示边界，Agent tool schema 和 protocol 从同一 registry 生成。

**Tech Stack:** Python/FastAPI/JSONL stores/asyncio、pytest、React/TypeScript、Vitest、现有 Graph/Run/Chain/Fork/Operation stores。

**Constraints:** 只修改 `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.7`；保留当前未提交改动；不修改两个 adversarial review 测试；不创建第二个 worktree；不 push、PR、merge、tag；不调用 DeepSeek 或修改真实用户配置；Agent 不获得任意 shell/Python/文件/网络工具。

## Acceptance contract

```text
proposal_id → operation_record_id → execution_key → zero-or-one effect binding → one terminal Operation Record
```

`model.rerun` 最多绑定一个 child run；`graph.fork` 绑定一个 fork、child Chain 和 child Agent，但不自动产生 child run。Reconcile 只能发现、绑定、验证和补全已有 effect，不能为同一 execution key 再提交一次 pipeline。Global Main Agent、多步骤计划和 V11 数据层 operation 明确不在本里程碑。

## Task 1 — Unified Capability Registry

**Files:** `backend/workbench/agent/operations.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/http/agent_routes.py`, new `tests/test_agent_capabilities.py`, existing proposal/tool/route tests.

- [x] Write RED tests that `model.rerun` and `graph.fork` both expose `scope`, `risk_level`, `confirmation_policy`, operation-specific `proposal_schema`, `editable_schema`, `executor_key`, `reconciler_key`, `diff_builder_key`, `verification_builder_key`, `ui_description`, and `example_prompts`.
- [x] Assert the public capability projection contains only JSON-safe stable hook keys, never callable reprs, provider keys, or other secrets; assert sorted operation ids and unknown-scope behavior.
- [x] Run `.venv/bin/pytest -q tests/test_agent_capabilities.py tests/test_agent_proposal_operations.py` and confirm RED before production changes.
- [x] Extend `OperationDefinition`, populate complete metadata for both registered operations, and add `OperationRegistry.capabilities()`.
- [x] Generate the proposal tool enum, target/changes schema, and Chain Agent protocol operation list from the registry. Remove the literal `allowed_operations=["model.rerun"]` source; retain scope policy so `graph.fork` is enabled only after Task 3 binding is complete.
- [x] Add read-only `GET /agent/capabilities?project_root=&scope=`. It must not create storage or load provider secrets.
- [x] Run the capability, tool, context, proposal, and route suites green.

## Task 2 — Generic lifecycle, claims, recovery, and concurrency

**Files:** new `backend/workbench/agent/execution.py`, existing `operations.py`, `orchestrator.py`, `agent_routes.py`, new `tests/test_agent_operation_lifecycle.py`, existing workflow/route/rerun tests.

- [x] Write RED tests for deterministic `execution_key(proposal_id, revision, fingerprint)`, idempotent `OperationRecordStore.claim_execution()`, different-key conflict, persisted claim, and terminal immutability.
- [x] Run the lifecycle test file and confirm the expected missing-API failure.
- [x] Implement `execution.py` with `execution_key`, `OperationFailpoint`, `NoopFailpoint`, `OperationEffect`, and `OperationClaimConflict`.
- [x] Extend `OperationRecord.execution` with `execution_key`, claim owner/time, lease expiry, and effect bindings. Add locked `claim_execution()` and `bind_effect()`; same key returns the existing claim, a different key fails closed.
- [x] Implement one `WorkbenchOperationLifecycle` entry point that validates preconditions, claims, selects handlers by registry hook key, binds effects, reconciles, appends one terminal state, and emits typed events.
- [x] Register existing rerun and fork implementations as handlers; confirmation routes call the lifecycle entry point.
- [x] Add failpoint tests for crash after claim, before child effect, after child effect, and before terminal reconcile. Assert JSONL/domain-store counts: rerun zero-or-one child run; fork exactly one fork/child Chain/session and zero child runs.
- [x] Add `asyncio.gather()` tests for duplicate confirmation of one proposal, two proposals on one active head, and repeated HTTP confirmation. Require one effect for the first case and fail-closed conflict/stale behavior for competing active-head writes.
- [x] Run lifecycle, workflow, route, and rerun suites green.

## Task 3 — Natural-language `graph.fork`

**Files:** `context_tools.py`, `orchestrator.py`, `agent_routes.py`, Agent frontend API/types/context/panel, existing Agent route/workflow/fixture tests.

- [x] Write a fake-stream RED integration test for “从当前节点创建一个新分支，后续我想测试另一套稳健标准误。” The model must inspect context and contract, then call `propose_operation` for `graph.fork`.
- [x] Assert the target run/node/hash/forest key and `source_session_entry_id` are backend-derived from the reachable current Chain leaf, not invented by the model; assert allowed operations come from the registry.
- [x] Run the focused natural-language fork tests and confirm RED because the current HTTP turn only allows `model.rerun`.
- [x] Generate the fork-specific schema from the registry. In canonicalization, bind the current session leaf and reject a model-supplied entry outside the branch; continue deriving node facts and fingerprints from `NodeOperationContextProvider`.
- [x] Route confirmation and reconciliation through the generic lifecycle. Fork completion creates only fork/child Chain/child Agent and never auto-submits a statistical run.
- [x] Add frontend tests for pending → confirmed → completed fork state, no child-run placeholder, typed fork/Chain/Agent links, and reload recovery. Keep explicit message and graph-node fork tests as separate entrypoints.
- [x] Run the complete Agent backend suite, Agent/Activity/NodeActionMenu Vitest suite, and frontend typecheck.

## Task 4 — Capability boundary UI

**Files:** Agent types/API/composer/panel/context/CSS, new `AgentCapabilityPopover.tsx` and test, existing Agent frontend tests.

- [x] Write RED tests for the bounded composer prompt `询问当前分析，或请求修改当前模型参数并重新运行` and for capability sections generated from backend data, not duplicated JSX labels.
- [x] Add typed `getAgentCapabilities()` hydration and a read-only popover with `当前可以执行`, `可以询问，但不能直接执行`, and `暂不支持` sections. Show risk, confirmation policy, descriptions, and examples from the registry.
- [x] Add honest unavailable rendering when capability loading fails; preserve read-only questions.
- [x] Extend the Chain Agent protocol and fake-model tests so unsupported cleaning/data/code/file/multi-step requests never call `propose_operation` and create no proposal, Operation Record, run, fork, or graph mutation.
- [x] Run capability route tests, unsupported-operation tests, popover/composer/panel Vitest tests, and TypeScript.

## Task 5 — Fixture, browser acceptance, and closeout

**Files:** `backend/workbench/dev_fixtures/agent_navigation.py`, `scripts/seed_agent_navigation_smoke.py`, `docs/dev-browser-smoke.md`, fixture tests, `findings.md`, `progress.md`.

- [x] Extend the deterministic isolated fixture manifest with proposal ids, operation record ids, execution keys, fork/Chain/session ids, and zero/one child-run expectations. The manifest also records the recoverability contract without touching a real project.
- [x] Document two independent browser flows: rerun proposal → confirm → child run → diff → reload; fork proposal/entrypoint → confirm → fork/child Chain/child Agent → reload. Record URL, `/api` proxy, exact project scope, execution key, effect count, AI Activity, and console state. Confirm fork does not auto-run.
- [x] Run the fixture smoke only with a temporary local/fake provider seam; do not call DeepSeek or edit user provider settings. Stop servers and leave the unique scratch fixture.
- [x] Run `git diff --check`, `bash scripts/gate.sh --quick`, `bash scripts/gate.sh`, branch status, and protected-file status. Report test evidence separately from browser evidence.

## Verified 2026-07-15

- Focused Agent/operation suite: `86 passed, 4 warnings`.
- Full gate: backend `1666 passed, 8 skipped`; golden `23 passed`; frontend `128 files / 1109 tests`; TypeScript passed; `GATE PASSED`.
- Browser fixture: source Agent → operation → child run/fork → child graph → child Agent; child graph and child Agent deep-links survived reload; AI Activity showed Main/Chain plus operation/diff associations; capability boundary loaded through `/api/agent/capabilities`.
- Scratch project: `/private/tmp/wb-v17-agent-navigation-20260715-foundation`; no DeepSeek call and no user provider configuration change.

## Completion definition

- `model.rerun` and `graph.fork` use one registry contract and one lifecycle entry point.
- proposal → operation record → execution key → effect binding is durable and idempotent.
- All four failpoint positions converge without duplicate effects.
- Same-proposal confirmation is idempotent; competing same-Chain active-head writes fail closed.
- Natural-language `graph.fork` is available through generated schema and remains confirmation-gated.
- Unsupported operations produce explicit no-mutation behavior and the UI shows the boundary.
- Rerun and fork browser flows both pass with reload and exact scope checks.
- Focused tests, TypeScript, quick gate, full gate, and protected-file checks pass.
- Main Agent routing and multi-operation planning remain deferred to later milestones.
