# V2/V10 CC Switch-style LLM Settings and Workbench Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace the read-only LLM badge and launcher-only Home with a CC Switch-inspired multi-provider manager, real model/context configuration, and a Workbench-integrated Home view while preserving existing environment configuration and deep links.

**Architecture:** Add a backend provider-store layer that atomically persists provider metadata plus an internal API key to a user-local JSON file. Resolve the active provider per request, keep the OpenAI-compatible Chat Completions adapter, and add model refresh/probe endpoints. On the frontend, build one reusable provider manager/editor and mount it from both Workbench topbar and Workbench Home; add Home to the existing URL-backed view state and reuse recent-project/create-project primitives.

**Tech Stack:** FastAPI, Pydantic, Python dataclasses, httpx, pytest, React 18, TypeScript, React Router, Vitest, Testing Library, existing Workbench CSS tokens.

**Working directory:** /Users/jiayuanren/项目规划/.worktrees/workbench-v1.6.12

**Spec:** docs/superpowers/specs/2026-07-12-v2-v10-ccswitch-settings-home-design.md

---

## Task 1: Secure local provider store

**Files:**
- Create: backend/workbench/llm/provider_store.py
- Test: tests/test_llm_provider_store.py

- [ ] **Step 1: Write failing store tests**

~~~python
def test_store_round_trips_active_provider_and_keeps_key_internal(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "llm-providers.json"))
    provider = ProviderRecord(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        api_key="secret-key",
        timeout_s=60.0,
        models=[ModelRecord("deepseek-chat", "deepseek-chat", None, False)],
    )
    save_provider_store(ProviderStore(active_provider_id="deepseek", providers=[provider]))
    loaded = load_provider_store()
    assert loaded.active_provider_id == "deepseek"
    assert loaded.providers[0].api_key == "secret-key"
    assert provider_public_dict(loaded.providers[0])["key_present"] is True
    assert "api_key" not in provider_public_dict(loaded.providers[0])


def test_store_writes_private_file_and_handles_corrupt_file(tmp_path, monkeypatch):
    target = tmp_path / "llm-providers.json"
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(target))
    save_provider_store(ProviderStore(active_provider_id=None, providers=[]))
    assert target.exists()
    assert target.stat().st_mode & 0o077 == 0
    target.write_text("{not json", encoding="utf-8")
    assert load_provider_store().providers == []
~~~

- [ ] **Step 2: Confirm RED**

~~~bash
.venv/bin/python -m pytest tests/test_llm_provider_store.py -q
~~~

Expected: collection fails because the store module and types do not exist.

- [ ] **Step 3: Implement and verify**

Create frozen dataclasses ModelRecord, ProviderRecord, and ProviderStore plus config_path, load_provider_store, save_provider_store, environment_provider_from_env, and provider_public_dict. Use WORKBENCH_LLM_CONFIG_PATH for tests and ~/.config/econometrics-workbench/llm-providers.json by default. Treat missing or invalid JSON as an empty store. Write to a sibling temporary file, set mode 600, then atomically replace the target. Never include api_key in provider_public_dict.

~~~bash
.venv/bin/python -m pytest tests/test_llm_provider_store.py -q
git add backend/workbench/llm/provider_store.py tests/test_llm_provider_store.py
git commit -m "feat(v1.6.12): add secure local LLM provider store"
~~~

## Task 2: Active-provider resolution and chat compatibility

**Files:**
- Modify: backend/workbench/llm/config.py
- Modify: backend/workbench/llm/client.py
- Test: tests/test_llm_chat.py

- [ ] **Step 1: Write failing tests**

Add tests proving a local active provider overrides environment variables and missing local storage preserves the existing environment fallback. Confirm the existing chat request posts to /chat/completions with model, messages, and stream false.

~~~bash
.venv/bin/python -m pytest tests/test_llm_chat.py -q
~~~

Expected: the local-provider test fails because config.py only reads environment variables.

- [ ] **Step 2: Implement resolution and verify**

Extend LLMConfig with provider_id, provider_name, source, context_window_tokens, and supports_1m. Load the active local record on every request, fall back to environment_provider_from_env, then return an empty config. Keep is_configured strict and do not add Anthropic-specific headers or branches.

