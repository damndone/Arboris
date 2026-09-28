# Findings

This file records evidence from the current smoke-test session. External
content and unverified assumptions must not be treated as repository facts.

## Repository launch evidence

- `README.md` documents backend `uvicorn workbench.api:app --reload` and
  frontend `npm run dev`.
- `docs/dev-browser-smoke.md` documents backend port `8000`, frontend port
  `5173`, and the CLI seed path using `tests/fixtures/forest_min.csv`.
- The repository contains no file or fixture whose name explicitly identifies
  `TEM`; the closest confirmed fake-data surface is the documented forest
  fixture plus the committed econometrics fixtures under `tests/fixtures/`.
- Current worktree already contains intentional v1.7 changes and the newly
  created planning files; no code or pre-existing adversarial review file has
  been changed by this smoke pass so far.

## Initial UI smoke evidence

- `http://127.0.0.1:5173/` renders the Workbench shell with theme controls and
  the `Home` / `Workbench` view tabs.
- The default route then shows `Could not load lineage` and `Request failed
  with status 500`, with a visible `Try again` action. This is reproducible
  before a project/run context is supplied; it is not yet evidence that a
  seeded run is broken.

## Seeded fake-data evidence

- Created an isolated temporary project at
  `/tmp/wb-v17-parent.PabI7h/wb-smoke` and ran the documented cross-section
  fixture successfully.
- Run id: `20260714_150851_911114_196243ec`.
- The run produced `run_manifest.json`, `graph.json`, `node_index.json`,
  `diagnostic_summary.json`, `artifacts_index.json`, and `workflow_log.jsonl`.
- The CLI emitted a Matplotlib/font-cache warning because the user cache and
  system font cache are not writable; execution still completed. This is an
  environment reproducibility risk worth carrying into the review.

## API smoke evidence

- With the seeded project root and run id, `GET /graph`, `GET /runs`, run
  detail, run graph, and artifacts all returned HTTP 200.
- Run detail exposes status, lineage, model results, normalized errors, and a
  diagnostic summary preview; run graph exposes nodes, edges, branches, and
  stats. This confirms the backend data contract is reachable from the live
  service, not only from unit tests.

## Seeded UI route evidence

- Navigating the frontend to the CLI-style lineage URL rewrites to the v1.6.8
  slug route `/p/<encoded-project-root>/graph?run=<run_id>`.
- The visible page still reports `Request failed with status 500`, despite
  the equivalent backend endpoints returning 200 directly.
- Browser console showed only React Router future-flag warnings, not a
  ReactFlow or application exception. The mismatch is now a high-value
  antifragile finding: the UI route/proxy/project-root translation is not yet
  proven against the live seeded run.

## Root cause of the live UI 500

- `frontend/vite.config.ts` defaults `VITE_API_PROXY_TARGET` to
  `http://127.0.0.1:8010`.
- The repository smoke document starts the backend on `8000`, and this run
  was started on `8000`.
- This explains the split evidence: direct backend API probes returned 200,
  while the browser's `/api/*` calls failed through the Vite proxy.
- This pass will first re-run with `VITE_API_PROXY_TARGET=http://127.0.0.1:8000`
  as an environment-only correction; code changes are not being made during
  the review.

## Model operation smoke evidence

- After correcting the proxy, the seeded graph rendered in the browser with
  raw input, cleaned data, model, report, variables group, review badge, and
  bottom logs panel.
- Opening the model node rendered the operation panel, review decisions,
  lineage path, equation, Ask AI scope, and compare section.
- Changing covariance from `robust` to `clustered` enabled the preview action;
  the preview displayed `covariance: robust -> clustered`.
- Confirming the rerun failed closed with the visible message `Parent run has
  no run_inputs.json (not rerunnable)`. No child run was created. This is a
  real limitation of the CLI-seeded path: the run artifacts listed earlier do
  not include `run_inputs.json`, so the UI correctly refuses to invent rerun
  inputs.

## DeepSeek Ask AI smoke evidence

- The live node dialog showed DeepSeek configured as `https://api.deepseek.com`
  with a present key and model `deepseek-v4-flash`.
- A fake-data question was submitted from the UI. The backend logged
  `POST /llm/chat` HTTP 200, so the API call reached the provider path.
- After more than ten seconds the UI still showed a disabled Ask AI button,
  no answer, and `No AI activity yet`. The browser console had no application
  error. This is an unresolved UI persistence/rendering issue or a response
  contract mismatch, not evidence that the provider returned a usable answer.
