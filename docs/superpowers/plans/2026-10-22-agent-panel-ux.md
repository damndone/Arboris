# Agent Panel UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `docs/superpowers/specs/2026-10-22-agent-panel-ux-design.md`: a resizable docked panel, one mode control, per-model thinking and context in the model picker, and a calmer transcript.

**Architecture:** Thinking effort and its support become declared fields of the provider's model record (like `supports_1m`); the LLM client reads them, with `WORKBENCH_REASONING_EFFORT` still first. The composer gets two small popover components (mode, model) replacing the select and the shield; the run controls shrink to a steer toggle and a resume banner. CSS fixes the docked resize handle and the flex shrink that let the error overlap the transcript.

**Tech Stack:** FastAPI + dataclasses (backend), React + Vite + Vitest (frontend), generated OpenAPI types (`scripts/generate_api_types.py`).

**Constraint:** The scheduled free-route Auto rerun starts 2026-10-23 13:05 UTC from this worktree with `WORKBENCH_REASONING_EFFORT=none`; the environment variable must keep overriding any stored effort.

---

## File map

| File | Change |
|---|---|
| `backend/workbench/llm/provider_store.py` | `ModelRecord.reasoning_effort`, `ModelRecord.supports_reasoning_effort` (default from the V4 model-name rule when absent) |
| `backend/workbench/llm/config.py` | `LLMConfig.reasoning_effort` from the active model record |
| `backend/workbench/llm/client.py` | `agent_reasoning_effort(config)`: env, else the record's effort, else `high` |
| `backend/workbench/http/llm_routes.py` | `ProviderModelRequest` accepts both fields |
| `frontend/src/generated/api-schema.ts` | regenerated |
| `tests/test_llm_model_reasoning_effort.py` | new |
| `frontend/src/workbench/agent/AgentSurfaceContext.tsx` | `setModelSettings(requestModel, patch)` |
| `frontend/src/workspace/agent/AgentModelMenu.tsx` (+css, test) | new: model list, Thinking, Context |
| `frontend/src/workspace/agent/AgentModeMenu.tsx` (+test) | new: three modes, Shift+Tab cycle |
| `frontend/src/workbench/agent/AgentRunControls.tsx` | steer toggle and resume banner only |
| `frontend/src/workspace/agent/AgentColumnComposer.tsx` | uses the two menus; footer note removed |
| `frontend/src/workspace/AgentWindow.tsx`, `agentWindow.css`, `agentColumn.css`, `layoutModel.ts` | docked handle position, 8px hit area, double-click reset, 440 default / 320 min |
| `frontend/src/workbench/agent/AgentPlanPanel.tsx`, `AgentUsagePanel.tsx`, `AgentPanel.tsx`, `agent.css` | collapsed plan, slim usage row, error callout in flow |

## Task 1: Per-model thinking effort (backend)

- [ ] Write `tests/test_llm_model_reasoning_effort.py`:
  - a stored record without the fields loads with `supports_reasoning_effort` true for `workbuddy-ai/deepseek-v4.1-flash` and `deepseek-flash`, false for `glm-5.3-flash-free`; `reasoning_effort` None;
  - `reasoning_effort` outside `none|low|high|max` is refused; round-trip through `to_dict`;
  - `_chat_request_payload` for a V4 config with `reasoning_effort="max"` sends `reasoning_effort: max`; with `"none"` sends `thinking: disabled` and no `reasoning_effort`; with the env var `none` set and record `max`, sends `thinking: disabled` (env wins);
  - `PUT /llm/providers/{id}` with a models list carrying `reasoning_effort` persists it.
- [ ] Run, expect failures; implement; run `tests/test_llm_model_reasoning_effort.py` and the existing `tests/test_llm*` and provider route tests; regenerate types (`python3 scripts/generate_api_types.py`); run `tests/test_api_types_drift.py`; commit.

## Task 2: Model menu (frontend)

- [ ] `setModelSettings(requestModel, {reasoning_effort?, context_window_tokens?})` in `AgentSurfaceContext`: replaces that model in the active provider's `models` via `updateLlmProvider(id, {models})`, updates local providers/config.
- [ ] `AgentModelMenu`: a button showing the model display name and, when set, the effort (e.g. "DeepSeek V4.1 Flash · High"); popover lists models (radio), then *Thinking* segmented Off/Low/High/Max when `supports_reasoning_effort`, then *Context* 128K/1M when `supports_1m`. Escape and outside click close it; disabled while a turn runs.
- [ ] Vitest: lists models; changing effort calls `setModelSettings` with `{reasoning_effort:"max"}`; Thinking hidden for a model without support; Context hidden without `supports_1m`. Commit.

## Task 3: One mode control

- [ ] `AgentModeMenu`: modes `review` (`ask`+`proposal_only`), `read_only` (`ask`+`auto_read_only`), `auto` (`auto`); button label = current mode short name; popover with name + one-line description; `cycleAgentMode` exported and wired to Shift+Tab in the composer textarea.
- [ ] Remove the Mode select from `AgentRunControls`, the shield button and the footer note from the composer.
- [ ] Vitest: each choice sets both execution mode and policy; Shift+Tab cycles; disabled while running. Update existing composer tests. Commit.

## Task 4: Running controls

- [ ] `AgentRunControls`: while a turn runs and `queueTurnMessage` exists, one small toggle "Steer" (off = queue follow-up); Enter in the composer while running sends via `queueTurnMessage(steer ? "steer" : "follow_up", prompt)`. Unfinished turns: one banner "Previous turn unfinished · Resume".
- [ ] Vitest for both; commit.

## Task 5: Resize

- [ ] CSS: `.ws-agent[data-mode="docked"] { position: relative; }`; handle 8px wide at `left: -4px`; double-click resets to `DEFAULT_AGENT_WIDTH` (440); `readAgentWidth` minimum 320.
- [ ] Vitest: double-click resets width; browser check that the handle sits on the panel edge and dragging changes the width. Commit.

## Task 6: Transcript

- [ ] Usage: summary line shares a slim muted row with the audit link; table opens as an overlay, not in flow.
- [ ] Plan: `<details>` collapsed by default; summary = "Plan v2 · draft · 3 steps" + Approve button when approval is pending; expanded steps one line each (status dot, title), details in `title`.
- [ ] Error: callout card, `flex-shrink: 0`; same for plan and usage rows.
- [ ] Update `AgentPlanPanel`/`AgentUsagePanel`/`AgentPanel` tests. Commit.

## Task 7: Verify

- [ ] `npm test` (vitest, bounded workers), `npm run typecheck`, backend tests touched.
- [ ] Browser at 1512×945 (14-inch) and 1024×700, light and dark: resize, menus, plan, error; screenshots for the report.