~~~bash
.venv/bin/python -m pytest tests/test_llm_chat.py -q
git add backend/workbench/llm/config.py backend/workbench/llm/client.py tests/test_llm_chat.py
git commit -m "feat(v1.6.12): resolve active LLM provider per request"
~~~

## Task 3: Provider CRUD, activation, model refresh, and probe

**Files:**
- Modify: backend/workbench/http/llm_routes.py
- Modify: backend/workbench/llm/client.py
- Create: tests/test_llm_providers.py

- [ ] **Step 1: Write failing API tests**

Use TestClient and tmp_path. Test sanitized create/list/update, activation, deletion, model refresh, and probe. The model refresh test must monkeypatch the client factory with httpx.MockTransport, assert GET /models, and never call a real provider.

~~~bash
.venv/bin/python -m pytest tests/test_llm_providers.py -q
~~~

Expected: 404 because provider routes do not exist.

- [ ] **Step 2: Implement request models and routes**

Add ProviderModelRequest and ProviderUpsertRequest. Validate id, name, absolute HTTP(S) URL, timeout, and model. On update, a blank API Key preserves the stored secret; clear_api_key removes it. Return provider_public_dict only.

Implement GET /llm/providers, POST /llm/providers, PUT /llm/providers/{provider_id}, POST /llm/providers/{provider_id}/activate, DELETE /llm/providers/{provider_id}, POST /llm/providers/{provider_id}/models/refresh, and POST /llm/providers/{provider_id}/probe. Expand GET /llm/config with provider id/name/source/context metadata without removing current fields.

- [ ] **Step 3: Verify and commit**

Add fetch_models(config) in client.py. It performs GET {base_url}/models with the Bearer key and timeout, returns only id/owned_by, and converts non-2xx or malformed responses to sanitized LLMUpstreamError. Probe may call fetch_models but never chat_completion.

~~~bash
.venv/bin/python -m pytest tests/test_llm_providers.py tests/test_llm_chat.py -q
git add backend/workbench/http/llm_routes.py backend/workbench/llm/client.py tests/test_llm_providers.py
git commit -m "feat(v1.6.12): add LLM provider management APIs"
~~~

## Task 4: Typed frontend LLM API client and presets

**Files:**
- Create: frontend/src/llm/llmTypes.ts
- Create: frontend/src/llm/llmApi.ts
- Create: frontend/src/llm/providerPresets.ts
- Modify: frontend/src/lineage/detail/sections/askAiClient.ts
- Test: frontend/src/llm/llmApi.test.ts

- [ ] **Step 1: Write failing wrapper test**

Mock fetch and assert createLlmProvider sends POST /llm/providers and the returned public type has key_present but no API key field.

~~~bash
(cd frontend && npx vitest run src/llm/llmApi.test.ts)
~~~

Expected: import fails because llmApi.ts does not exist.

- [ ] **Step 2: Implement and verify**

Define sanitized LlmModel, LlmProvider, and LlmProvidersResponse types. Implement fetch/create/update/activate/delete/refresh/probe functions using apiUrl and readResponse. Move LlmConfigInfo and fetchLlmConfig out of askAiClient.ts and re-export them temporarily. Add presets for DeepSeek, OpenAI, GLM, Moonshot, Qwen, and Custom; presets provide name and Base URL only.

~~~bash
(cd frontend && npx vitest run src/llm/llmApi.test.ts)
(cd frontend && npx tsc --noEmit)
git add frontend/src/llm frontend/src/lineage/detail/sections/askAiClient.ts
git commit -m "feat(v1.6.12): add typed LLM provider client"
~~~

## Task 5: CC Switch-style provider manager and editor

**Files:**
- Create: frontend/src/llm/LlmProviderManager.tsx
- Create: frontend/src/llm/LlmProviderManager.test.tsx
- Create: frontend/src/llm/LlmProviderEditor.tsx
- Create: frontend/src/llm/LlmProviderEditor.test.tsx

- [ ] **Step 1: Write failing manager tests**

Cover active marking, activation, opening the editor, and blank-key preservation. Use stable ids llm-provider-list, llm-provider-active-<id>, llm-provider-activate-<id>, and llm-provider-edit-<id>.

~~~bash
(cd frontend && npx vitest run src/llm/LlmProviderManager.test.tsx src/llm/LlmProviderEditor.test.tsx)
~~~

Expected: imports fail because the manager/editor components do not exist.

- [ ] **Step 2: Implement manager shell**