- The rendered context preview element exists but is collapsed, so this pass
  has not treated hidden DOM text as evidence about the packet contents.
- A separate minimal synthetic `POST /llm/chat` returned HTTP 200 with a
  non-empty Chinese answer, model `deepseek-v4-flash`, and the supplied
  context fingerprint. The provider and backend response contract work
  independently; the unresolved failure is specifically in the browser
  Ask AI state transition/activity persistence.

## Report-generation smoke evidence

- The Report view exposed a 22-fact citable packet and the Generate report
  action.
- After submitting the synthetic-data report request, the backend again logged
  HTTP 200 for `/llm/chat`, but the UI still showed `No reports yet` and the AI
  activity panel remained empty after 12 seconds.
- This repeats the Ask AI symptom across both AI surfaces and raises the
  finding from a node-only issue to a shared frontend AI activity/result
  lifecycle problem.

## API-submitted run evidence

- A second isolated run created through `POST /runs` completed successfully:
  `20260714_151553_237739_8b2a006f`.
- Unlike the CLI-created run, this API path persisted `run_inputs.json` with
  the complete form, upload SHA-256, and DAG hash. This confirms the backend
  has the provenance substrate needed for rerun when the actual UI/API submit
  path is used.
- The API run detail returned `completed` with `y=wage` and
  `x=[education, experience, region]`.

## API-run rerun smoke evidence

- The API-submitted run rendered a two-version head selector and full workflow
  logs in the browser.
- Its model operation preview accepted `covariance: robust -> clustered`.
- Confirming the rerun sent `POST /runs/20260714_151553_237739_8b2a006f/rerun`
  but the backend returned HTTP 409 Conflict. The UI did not surface a clear
  error or child-run transition in the observed state. The exact conflict
  payload and idempotency semantics still need inspection before calling the
  rerun operation healthy.

## Fail-closed and genesis smoke evidence

- A direct legacy rerun on the same completed API run succeeded and created
  child `20260714_151750_711372_767d3927`; the earlier UI 409 was therefore
  not a general rerun-engine failure.
- Empty project `GET /graph` returned HTTP 200 with zero nodes, edges, and
  families, and the visible UI rendered `This project has no data yet` plus
  `＋ New analysis`.
- Clicking `＋ New analysis` opened the dataset intake panel without error.
- Missing project root returned HTTP 404 with `PROJECT_NOT_FOUND`; an invalid
  graph node rerun returned HTTP 422. These boundaries fail closed with
  structured responses.

## Draft save / validate / execute smoke evidence

- The fork action created `draft_d5a9872332884e71b73b91c7e719904e` and the
  browser opened the draft editor. Changing covariance in the editor showed a
  local changed-field row, but a follow-up `GET /pipeline-drafts/{draft_id}`
  proved that the UI had not persisted the change: the draft was still
  `status=draft`, with `covariance=clustered` and the original draft hash.
- The backend draft contract works independently. A direct `PATCH` changed
  covariance to `unadjusted` and returned a new draft hash; direct
  `POST .../validate` returned `ok=true`, `status=valid`, `executable=true`,
  and a validated hash for `rerun_child`.
- The complete backend draft loop also works: direct `POST .../execute`
  created child `20260714_152744_846452_6e1795fe`, which reached
  `status=completed`. Its `run_inputs.json` records `covariance=unadjusted`.
- Therefore the current finding is specifically a browser draft-editor
  integration/state-transition gap (Save/Validate does not visibly dispatch or
  surface the backend lifecycle), not a missing backend draft capability.

## Follow-up verification after Agent workbench implementation

- The prior AI smoke gap is no longer present in the current checkout. With the
  restarted backend and frontend, Ask AI rendered a substantive DeepSeek answer
  in the node dialog and the AI activity panel showed the corresponding typed
  record. Report generation rendered a report body and added a report activity
  record. The earlier observation was made before the current browser state was
  allowed to complete the provider request; it should not be treated as current
  evidence of a failing result path.
- The new Agent surface is visible in the Graph route and bottom panel. A
  synthetic fake-data prompt returned `SMOKE_OK`; the same transcript was
  present after a browser reload. The backend session route and browser state
  therefore agree on durable replay for the tested session.
- The Draft Editor now carries per-draft request errors into the visible editor
  (`role=alert`) while preserving fail-closed lifecycle state. The backend direct
  draft PATCH/validate/execute contract remains independently verified above;
  a fresh browser Save/Validate pass is still deferred until a draft node is
  reintroduced into the visible forest fixture.