Render a full-height role dialog with a back button, title, provider list, add button, and error/status region. Rows display key status, active state, model, Base URL, probe state, and actions. Activation refreshes from the server; deletion requires window.confirm.

- [ ] **Step 3: Implement editor form**

Render the CC Switch structure: two-column basic fields, masked API Key with show/hide and explicit clear, Base URL with connectivity check, collapsed advanced section, model refresh, mapping rows with context window and 1M, default model, sanitized config preview, disabled saving state, inline errors, and success state.

When editing, blank api_key submits undefined; only explicit clear sends clear_api_key: true. Add tests for URL validation, required fields, preset selection, Key reveal, blank-key preservation, explicit clear, model refresh, context window, 1M, and sanitized preview.

~~~bash
(cd frontend && npx vitest run src/llm/LlmProviderManager.test.tsx src/llm/LlmProviderEditor.test.tsx)
git add frontend/src/llm/LlmProviderManager.tsx frontend/src/llm/LlmProviderManager.test.tsx frontend/src/llm/LlmProviderEditor.tsx frontend/src/llm/LlmProviderEditor.test.tsx
git commit -m "feat(v1.6.12): add CC Switch-style LLM provider editor"
~~~

## Task 6: Ask AI context summary

**Files:**
- Create: frontend/src/llm/LlmContextSummary.tsx
- Create: frontend/src/llm/LlmContextSummary.test.tsx
- Modify: frontend/src/lineage/detail/sections/AskAISection.tsx
- Modify: frontend/src/lineage/detail/sections/AskAISection.test.tsx

- [ ] **Step 1: Write failing summary test**

Render a packet fixture with context_window_tokens 1,000,000 and supports_1m true. Assert that the summary shows 1M, ask-ai-context/v1, packet size, preview budget, artifact count, and truncation.

~~~bash
(cd frontend && npx vitest run src/llm/LlmContextSummary.test.tsx)
~~~

Expected: import fails because the component does not exist.

- [ ] **Step 2: Implement diagnostics**

Compute JSON.stringify(packet) size with TextEncoder, count artifacts, inspect context_visibility_notice.max_total_preview_chars, and collect artifact redactions. Render a collapsed details section with data-testid llm-context-summary. Show model capacity and actual packet size separately. Keep the existing 8,000-character safety budget unchanged.

- [ ] **Step 3: Mount and verify**

Mount the summary next to the existing Context preview, preserve Ask AI history and artifact Explain, then run:

~~~bash
(cd frontend && npx vitest run src/llm/LlmContextSummary.test.tsx src/lineage/detail/sections/AskAISection.test.tsx)
git add frontend/src/llm/LlmContextSummary.tsx frontend/src/llm/LlmContextSummary.test.tsx frontend/src/lineage/detail/sections/AskAISection.tsx frontend/src/lineage/detail/sections/AskAISection.test.tsx frontend/src/lineage/detail/sections/askAiClient.ts
git commit -m "feat(v1.6.12): expose Ask AI context diagnostics"
~~~

## Task 7: Workbench Home URL view

**Files:**
- Modify: frontend/src/workbench/state/urlSchema.ts
- Modify: frontend/src/workbench/state/urlSchema.test.ts
- Modify: frontend/src/workbench/WorkbenchMain.tsx
- Modify: frontend/src/workbench/WorkbenchTopbar.tsx
- Modify: frontend/src/workbench/WorkbenchTopbar.test.tsx
- Create: frontend/src/workbench/views/WorkbenchHomeView.tsx
- Create: frontend/src/workbench/views/WorkbenchHomeView.test.tsx

- [x] **Step 1: Write failing URL/Home tests**

Add a URL round-trip test for view=home and a Home view test that renders recent projects, new project, LLM status, and settings without mounting the graph canvas.

~~~bash
(cd frontend && npx vitest run src/workbench/state/urlSchema.test.ts src/workbench/views/WorkbenchHomeView.test.tsx)
~~~

Expected: home is rejected by the URL parser and the Home view import fails.

- [x] **Step 2: Implement Home view**

Add home to ViewMode and VIEW_MODES while keeping graph as default. Create WorkbenchHomeView with recent projects, current project continuation, CreateProjectModal, LLM status, and 管理供应商. Use test ids workbench-home, workbench-home-llm-card, and workbench-home-settings. It must render zero-recents and LLM-error states without infinite loading.

- [x] **Step 3: Add Home to topbar and WorkbenchMain**

Make VIEW_TABS equal Home, Graph, Table, Report. Thread onOpenSettings from WorkbenchShell through WorkbenchMain and WorkbenchTopbar. Add a home branch in WorkbenchMain that renders WorkbenchHomeView with projectRoot and onOpenSettings.

~~~bash
(cd frontend && npx vitest run src/workbench/state/urlSchema.test.ts src/workbench/views/WorkbenchHomeView.test.tsx src/workbench/WorkbenchTopbar.test.tsx src/workbench/WorkbenchTopbar.tabs.test.ts)
git add frontend/src/workbench/state/urlSchema.ts frontend/src/workbench/state/urlSchema.test.ts frontend/src/workbench/WorkbenchMain.tsx frontend/src/workbench/WorkbenchTopbar.tsx frontend/src/workbench/WorkbenchTopbar.test.tsx frontend/src/workbench/WorkbenchTopbar.tabs.test.ts frontend/src/workbench/views/WorkbenchHomeView.tsx frontend/src/workbench/views/WorkbenchHomeView.test.tsx
git commit -m "feat(v1.6.12): add Workbench Home view"
~~~

## Task 8: Launcher routing and shared project actions

**Files:**
- Create: frontend/src/launcher/RecentProjectsPanel.tsx
- Create: frontend/src/launcher/RecentProjectsPanel.test.tsx
- Modify: frontend/src/launcher/LauncherRoute.tsx
- Modify: frontend/src/launcher/LauncherRoute.test.tsx
- Modify: frontend/src/App.tsx
- Modify: frontend/src/App.test.tsx
- Modify: frontend/src/workbench/WorkbenchRouteContainer.tsx
- Modify: frontend/src/workbench/WorkbenchRouteContainer.test.tsx

- [x] **Step 1: Write failing route tests**

Add tests proving bare / with a recent project enters workbench-home, the Home tab stays under /p/<slug>/graph, and /?home=1 aliases view=home.

~~~bash
(cd frontend && npx vitest run src/launcher/LauncherRoute.test.tsx src/App.test.tsx src/workbench/WorkbenchRouteContainer.test.tsx)
~~~

Expected: current Home navigation goes to the standalone Launcher and the new assertion fails.

- [x] **Step 2: Extract RecentProjectsPanel**

Move card/probe/stale/remove behavior from LauncherRoute into RecentProjectsPanel. Preserve the concurrent-probe guard, PROJECT_NOT_FOUND handling, localStorage ordering, and fetchRuns probe. Keep LauncherRoute as a thin first-run wrapper around the shared panel and CreateProjectModal.

- [x] **Step 3: Change AppShell and aliases**

When the Workbench route is active and projectRoot is set, AppShell Home navigates to /p/<slug>/graph?view=home; otherwise it navigates to /. Map /?home=1 to the latest project’s view=home. Keep no-recents / usable and leave /submit untouched.

- [x] **Step 4: Share manager state and hide graph chrome**

Mount one LlmProviderManager owner in WorkbenchShell, pass onOpenSettings to WorkbenchTopbar and WorkbenchMain, and render the manager above the workbench content when open. When state.view is home, keep the topbar but hide RunHistoryRail, BottomPanel, DetailDrawer, graph keyboard behavior, and graph-only context-menu affordances.

~~~bash
(cd frontend && npx vitest run src/launcher/RecentProjectsPanel.test.tsx src/launcher/LauncherRoute.test.tsx src/App.test.tsx src/workbench/WorkbenchRouteContainer.test.tsx)
git add frontend/src/launcher/RecentProjectsPanel.tsx frontend/src/launcher/RecentProjectsPanel.test.tsx frontend/src/launcher/LauncherRoute.tsx frontend/src/launcher/LauncherRoute.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/workbench/WorkbenchRouteContainer.tsx frontend/src/workbench/WorkbenchRouteContainer.test.tsx
git commit -m "feat(v1.6.12): integrate Home into Workbench shell"
~~~

## Task 9: Correct documentation state

**Files:**
- Modify: docs/superpowers/followups/v1.6.9-followups.md
- Modify: docs/v1.6.12-release-notes.md
- Modify: docs/superpowers/plans/2026-07-12-v1.6.12-closeout-plan.md