## Agent frontend brainstorming evidence

- The user selected an integrated Agent surface: a new `Agent` bottom-panel
  tab plus a Codex-like composer directly below the lineage graph.
- The requested composer constraints are: graph-width alignment,
  semi-transparent surface, four rounded corners, light shadow, context-length
  ring, and model selection sourced from the existing LLM settings.
- The visual companion mockup at `http://localhost:54110/` represents this
  layout without changing Workbench code. The intended separation is quick
  prompt/task entry in the composer and full conversation, scope, permission,
  proposal confirmation, and activity in the Agent bottom panel.

## Agent HTTP TDD baseline

- Added `tests/test_agent_routes.py` for durable session creation, one turn,
  replayable events, context-size rejection, unknown-session errors, and
  provider-secret redaction.
- The expected RED run is confirmed: all 3 tests fail because
  `workbench.http.agent_routes` and `/agent/sessions` do not exist yet.

## Claude Code handoff source map

- No current v1.7 Claude handoff file exists in the worktree. Historical
  handoffs under `docs/superpowers/archive/` are format/background references,
  not current implementation truth.
- The handoff must anchor on the live v1.7 spec and plan, the live rolling
  followups file, the unified Graph roadmap, and architecture debt. The
  repository-local `task_plan.md`, `progress.md`, and `findings.md` are also
  current evidence for this unfinished worktree and must be read before code.
- The current worktree contains intentional uncommitted changes and must be
  continued in place; a handoff must list this boundary explicitly so Claude
  Code does not create a new worktree or reset the checkout.

## Canonical backlog and design evidence

- `docs/superpowers/followups/BACKLOG.md` (renamed from v1.6.9-followups.md) is still the live rolling
  backlog despite its filename. It explicitly says completed items are deleted
  rather than checked off. Remaining relevant items include V7 large-context
  Ask AI drill-down, V11 data-layer graph editing, N2/W1/W2, S1-S6, U1/U2,
  architecture pointers D2/D6/D4/D5, and future M2-M6 tracks.
- `docs/superpowers/roadmap/2026-07-01-unified-graph-workbench-roadmap.md`
  remains the product north star: one lineage graph for view/edit/rerun/
  compare/AI/report. v1.7 Agent Harness is the later orchestration layer, not
  permission to bypass graph truth.
- `docs/superpowers/roadmap/architecture-debt.md` marks D1 and D3 resolved;
  D2 GLM-family registry, D6 OpenAPI type generation, D4 CSS migration, and
  D5 periodic lineage-complexity review remain. New endpoints must use router +
  service layers rather than growing a facade.
- The v1.7 Agent Harness design and proposal plan are the governing architecture
  and the proposal plan is complete. The frontend design/plan is also
  implemented, but its checkbox plan is a historical execution checklist and
  should not be mistaken for a new RED implementation state.
- The live HTTP turn route currently constructs a plain `AgentCore` with the
  provider adapter and bounded budget; it does not yet attach the
  `WorkbenchOrchestrator`/provider-owned context tools or expose proposal
  confirmation endpoints. The backend orchestration primitives exist and are
  covered by tests, but the current Agent UI is therefore an advisory,
  request/response surface rather than the complete proposal-to-rerun UI.
- `frontend/src/workbench/agent/agentApi.ts` currently covers create/get/turn
  calls; the browser surface does not yet consume the durable event cursor for
  live streaming. Browser startup is documented by `docs/dev-browser-smoke.md`:
  `.venv/bin/uvicorn ... --port 8000` and `cd frontend && npm run dev`.

## 2026-07-14 Claude Code smoke + antifragile review (examples/datasets, isolated project)

Isolated project under the session scratchpad; backend 8015 / frontend 5177 via
dedicated launch.json entries. Four families verified over live HTTP + browser:
ols (robust), panel_ols, iv_2sls, cs_did (ATT≈2.02, collinear covariate dropped
with visible INFO). Browser: forest render, drawer, operation preview,
rerun robust→clustered created child `20260714_174611_355505_f7343d0c`, version
selector + rail followed the child; Agent composer/panel shared one transcript,
`SMOKE_OK_V17` round-trip, transcript survived reload; events replay seq 1–9
ordered; unknown session/project 404, >4,000-char prompt 422; no secret material
in `agent-sessions/`/`agent-events` (the only grep hit is the substring
"sk-" inside "ask-ai-context/v1"); Ask AI rendered a substantive answer and AI
activity recorded it; quick gate passed (backend focused 265, FE 125 files/1065,
gate contract 8, tsc clean). No unintended run/graph mutation; protected
adversarial files untouched.