- [x] **Step 1: Locate stale claims**

~~~bash
rg -n "V2|V10|V11|llm/config|ProjectSwitcher" docs scripts tests
~~~

- [x] **Step 2: Update docs**

Replace the old V2 claim of read-only config plus badge with provider manager, multi-provider persistence, model refresh, 1M metadata, and context summary. Replace the old V10 claim of launcher redirect plus ProjectSwitcher with Workbench Home, in-shell navigation, shared recent projects, and compatibility aliases. Keep V11 marked v1.7. Add commit references only after implementation commits exist.

- [x] **Step 3: Verify and commit docs**

~~~bash
rg -n -C 2 "V2|V10|V11|llm/config|Workbench Home|1M" docs/superpowers/followups/v1.6.9-followups.md docs/v1.6.12-release-notes.md docs/superpowers/plans/2026-07-12-v1.6.12-closeout-plan.md
git diff --check
git add docs/superpowers/followups/v1.6.9-followups.md docs/v1.6.12-release-notes.md docs/superpowers/plans/2026-07-12-v1.6.12-closeout-plan.md
git commit -m "docs(v1.6.12): record completed V2 and V10 behavior"
~~~

## Task 10: Full verification and visible browser acceptance

**Files:**
- No source changes expected unless verification finds a defect.

- [x] **Step 1: Run focused suites**

~~~bash
.venv/bin/python -m pytest tests/test_llm_provider_store.py tests/test_llm_providers.py tests/test_llm_chat.py -q
(cd frontend && npx vitest run src/llm src/launcher/RecentProjectsPanel.test.tsx src/launcher/LauncherRoute.test.tsx src/App.test.tsx src/workbench/state/urlSchema.test.ts src/workbench/WorkbenchTopbar.test.tsx src/workbench/WorkbenchRouteContainer.test.tsx)
(cd frontend && npx tsc --noEmit)
~~~

Expected: focused backend/frontend tests pass and TypeScript reports zero errors.

- [x] **Step 2: Run the repository gate**

~~~bash
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 ./scripts/gate.sh
~~~

Expected: backend, golden/invariants, frontend, and typecheck gates pass.

- [x] **Step 3: Perform visible browser acceptance**

Verify in the local browser:
1. Workbench Home renders recent projects, new project, and LLM status in one shell.
2. Home and topbar open the same CC Switch-style manager.
3. Adding a provider and reopening shows only 已配置, never the Key.
4. Model refresh succeeds against a controlled endpoint or shows the explicit unsupported-endpoint error.
5. Context window and 1M save and display correctly.
6. Ask AI shows provider, model capacity, packet size, redactions, and safe preview policy.
7. Home → Graph → Table → Report preserves view state and URL.
8. /submit remains reachable.

- [x] **Step 4: Final review**

~~~bash
git diff --check
git status --short --branch
git log --oneline --decorate -12
~~~

Expected: only intentional V2/V10 commits are on workbench-v1.6.12, no main-checkout files changed, and no API key or temporary provider file is tracked.

- [x] **Step 5: Request pre-merge review**

> Review note: the implementation was reviewed locally against the spec, focused tests, full gate, and visible Home/settings states. The delegated reviewer pool was saturated by an earlier stuck worker, so no separate reviewer response was available in this session. Push, PR, merge, and tag remain approval-gated release actions.

Resolve every Critical/Important review finding before calling V2/V10 complete. Push, PR, merge, and tag remain approval-gated release actions.

## Plan self-review

- **Spec coverage:** Tasks 1–3 cover persistence, env compatibility, CRUD, model refresh, probe, and redaction. Tasks 4–6 cover the CC Switch-style manager, 1M metadata, and Ask AI context visibility. Tasks 7–8 cover Home, URL state, launcher aliases, shared recent projects, and shell chrome. Tasks 9–10 cover docs, gates, browser QA, and review.
- **Completeness scan:** No unresolved markers or unspecified test commands remain.
- **Type consistency:** Backend uses ProviderRecord, ModelRecord, and ProviderStore; frontend uses LlmProvider, LlmModel, and LlmProvidersResponse. ViewMode adds only home while preserving graph, table, pipeline, and report.
- **Scope check:** Anthropic native protocol, Claude role mapping, Tool Search, V11 data editing, and full-data drill-down are explicitly excluded.