New findings (not fixed in this pass):

1. **OLS covariance is a silent no-op end-to-end.** `capabilities.py` exposes
   covariance (robust/clustered/unadjusted) in the model editable schema, the
   rerun UI previews `robust -> clustered`, the child run persists
   `covariance=clustered` in `run_inputs.json` — but `_fit_ols`
   (`backend/workbench/engine/stages/estimation.py:246`) hardcodes
   `robust=True` and never reads `_covariance`; child std errors are
   byte-identical to the parent and no WARNING is emitted. Only `panel_ols`
   consumes `_covariance`. A decisions note ("OLS pipeline always applies HC1;
   not data-driven") exists in the packet, and Ask AI spotted the mismatch, but
   the operation path lets the user "change" a dead parameter. Pre-existing
   (not a v1.7 regression); violates explicit-only honesty; candidate followup.
2. **`Fork draft here` failure is console-only.** After the rerun, the pinned
   node's fork hit `POST /pipeline-drafts/from-node` → 409
   `SOURCE_CONTEXT_MISMATCH: context_stale: context_fingerprint`, and
   `onForkDraftHere` (`frontend/src/lineage/graph/NodeActionMenu.tsx:114`)
   only logs `fork draft failed` to console — zero visible UI feedback. Same
   bug class as the draft-lifecycle errors fixed this round; this entry point
   was missed. Fail-closed behavior itself is correct.
3. **`x` wire-format asymmetry and unrepresentable empty x.** `POST /runs`
   parses `x`/`focal_x` as comma-separated but `iv_endog`/`iv_instruments` as
   JSON arrays. Sending `x=["a","b"]` "works" only because
   `normalize_column_name` strips the brackets/quotes; sending `x=[]` produced
   a blocked run with misleading evidence `missing_columns: [""]`. An actually
   empty `x` is rejected by FastAPI as missing (empty multipart string →
   `Field required`), so a zero-covariate DID/CS run — supported by the engine
   and used in tests via `run_workflow(x=[])` — cannot be submitted over HTTP;
   the frontend's `x.join(",")` has the same gap.
4. **Spec/implementation divergence in Agent storage layout.** Sessions/events
   are written to `<project>/agent-sessions/` and `<project>/agent-events/`,
   while the v1.7 harness design §10.1 places them under `workbench/`.
   Reported per handoff rule 6 (stop and surface conflicts) — needs a decision
   (fix layout vs. amend spec) before chain/fork/operation stores land.
5. Minor, known-debt confirmations: drawer meta line still shows the raw
   machine string (U1); the estimated equation renders raw
   `C(Q('region'))[T.South]` terms; composer Enter did not submit in the
   automated browser (Send button worked; needs a manual recheck before filing).

## 2026-07-14 development round — resolutions and new evidence

- Findings 1–4 from the smoke section above are now FIXED in this worktree
  (OLS covariance honesty incl. new `ols_clustered` path + fail-closed
  OLS_CLUSTER_FIELD_MISSING; visible fork-draft alert; dual-format/optional
  `x` selector via `parse_column_selector`; agent storage under
  `workbench/`). Old project-root `agent-sessions/` data from before the move
  is orphaned by design (dev-only; sessions are recreated on demand).
- NEW live-provider finding (fixed): `OpenAICompatibleModelAdapter` posted the
  INTERNAL assistant tool_calls/tool-result shapes on the post-tool turn, so
  the first real DeepSeek tool roundtrip died with LLMUpstreamError. The
  deterministic suite never crossed this boundary because it uses fake
  adapters — live provider smoke remains a mandatory acceptance layer for
  every adapter-facing change. Fixed by `_to_openai_wire_messages` at the
  adapter boundary with a mocked-transport regression test.
- Observed model behavior worth keeping: DeepSeek guessed operation ids
  ("rerun"/"run"/"ols") until the tool schema enumerated
  `registry.operation_ids()`; after the enum it self-corrected and used
  `model.rerun`. Schema-level enums are an effective guardrail against
  tool-argument guessing.
- Read-only inspection slice verified live: 5 chained tool calls with
  canonical args, typed `⋮ tool ✓/✗` lines in the terminal panel,
  `blocked` (max_steps) and `failed` (upstream) states visible and durable,
  zero Workbench mutation (runs/graph untouched; chains/forks/
  operation-records/proposals stayed empty).
- At the time of this earlier handoff entry, the next slice was proposal card
  plus confirmation endpoints/UI. That slice is now covered by the continuation
  evidence below; event-cursor live streaming in `agentApi.ts`, Main/Chain
  projection, fork/operation-record/diff UI, V7, V11, and the remaining backlog
  items are still pending.

## 2026-07-14 Agent proposal continuation evidence

- The local `.venv` has an editable Workbench install pointing at the main
  checkout. Starting uvicorn without an explicit `PYTHONPATH` therefore served
  the wrong checkout and returned a false 404 for the new Agent routes. The
  valid smoke launch used
  `PYTHONPATH=/Users/jiayuanren/项目规划/.worktrees/workbench-v1.7/backend`
  with backend port `8017`, and Vite was pointed at that backend. Future browser
  smoke must preserve this worktree/runtime check.
- With a selected OLS node in isolated project
  `/tmp/wb-agent-proposal.43fkpx`, DeepSeek `deepseek-v4-flash` completed the
  scoped inspection tools, called `propose_operation`, and created a real
  pending `model.rerun` proposal changing `covariance: robust → unadjusted`.
  The Agent bottom panel rendered the typed proposal card with expected effects,
  risks, and a confirmation button.
- Clicking the visible confirmation button created an append-only Operation
  Record with `status=pending` and changed the proposal card to `confirmed`.
  The project still had five completed runs and no new child run, so this seam
  is confirmation-only; execution is intentionally still a separate pending
  follow-up.
- A live first attempt with the new structured proposal flow exposed two real
  contract issues: the model needed explicit nested target/precondition fields,
  and `operation_proposal` audit metadata was inserted between an assistant
  tool-call and its tool result. The first issue is now addressed by the
  provider-visible schema and chain protocol; the second is addressed in the
  OpenAI wire converter by deferring interleaved audit messages until the tool
  result block ends. A subsequent DeepSeek run completed `idle` with the
  proposal card visible, confirming the provider turn no longer fails.
- A no-selection DeepSeek prompt remains fail-closed: inspection arguments had
  no valid node target, the session became blocked, and no proposal or mutation
  was created. The current frontend sessionStorage key is project+run scoped,
  not selection scoped, so changing selection after a fallback session exists
  can reuse stale project context. This is a known next-slice UX/safety gap, not
  silently treated as solved by the proposal confirmation work.

## 2026-07-14 Scope and event-cursor resolution evidence

- The selection-scope reuse gap is fixed in the frontend. Agent session
  persistence is now keyed by the bounded context fingerprint rather than only
  project and run. On scope change the provider resets visible session state;
  stale in-flight responses cannot write into the new scope. The regression
  test covers old-node hydration followed by a new-node submission and checks
  that the new context fingerprint is sent.
- The frontend now consumes the existing durable event endpoint with an
  `after_seq` cursor. It replays from zero when hydrating a session, polls
  during a live turn, and renders the latest cursor in the Agent terminal.
  Live DeepSeek evidence: a read-only node inspection advanced `events #0` →
  `events #17` while thinking → `events #22` on idle; reload replayed `#22`
  and the transcript. No proposal or run mutation was produced.
- The remaining boundary is deliberate: confirmation still creates a pending
  Operation Record only. Execution must be added as a separate typed,
  precondition-revalidated UI/API slice.

## 2026-07-14 Agent UI correction evidence

- The bottom Agent page’s “pure terminal” requirement still needs an input
  affordance to be useful. The corrected design keeps one terminal command
  line inside the panel and retains the Graph composer as the only place for
  model/context controls. Browser DOM inspection found exactly one bottom
  terminal textbox and no duplicated bottom model selector or context ring.
- The context ring defect was a CSS interaction, not a missing visual token:
  the global button minimum height made the nominal 30px circle render at
  30×36px. Explicit width/height/min/max constraints now survive the global
  rule; browser measurement is 30×30px.
- LLM Settings was not merely a visual issue. The provider manager listed
  model mappings but did not provide an active-model operation or an explicit
  Configure affordance. The manager now updates the provider model through the
  existing persistence API and opens the existing editor. A browser smoke
  switched the live environment-backed provider to `deepseek-v4-pro`, then
  back to `deepseek-v4-flash`, and opened Configure successfully.
- A full-gate test caught one stale test expectation that modeled Settings as
  opening the editor directly. The product route is intentionally manager
  first, so the test now asserts the manager lifecycle rather than weakening
  the manager/editor implementation.
- The unisolated gate failure after browser verification is a reproducibility
  concern worth retaining: real settings persistence can contaminate tests
  that assume no user-level provider configuration. The deterministic gate
  invocation for this work used a temporary `WORKBENCH_LLM_CONFIG_PATH`; no
  production fallback was added to hide the contamination.

## 2026-07-14 Agent UI redesign intake evidence

- Browser inspection of the live v1.7 worktree confirms the current shell still
  renders `Local Econometrics Workbench` as the top-left heading, with the
  Light/System/Dark control in a separate header row above the Home/Workbench
  navigation. This creates avoidable vertical dead space.
- The Graph route currently renders one `Ask Agent` composer below the graph,
  while the bottom Agent panel renders a second `Ask Agent` composer. The
  panel also repeats the context button and model selector. This duplicates
  the input contract and leaves the terminal transcript, proposal/confirmation
  content, and input controls competing for the same limited panel height.
- The context control is currently a button with an inline conic-gradient
  background and a token label. It does not open a usable background-context
  popover, and its rendered shape is not guaranteed to remain circular.
- The selected provider payload exposed `deepseek-v4-flash` in the current
  browser session, while the requested DeepSeek Flash/Pro choice was not
  exposed as a usable model switch in the Agent surface. This requires a
  verified provider-model contract, not only a visual select change.
- Assistant content is projected directly from the stored message text in the
  Agent terminal. Markdown markers such as headings and emphasis therefore
  appear as raw `##`/`**` text instead of readable terminal content.
- No source implementation was changed for this redesign intake; these are
  observations from the running browser and current code paths, recorded
  before design approval.

## 2026-07-14 Agent UI usability implementation evidence

- RED coverage was added before the UI correction. The old implementation
  failed because model records were rendered as React children, the bottom
  Agent panel still mounted a second composer, and no context dialog or
  Markdown projection existed. The corrected focused frontend suite now
  passes 75 tests across Agent, LLM Settings, and App shell coverage.
- The bottom Agent page now contains only its terminal header, durable log, and
  a bounded action rail for proposals. The Graph composer is the sole prompt
  input and the model selector uses `{display_name, request_model}` records.
- The existing deterministic Markdown renderer is reused for assistant
  messages. Browser/DOM evidence shows the context control opens an
  `Agent context details` dialog with used/capacity/remaining/model fields.
- The LLM provider surface previously hid the environment-backed DeepSeek
  configuration from `/llm/providers`, which made the Agent model selector
  fall back to one model and made model updates return 404. The API now
  exposes the environment provider without its key, includes verified
  `deepseek-v4-flash` and `deepseek-v4-pro` records for a DeepSeek endpoint,
  and materializes the provider into the local store when the user changes a
  model. Backend provider/store coverage is 126 passed.
- Settings browser evidence on the running worktree shows `DeepSeek V4 Flash`
  and `DeepSeek V4 Pro` in the provider model mapping and exposes Refresh
  models, Edit, and Add DeepSeek V4 presets actions. No API key value was
  displayed or written to repository files.
- Light and dark browser screenshots show the compressed navigation row, the
  theme-aware composer, and the terminal-only bottom Agent panel. The live
  browser smoke did not submit a real model switch, to avoid mutating the
  user's current environment-backed provider during visual verification;
  persistence is covered through the isolated backend test and the existing
  Agent context update test.

## 2026-07-15 confirm→execute→reconcile slice evidence

- Two latent cross-layer bugs only observable on the full round-trip (both
  fixed with regression tests): reconcile's 12-field workbench_context
  reconstruction vs the executor's 19-field persistence; and model-supplied
  proposal references (forest projection key, invented fingerprint) that pass
  proposal schema but fail the execution validator — canonicalized at
  propose_operation via the context provider per design §5.3.
- Deterministic fake-adapter suites cannot catch either class; the live
  provider + real-project HTTP round-trip remains a mandatory acceptance
  layer for every orchestration-facing change.
- Remaining for later slices: Main/Chain hierarchy projection, fork
  bidirectional UI (graph node ↔ agent message),
  diff deep-links from the operation status line, and AI-activity projection
  of operation records.

- Gate incident (fixed): the first quick-gate after this slice failed with 13
  reds in tests/test_llm_chat.py — the "not configured" expectations read the
  REAL ~/.config/econometrics-workbench/llm-providers.json that the Settings
  UI wrote at 19:39. Pre-existing isolation gap, exposed the first time a dev
  machine carried an active saved provider. Fixed with an autouse fixture
  pointing WORKBENCH_LLM_CONFIG_PATH at a temp file; check other suites for
  the same leak if new tests start asserting on unconfigured LLM state.

- Process incident (self-inflicted, corrected): the provider-store isolation
  fixture was first written via a RELATIVE path from a shell whose cwd had
  silently reset to the MAIN checkout — so the fix landed on main, the
  verification "35 passed" ran against main, and the worktree gate stayed
  red. Main was restored (`git checkout -- tests/test_llm_chat.py`, diff was
  exactly the 13 accidental lines), the fixture applied to the worktree file,
  and solo+combo runs are green in the worktree. Rule reinforced: every
  file-mutating or test-running command in this repo must use absolute paths
  or an explicit `cd` into the worktree — the session shell cwd resets.

## 2026-07-15 proposal decline/revision evidence

- Proposal storage already had an append-only `revise()` primitive but no HTTP
  route or Agent surface action. It also lacked a first-class decline record;
  the new `ProposalDecision` keeps decline status, reason, actor, revision and
  fingerprint explicit rather than overloading confirmation metadata.
- Revision reuses the registered operation validator with immutable target and
  preconditions. This preserves the spec §8.3 boundary: a user may adjust
  allowed operation changes without retargeting a node or silently refreshing
  stale context.
- Route regression evidence covers successful decline with no run mutation,
  confirmation rejection after decline, revision preserving target and
  preconditions, stale base revision rejection, and invalid empty changes
  returning `AGENT_PROPOSAL_INVALID`.
- Frontend evidence covers visible Decline/Revise actions, the JSON revision
  editor, scoped API calls, proposal status update and revision number update.
  Operation-specific structured field controls remain a later UX refinement;
  the current editor is deliberately a thin typed boundary, not a generic
  mutation editor.
- Full verification evidence: the focused Agent/LLM/rerun regression passed with
  232 tests. The isolated quick gate passed with backend 1627 passed / 8 skipped,
  frontend 125 files / 1084 tests, gate contract 9 passed, and typecheck clean.
  The stage-close full gate also passed: backend 1627 passed / 8 skipped,
  golden/invariants 23 passed, frontend 125 files / 1084 tests, TypeScript
  passed, final `GATE PASSED`.

## 2026-07-15 bidirectional navigation evidence

- The durable navigation boundary is now typed and read-only. Session,
  operation, and graph projections resolve links from stored IDs and verified
  run/node metadata; no natural-language parsing or inferred target is used.
- The real CLI cross-section seed rendered the graph and Agent terminal, but
  it intentionally had no Agent operation record or fork. The graph action
  menu therefore returned the honest unavailable state instead of inventing an
  Agent destination. The same missing durable records explain why a live
  browser click-through could not be claimed on that seed.
- The browser did verify the surrounding user-visible contract: exactly one
  terminal input, model options `DeepSeek V4 Flash`/`DeepSeek V4 Pro` with the
  selector changing to Pro, and a measured context ring of `30×30` pixels.
- Browser startup in this environment has two independent network namespaces:
  the sandboxed shell could not reach a uvicorn process started with local-bind
  approval, although the browser could load the Vite page. This prevented a
  reliable browser click-through against a temporary Agent fixture; backend
  route/projection tests and typed frontend navigation tests remain the direct
  evidence for that relationship.
- Final full gate is green: backend `1639 passed, 8 skipped`, golden `23
  passed`, frontend `126 files / 1095 tests`, TypeScript passed. `git diff
  --check` passed and protected adversarial review files were untouched.

## 2026-07-15 Agent navigation fixture findings

- The existing CLI fake run was insufficient for browser acceptance because it
  had no durable Agent operation/fork/child-chain/session relationship. The
  new local seeder exercises the production dispatcher and confirmed rerun
  workflow instead of writing synthetic graph or Agent files.
- Real graph UI selectors are `node_hash::node_ref`; durable rerun targets are
  canonical `node_hash`. The projector previously compared these as identical
  strings, causing the honest `Agent lineage unavailable` response. The
  projector now validates both shapes without changing durable facts.
- Running Uvicorn or a standalone script from this checkout can otherwise
  import an older installed `workbench` package. The seeder pins `backend/`
  itself; browser docs require `PYTHONPATH=backend`. This was the cause of the
  first browser 404, not a storage or resolver failure.
- Child Agent navigation projections can contain the same Chain ID with
  different relations. `AgentPanel` previously emitted duplicate React keys;
  relation is now part of the key and the focused browser reload produced no
  new duplicate-key error.
- Browser acceptance remains separate from tests. Fresh focused evidence is
  `10 passed` for fixture/navigation backend tests, `12 passed` for AgentPanel,
  and the visible source graph → Agent message → operation → child run/fork →
  child graph → child Agent path plus operation/child reloads. At that point,
  Main/Chain tree UI and AI Activity operation/diff projection were deferred
  slices; the tree is addressed in the dated finding below.

## 2026-07-15 Main/Chain hierarchy findings

- Flat navigation refs were sufficient for buttons but not for a truthful tree:
  the parent Chain relationship lives in ChainStore, while source Chain
  identity may exist only in durable session metadata. The new backend
  hierarchy keeps those facts separate and marks the source Chain `idle`
  rather than inventing an active ChainStore record.
- The browser fixture now renders Main → source Chain → completed operation /
  fork / child run → child Chain → child Agent. Clicking the child Agent from
  the tree preserves typed URL state and reload restores both tree and
  inherited transcript.
- At the time of this dated finding, Main/Chain tree was complete for the
  read-only projection slice; the following dated finding records the next
  AI Activity operation/diff slice.

## 2026-07-15 AI Activity operation/diff findings

- The existing AI Activity panel was localStorage-only, so it could not show a
  confirmed Agent operation after reload or distinguish durable verification
  from assistant prose. The new backend activity projection fixes that seam
  without removing the v1.6.12 compatibility records.
- The Main identity must resolve from the project SessionRepository's durable
  `role=main` record; hardcoding `agent_main` broke projects whose Main session
  used another stable ID and was caught by the first activity projection test.
- Diff display remains intentionally bounded to `diff_ref` kind/changed fields
  and the authoritative `verification.passed` result. It does not recompute or
  infer a diff in the browser. The following dated slice adds the typed
  `diff=1` deep-link and backend-owned Activity hierarchy.

## 2026-07-15 diff deep-link and AI Activity hierarchy findings

- A diff has no independent mutable identity in the current contract, so its
  typed ref uses the durable operation record ID plus `diff=1`; this keeps the
  operation record as the only fact source and makes stale/missing operation
  handling fail closed through the existing operation route.
- AI Activity now receives the same backend-owned Main/Chain hierarchy used by
  the Agent panel, with diff as an operation child. The frontend renders this
  tree and routes every node through the shared typed navigation adapter.

## 2026-07-15 Foundation v2.1 reliability findings

- The Agent operation lifecycle is now genuinely shared for the two current
  typed operations. Recovery after `after_domain_commit` observes a committed
  business effect with a pending projection and terminalizes it without
  creating another child effect.
- The supported concurrency contract is single worker plus same-process
  duplicate requests, HTTP retries, and recoverable on-disk Chain leases.
  JSONL claim/lease state is not a truthful multi-worker control plane; that
  boundary is now explicit in the fixture manifest and browser smoke docs.
- The fresh browser fixture proves the durable relationship and reload path,
  but it intentionally does not prove a natural-language LLM turn: the smoke
  uses a no-op adapter and does not call DeepSeek. The existing graph detail
  rerun control also remains a separate direct run path; it is not counted as
  an Agent proposal confirmation.
- This is fault tolerance/recovery and concurrency consistency testing, not
  "antifragility" in the strict sense. The system does not yet claim to become
  stronger automatically after a failure.

## 2026-07-15 V11 `data.column.cast` findings

- The first data-layer operation now runs through typed preview → proposal →
  confirmation → precondition revalidation → shared lifecycle execution. The
  natural-language registry intentionally excludes it until the typed manual
  contract is stable.
- The browser smoke exposed the correct scope boundary: the drawer receives
  `cleaned_dataset` and its columns from the selected graph node's backend
  context. It does not accept an arbitrary artifact path, column string, or
  target node guessed from text.
- Preview and effect matched for the real fixture (`wage`, `int64 → string`,
  30 conversions, 0 failures, 0 new missing). The final verification recorded
  `preview_matches_effect=true` and `source_immutable=true`.
- Reload proved durable graph projection rather than transient UI state: one
  `data-cast:<effect>` child node and one `data.column.cast` edge appeared,
  while the downstream model was marked caution/rerun-required. A second child
  was not created.
- The current implementation creates the immutable data artifact and child
  data node in the source run's graph. It does not automatically run the
  invalidated downstream model, which is the intended V11 boundary.
- The manual smoke was performed with `actor_type=human_ui` and a deterministic
  scratch fixture. It is evidence for the typed UI path, not live-provider
  evidence for natural-language Agent execution. DeepSeek remained untouched.
