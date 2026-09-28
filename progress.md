# Progress

## 2026-07-14

- Started smoke-test and antifragile-review pass.
- Confirmed the target is the existing `workbench-v1.7` worktree.
- Launch command, fake-data source, and UI route still being identified.
- Identified the documented launch path: backend `workbench.api:app` on 8000,
  frontend Vite on 5173.
- First sandboxed backend bind failed with `operation not permitted`; the same
  documented command succeeded after controlled local bind approval.
- Backend and frontend are now running from this worktree for smoke testing.
- Smoke coverage completed against repository fake data (`cross_section.csv`)
  and isolated temporary projects: CLI/API run, graph/forest, table/report,
  node operation preview, direct rerun child, fork/patch/validate/execute
  draft loop, empty-project genesis intake, and structured fail-closed errors.
- Antifragile review found three user-visible gaps: the frontend default proxy
  points at 8010 while the documented backend uses 8000; Ask AI and report
  generation receive backend HTTP 200 but do not render result/activity in the
  UI; and the browser draft editor did not persist Save/Validate even though
  the backend contract succeeds directly.
- Services are intentionally retained for handoff at `127.0.0.1:5173` and
  `127.0.0.1:8000`; frontend was started with
  `VITE_API_PROXY_TARGET=http://127.0.0.1:8000`.
- Delivery verification: `bash scripts/gate.sh --quick` passed with 262
  focused tests and 6 gate-contract tests; final output was `GATE PASSED`.
- Brainstorming started for the missing Agent frontend surface. A visual
  companion mockup is running at `http://localhost:54110/` for layout review;
  no Workbench code has been changed for this feature yet.
- Agent HTTP contract tests are now RED by design: 3 failures prove the
  missing route seam before implementation.

- Implemented the durable Agent HTTP seam with bounded context/prompt caps,
  project/session validation, durable messages, and replayable events. The
  route tests now pass; provider secrets are not returned.
- Implemented one shared `AgentSurfaceProvider` for Graph composer and bottom
  panel. The composer is graph-width aligned, translucent, rounded, lightly
  shadowed, and exposes prompt, context ring, model list, scope, status, and
  errors. The `Agent` bottom tab is URL-addressable and transcript state is
  shared between both surfaces.
- Added provider-level tests for LLM settings model sync, durable reload
  hydration, shared turn transcript, and unsent-prompt context accounting.
- Browser smoke with the isolated fake-data project verified: Agent prompt
  returned `SMOKE_OK` from the configured DeepSeek path; the Agent transcript
  survived reload; Ask AI rendered a substantive answer; Report rendered a
  generated report; and AI activity displayed both records.
- Replaced draft lifecycle `console.error`-only failures with per-draft
  visible errors, and added a regression test for structured 409 rerun error
  display. Changed Vite's default proxy target to documented port 8000.
- The first post-change quick gate was conservative and ran the backend full
  fallback: `1604 passed, 8 skipped` in `477.49s`. The gate classifier has now
  been tightened to include Agent HTTP wiring, so the next quick gate will use
  the focused suite.
- The next quick gate exposed four unhandled frontend errors in legacy/error
  route mounts even though the test assertions passed. Root cause was the
  Agent provider assuming `model.nodes` and `providers` were always present.
  Added regression coverage for both incomplete inputs and made the provider
  degrade to empty collections. Focused regression passed: 55 tests across
  Agent context, App, and LineageRouteContainer; the full quick gate then
  passed with 265 backend tests, 1065 frontend tests, 8 gate-contract tests,
  and frontend typecheck.
- Stage-close full gate passed after the boundary fix: backend `1605 passed,
  8 skipped` with 38 warnings; golden/invariants `23 passed` with 1 warning;
  frontend `125 files / 1065 tests passed`; TypeScript passed. No push, PR,
  merge, tag, or adversarial-review-file modification was performed.
- Created `docs/superpowers/handoffs/2026-07-14-v1.7-claude-code-agent-development-handoff.md`.
  It records the canonical read order, current worktree/uncommitted-state
  boundary, memory lookup guidance, verified implementation, explicit gaps
  between the advisory Agent UI and the full proposal workflow, live followups,
  architecture debt, recommended next slice, commands, and handoff update rules.

## 2026-07-14 (Claude Code session)

- Read the full handoff canon in order, ran the read-only baseline checks
  (status/diff-check/protected files) — all matched the handoff.
- Ran a live smoke + antifragile review with repository fake data
  (`examples/datasets/*`) in an isolated scratchpad project on dedicated ports
  (backend 8015 / frontend 5177, new `backend-v17`/`frontend-v17` launch.json
  entries). Verified ols/panel_ols/iv_2sls/cs_did over HTTP, browser forest +
  drawer + rerun child + version/rail projection, Agent composer/panel shared
  transcript with durable reload replay, event cursor replay, fail-closed
  404/422 boundaries, secret hygiene, Ask AI + AI activity, and a passing
  quick gate (backend 265 / FE 1065 / contract 8 / tsc clean).
- Recorded five new findings in findings.md: OLS covariance silent no-op,
  console-only fork-draft 409, x wire-format asymmetry + unrepresentable empty
  x over HTTP, Agent storage layout diverging from spec §10.1, and minor U1/
  equation-format confirmations. No code changed; no push/PR/merge/tag; no
  worktree created; protected adversarial files untouched.

## 2026-07-14 (Claude Code session, development round)

- Agent UI: replaced the hardcoded-dark inline styles (nonexistent
  `--surface-elevated`/`--label-primary` vars falling back to #202124) with
  token-driven classes in `frontend/src/workbench/agent/agent.css`. The Graph
  composer is now a translucent, rounded, softly-shadowed Claude-Code-style
  bar (graph-column width, integrated context ring + model select + status,
  focus ring, reduced-transparency/contrast/motion fallbacks); the bottom
  Agent panel renders the transcript as a terminal log (mono, `❯` user lines,
  typed `⋮ tool ✓/✗` status lines). Verified in light AND dark themes.
- Fixed the four smoke findings: fork-draft failures now render a visible
  role=alert in NodeActionMenu; `x` accepts comma OR JSON-array form and an
  empty/omitted selector (zero-covariate DID submits over HTTP; malformed JSON
  → 422); agent sessions/events moved under `workbench/` per design §10.1;
  OLS covariance is honest end-to-end (robust→HC1, unadjusted→nonrobust,
  clustered→cluster-robust via entity_col with a statsmodels oracle test at
  1e-10; clustered without entity fails closed with OLS_CLUSTER_FIELD_MISSING;
  the ols_default_robust_se decision now records the actual variant and
  user_explicit source; golden 23 remained 0-drift).
- Handoff §7 slice landed: chain-role HTTP turns register the orchestrator's
  chain-scoped ToolRegistry (5 provider-backed read-only inspect tools +
  allowlisted propose_operation) via `WorkbenchOrchestrator.register_chain`;
  main-role turns expose no tools; a durable per-project `agent_main` session
  anchors the orchestrator. Tool results persist as typed transcript entries
  and replayable tool_execution events; a full read-only inspection performs
  zero Workbench mutation (chains/forks/operation-records stayed empty).
- Live DeepSeek regression found and fixed at the adapter boundary: the
  post-tool provider call sent internal message shapes; `model.py` now
  converts assistant tool_calls and tool results to OpenAI wire format
  (`_to_openai_wire_messages`). Also: `inspect_operation_contract`'s
  operation_id schema now enumerates registered operations (DeepSeek had
  guessed rerun/run/ols), turn budget raised to max_steps=8 (a 5-tool sweep
  blocked at 4), and tool entries carry `name` so the panel can label typed
  status lines.
- Live browser proof: DeepSeek chained all 5 read-only tools with canonical
  args extracted from the packet, recovered from UnknownOperationError by
  reading the enum, and produced a full inspection report; transcript,
  tool status lines, and blocked/failed states all render in the terminal
  panel and survive reload.

## 2026-07-14 (handoff continuation)

- Verified the next gap against the actual checkout: `ProposalStore` and
  `WorkbenchOrchestrator.confirm_proposal()` already create an append-only
  pending `OperationRecord`, but `agent_routes.py` exposes no proposal resource
  or confirmation endpoint. The frontend only projects the tool result as a
  one-line status and cannot inspect or confirm a proposal.
- Started the next thin slice: proposal listing/confirmation HTTP seam plus a
  typed AgentPanel card. Confirmation must remain fail-closed and must not
  submit a rerun; it only creates the pending operation record after session,
  fingerprint, context, and active-head checks.

## 2026-07-14 (proposal continuation)

- Completed the proposal slice with RED→GREEN coverage for the chain Agent
  protocol, nested proposal-tool schema, structured HTTP proposal creation,
  proposal listing, confirmation-only Operation Record creation, stale context,
  and cross-session scope failures.
- Added a durable chain workflow protocol that tells the model to call
  `propose_operation` instead of emitting an unpersisted Markdown/JSON proposal.
  The proposal tool now exposes the required target and precondition fields and
  registered operation enum directly in its schema.
- Fixed provider wire ordering: proposal/confirmation audit custom messages
  are preserved in the session but deferred behind contiguous tool results for
  OpenAI-compatible providers. This was found by a real DeepSeek upstream
  failure and verified with a regression test plus a subsequent live turn.
- DeepSeek browser evidence on run `20260714_195544_431976_b60e92d8`: selected
  OLS node → 4 inspection tools → structured `model.rerun` proposal → visible
  pending card → user confirmation. The UI ended `idle`, the card became
  `confirmed`, the operation record stayed `pending`, and no child run was
  created. The operation record is at the isolated temp project's
  `workbench/operation-records/` path, not in the repository.
- The next unresolved scope issue is recorded in `findings.md`: an Agent
  session created without a selected node can be reused after selection changes
  because the frontend storage key is project+run scoped. Event-cursor live
  projection and confirmed-operation execution remain pending by design.

## 2026-07-14 (scope and event-cursor continuation)

- Fixed the session scope gap in `AgentSurfaceContext`: the durable key now
  includes the server context fingerprint, and a context change clears the
  transcript, proposal cards, status, prompt, and pending confirmation state.
  In-flight responses from the previous scope are ignored, so selecting a new
  node cannot receive the old node's Agent result.
- Added typed frontend event replay through `GET /agent/sessions/{id}/events`.
  The provider maintains a monotonic `after_seq` cursor, replays events on
  hydration, polls while a turn is running, and exposes the latest cursor and
  event type in the terminal panel.
- RED→GREEN evidence: Agent frontend tests increased to 17 passing and
  TypeScript passed. Live DeepSeek read-only smoke advanced the panel from
  `events #0` to `events #17` during the turn and `events #22` at completion;
  after browser reload it replayed `events #22` and the full transcript.
- Confirmed-operation execution remains intentionally separate: the current
  confirmation seam still creates only a pending Operation Record and no child
  run.
- Gate evidence for this continuation: `bash scripts/gate.sh --quick` passed
  with backend `1621 passed, 8 skipped`, frontend `125 files / 1073 tests`,
  TypeScript and 8 gate-contract tests. Stage-close full
  `bash scripts/gate.sh` also passed with backend `1621 passed, 8 skipped`,
  golden/invariants `23 passed`, frontend `125 files / 1073 tests`, and
  TypeScript clean.
## 2026-07-14 Agent UI usability revision

- Approved and recorded the revised design: Graph composer is the only input;
  bottom Agent is terminal-only; assistant Markdown is structurally rendered;
  proposals use a bounded action rail; context uses a real popover; top chrome
  is compact; LLM Settings is the source of truth.
- Implemented the first slice in `AgentPanel.tsx`, `AgentComposer.tsx`,
  `agent.css`, `AgentSurfaceContext.tsx`, `App.tsx`, and `styles.css`.
- Made environment-backed DeepSeek settings operable in
  `provider_store.py`/`llm_routes.py`: public metadata now includes Flash/Pro
  model records without exposing the key, and a model update materializes a
  persistent local provider record.
- Focused frontend verification: 75 tests passed; TypeScript passed.
- Backend LLM verification: 126 tests passed.
- Browser verification: Graph/Agent loaded from the v1.7 worktree; one Graph
  composer, no bottom composer; context dialog; Flash/Pro model options;
  settings mapping; light and dark themes all visibly verified.
- Transcript priority, bounded action-rail layout, Markdown projection, and
  the context popover were verified in the same browser pass. The live browser
  did not submit a real model switch, to avoid mutating the user's current
  environment-backed provider; persistence is covered through isolated backend
  and frontend tests.
- Final verification: `bash scripts/gate.sh --quick` passed with backend
  `1623 passed, 8 skipped`, frontend `125 files / 1079 tests`, TypeScript,
  syntax, and gate-contract checks. Stage-close `bash scripts/gate.sh` passed
  with backend `1623 passed, 8 skipped`, golden/invariants `23 passed`,
  frontend `125 files / 1079 tests`, and TypeScript clean. `git diff --check`
  passed, and both protected adversarial review files remain unchanged.

## 2026-07-14 Agent UI usability correction

- Reproduced the remaining user-visible gaps in the running workbench before
  editing: the bottom Agent terminal had no input, the context ring rendered as
  30×36 px because the global `button { min-height: 36px }` rule overrode its
  height, and Provider Settings had no direct active-model selector or explicit
  Configure action.
- Added a terminal-integrated prompt line to the bottom Agent page. It shares
  the existing Agent surface prompt/send path, submits on Enter, and does not
  duplicate the Graph composer’s model/context controls. The panel remains a
  terminal projection rather than a second full composer.
- Constrained the context control to an actual 30×30 px circle with explicit
  width, height, min/max bounds, and `aspect-ratio`. Browser DOM measurement
  after the fix reported width=30, height=30, minWidth=30px,
  minHeight=30px, borderRadius=50%.
- Made LLM Providers directly operable: each provider card now has a model
  combobox backed by the provider’s `{display_name, request_model}` records,
  persists changes through `updateLlmProvider`, and exposes a separate
  Configure button that opens the editor. Browser verification switched the
  real DeepSeek-backed environment provider Pro→Flash, observed the persisted
  status, and opened the Configure editor; the selected model was restored to
  Flash afterward.
- Added RED→GREEN coverage for the terminal input, ring geometry, direct model
  switching, Configure entry, and the Settings→manager→Graph lifecycle. The
  focused suite passed 59 tests and TypeScript passed.
- The first quick gate run after browser settings interaction correctly failed
  only because the user-level provider store made “no configured environment”
  tests observe a real provider. Re-running with a temporary
  `WORKBENCH_LLM_CONFIG_PATH` isolated the gate and passed. The final full gate
  used the same isolated configuration and passed: backend `1623 passed,
  8 skipped`, golden/invariants `23 passed`, frontend `125 files / 1080
  tests passed`, and TypeScript clean.
- No provider key was printed or committed; the two protected adversarial
  review files remain untouched. Confirmed-operation execution is still the
  next deliberate product slice; proposal confirmation remains confirmation
  only and does not start a child run.

## 2026-07-15 (Claude Code session, confirm→execute→reconcile slice)

- Closed the first full HTTP mutation loop per design §8.2: the confirm
  endpoint now EXECUTES the confirmed proposal through
  `orchestrator.model_rerun_executor` (child chain/fork/inherited session +
  submitted child run) after the confirmation precondition recheck, and a new
  idempotent `POST /agent/sessions/{sid}/operations/{rid}/reconcile` endpoint
  completes the record with deterministic diff/verification once the child is
  terminal. The frontend polls reconcile after confirm and projects
  `model.rerun → status · child run <id>` in the Agent panel
  (`activeOperation` in AgentSurfaceContext).
- Two latent bugs found by the first end-to-end round-trip and fixed:
  (1) `reconcile_confirmed_proposal` rebuilt only 12 of the 19
  workbench_context fields the executor persists, so the strict equality
  check failed healthy children (VerificationFailed); (2) live DeepSeek
  copied the UI forest-projection key (`<hash>::<node_id>`) and a stale
  fingerprint into the proposal, which the rerun validator rejected at
  execution — `propose_operation` now canonicalizes model-supplied
  references through the context provider at creation (design §5.3), so a
  confirmable proposal is executable. The failed chain/fork/operation records
  from the pre-fix attempt remain as honest audit history.
- Semantics decision recorded: confirmation IS the execution gate. The
  parallel-session test that pinned "confirm leaves the record pending" was
  updated: a non-rerunnable fixture now lands as a durable `failed` record
  with no ghost child run; the healthy path is pinned by
  test_confirmed_proposal_executes_rerun_and_reconciles_to_completion (real
  parent run → tool-driven proposal → confirm → child run → reconcile →
  completed + verification + idempotent repeat + 404 scoping).
- Live browser proof on isolated fake data: DeepSeek inspected the node,
  produced a canonical pending proposal card (covariance clustered →
  unadjusted on the rerun child), one click on Confirm executed it, the Agent
  panel showed `model.rerun → completed · child run 20260715_002030_…`, the
  RUNS rail picked up the completed child, its model_results are genuinely
  nonrobust (`model_type: ols`, SEs differ from HC1 parent — the covariance
  honesty fix verified through the Agent loop), the operation record is
  completed with verification.passed=true and changed_fields=['covariance'],
  and the child chain/fork are active with the child as head.

- Final quick gate for this slice PASSED in the worktree: backend full
  fallback 1625 passed / 8 skipped, golden unaffected, frontend 125 files /
  1081 tests, gate contract 9, typecheck clean. Two incidents en route, both
  resolved and recorded in findings.md: the pre-existing provider-store test
  isolation gap (13 reds once a real local provider config existed), and a
  cwd-reset mishap that briefly applied that fix to the main checkout (main
  restored to byte-identical, fix re-applied in the worktree).

## 2026-07-15 proposal decline/revision slice

- Added the missing proposal lifecycle actions without changing the mutation
  boundary. Decline now uses an append-only `decision` record containing the
  status, reason, actor, revision and fingerprint; it creates no Operation
  Record, child run, chain or fork.
- Added scoped revision HTTP support. A revision may change only `changes`,
  `expected_effect`, and `risks`; target and preconditions are copied from the
  immutable prior revision. The registered operation definition validates the
  new changes before the new fingerprint is persisted.
- AgentPanel now exposes Decline and Revise actions for pending proposals. The
  revision editor accepts a bounded JSON object for operation changes and uses
  the existing scoped busy state so confirmation, decline and revision cannot
  overlap. AgentSurfaceContext updates the proposal and replays events after a
  successful action.
- RED→GREEN evidence: decline/revision route tests passed; AgentPanel and
  AgentSurfaceContext action tests passed; TypeScript passed. The focused
  Agent/LLM/rerun regression passed with 232 tests. The isolated quick gate
  passed with backend 1627 passed / 8 skipped, frontend 125 files / 1084
  tests, gate contract 9 passed, and typecheck clean.
- Stage-close full gate then passed in the worktree: backend 1627 passed / 8
  skipped, golden/invariants 23 passed, frontend 125 files / 1084 tests, and
  TypeScript passed. Final output was `GATE PASSED`.

## 2026-07-15 Main/Chain/fork bidirectional navigation slice

- Added a read-only `AgentNavigationProjector` spanning project-local Agent
  stores and verified graph/run metadata. It projects typed refs between Agent
  sessions/messages, Main, Chain, proposal, operation record, source graph
  node, child run, fork, child Chain, and child Agent session.
- Added scoped HTTP projections for Agent sessions, graph nodes, and operation
  records. Durable message entries now carry internal `command_id` metadata,
  which is stripped before provider wire conversion and used to attach exact
  operation refs to message-level UI links without parsing message prose.
- Added a typed frontend URL adapter and shared route navigation context. The
  Graph detail action menu and Agent terminal panel now consume the same typed
  refs, preserve unrelated URL state, and support reload-stable Agent/graph/
  operation deep links. Read-only projection of an unknown graph scope does
  not create `workbench/` storage.
- Verification: backend navigation/routes/foundation `43 passed`; focused
  frontend navigation/surface/route/menu `76 passed`; final full gate backend
  `1639 passed, 8 skipped`, golden `23 passed`, frontend `126 files / 1095
  tests`, TypeScript passed, final `GATE PASSED`; `git diff --check` passed.
- Browser evidence on a real seeded graph: Graph and Agent terminal rendered;
  the terminal input was visible; Flash and Pro were both exposed and the
  selector changed to Pro; context ring measured exactly `30×30`; node action
  menu correctly showed `Agent lineage` unavailable because this CLI seed had
  no durable Agent operation/fork record. This is recorded as unavailable
  data, not claimed as a live navigation success.
- Boundaries: current branch is `workbench-v1.7`; protected adversarial files
  have no status output; no second worktree, push, PR, merge, or tag was used.

## 2026-07-15 real Agent navigation smoke fixture

- Added `backend/workbench/dev_fixtures/agent_navigation.py` and
  `scripts/seed_agent_navigation_smoke.py`. The seeder refuses non-empty
  project roots, runs a real OLS source graph with incremental node identity,
  then uses `WorkbenchOrchestrator` confirmation/execution/reconciliation to
  create the real child run, operation record, fork, child chain, and inherited
  child Agent session. It never invokes an LLM provider.
- Added `tests/test_agent_navigation_fixture.py` covering durable run inputs,
  completed operation verification, fork/chain state, source-message links,
  child-graph links, and refusal to overwrite an existing project.
- Fixed the read-only navigation projector to accept the browser's
  `node_hash::node_ref` selector while retaining canonical durable
  `forest_node_key=node_hash`; graph projection now also returns the owning
  source Agent session and browser-shaped source graph href.
- Browser evidence on a fresh `/private/tmp` fixture: source graph
  `Agent lineage` became available; source Agent message exposed the real
  proposal/operation/child run/fork/chain/session refs; operation deep-link
  reload preserved `panel=agent`, session, operation and completed child-run
  status; child graph opened the child Agent; child Agent inherited the source
  message plus completed operation result and survived reload.
- Browser startup required `PYTHONPATH=backend` to pin Uvicorn to this
  worktree. The smoke script pins its own import path and the docs now make
  the server-side pin explicit. A browser duplicate-key warning from two
  relation variants of one Chain was fixed with a RED→GREEN AgentPanel test by
  including relation in typed navigation React keys.

## 2026-07-15 Main/Chain hierarchy tree

- Added backend-owned `AgentHierarchyNode` projection to the existing session
  navigation response. The tree is rebuilt from session metadata, ChainStore,
  OperationRecordStore, ProposalStore, ForkStore, and run manifests; the
  frontend does not infer parent/child relationships from flat links or text.
- Added the read-only `Main / Chain hierarchy` Agent panel tree with typed
  navigation for Main, Chain, operation, fork, run, and child Agent nodes.
- Browser verified the real fixture tree, source Chain → operation → child
  Chain → child Agent navigation, URL scope, child Agent reload, and inherited
  transcript recovery. Current browser console error count was zero.

## 2026-07-15 AI Activity operation/diff projection

- Added a read-only `AgentNavigationProjector.activity()` projection and
  `GET /agent/activity`; it derives Main, Chain, operation, typed child links,
  `diff_ref`, and `verification` from durable stores.
- Extended the AI Activity panel to merge backend operation activity with the
  existing local Ask AI/report compatibility log. Operation rows show the
  verified status and deterministic diff summary, and reuse the existing typed
  navigation adapter for run/fork/child Agent links.
- TDD evidence: backend projector and route tests passed; the frontend test
  verifies the `/api/agent/activity` proxy/scope URL, Main/Chain path, diff,
  verification, and typed link callback.

## 2026-07-15 diff deep-link and AI Activity hierarchy

- Added a typed `diff` navigation ref backed by the durable operation record;
  `diff=1` is only written together with `operation` and reloads into the
  existing Agent panel route.
- Extended the operation projection and Main/Chain hierarchy with a diff
  child node. The Agent panel renders the backend `diff_ref` kind/changed
  fields and authoritative verification when the diff deep-link is focused.
- Extended `GET /agent/activity` with the backend-owned hierarchy so AI
  Activity renders Main → Chain → operation → diff/fork/run/child Agent
  relationships without frontend inference.
- TDD evidence: backend activity/navigation/routes and frontend URL,
  navigation, Activity, and Agent deep-link tests are green.

## 2026-07-15 Agent Operation Reliability Closeout / Foundation v2.1

- Unified Agent-confirmed `model.rerun` and `graph.fork` execution behind the
  shared `WorkbenchOperationLifecycle`: claim, deterministic execution key,
  Chain lease, effect binding, domain commit, terminalization, and reconcile.
- Added deterministic failpoints for claim/effect/binding/domain-commit/
  terminal windows, separated durable `effect_status` from
  `projection_status`, made partial JSONL tails recoverable without accepting
  malformed complete records, and added lease/duplicate/competing-head tests.
- AI Activity now projects and displays `effect_status` and
  `projection_status` from the backend-owned operation record.
- Added the single-worker boundary to the browser smoke contract. The JSONL
  control plane is not claimed to be multi-worker safe.
- Fresh local fixture: `/private/tmp/wb-v17-agent-reliability-20260715-132000`.
  Browser verified typed graph → Agent → proposal → graph.fork confirmation →
  child Chain/Agent, operation/diff deep links, AI Activity hierarchy/events,
  scope-preserving URLs, and reload recovery. No LLM/provider request was
  made; smoke servers were stopped after acceptance.
- Verification: quick and full gate both passed; backend `1675 passed, 8
  skipped`, golden `23 passed`, frontend `128 files / 1109 tests`,
  TypeScript passed, final `GATE PASSED`; `git diff --check` passed.

## 2026-07-15 V11 `data.column.cast` first vertical slice

- Added the dated V11 design/plan, but kept the implementation boundary to one
  typed manual operation: `data.column.cast`. It is deliberately not exposed
  to the natural-language proposal tool yet.
- Added strict typed backend preview/confirm/readback routes and a read-only
  context resolver. Preview binds to the real graph node/artifact context;
  column and target dtype are enum/owned values, and parse failures block the
  operation.
- Added the shared lifecycle execution path for the data effect: deterministic
  execution key, immutable derived CSV plus recipe artifact, graph child node,
  schema fingerprint diff, downstream model invalidation, Operation Record,
  verification, and recovery tests for post-effect crash windows.
- Added the dataset-node UI with backend-populated column selection, preview
  counts, downstream rerun warning, typed confirmation, and durable completion
  state. Added frontend API/UI tests and registry wiring.
- Browser evidence on scratch project
  `/private/tmp/wb-v17-agent-rerun-20260715-173500`: selected `wage`, changed
  `int64 → string`; visible preview was `30 converted · 0 failures · 0 new
  missing`, confirmation returned
  `oprec_4049c358a57d8f592ade45a1`, and reload showed the child node
  `Cast wage → string` plus `data source changed; rerun required`.
- Backend evidence for the same browser action: one cast node and one cast
  edge; source `cleaned_dataset` SHA remained unchanged; derived artifact
  `data_cast_570f5767f06dae6f28176c41d473cb51`; final Operation Record was
  `completed / committed / complete` with `verification.passed=true` and
  `source_immutable=true`.
- Browser did not invoke DeepSeek; the operation actor was `human_ui`. This
  slice does not claim all legacy rerun entrypoints share the typed lifecycle,
  does not enable natural-language `data.column.cast`, and does not include a
  Main Agent or multi-worker guarantee.

## 2026-07-15 V11 hardening: browser acceptance, idempotency proof, child-node provenance

- Repeated the full V11 browser acceptance with in-app browser automation on a
  fresh fixture `/private/tmp/wb-v17-agent-rerun-20260715-151026` (servers
  pinned to this worktree, scratch LLM config; backend saw no `/llm/chat`).
  Cast `wage int64 → string` via Preview → Confirm →
  `oprec_ac4940123ded794e7e208e5c`; reload kept the child node, the
  `data source changed; rerun required` model badge, and the immutable source.
- Idempotency/e2e proof against the live HTTP API: replaying the same confirm
  twice returned the same durable record with zero new state lines (all 8
  lines carry the original execution timestamps); two concurrent duplicate
  confirms for a second cast (`education`) converged to one record
  `oprec_e52f5f2c6b9debdae014233e`, one derived directory, and one child; a
  bogus `preview_fingerprint` returned `409 DATA_OPERATION_STALE`.
- Extended the lifecycle reconcile test to all seven failpoint windows
  (`after_claim`, `before_child_effect`, `after_child_effect`,
  `after_effect_binding`, `before_domain_commit`, `after_domain_commit`,
  `before_terminal_reconcile`) and added a source-SHA-unchanged assertion
  captured before execution.
- Child-node completeness fixes: the cast child's `created_at` was a
  hardcoded constant and the child had no Merkle identity, which disabled Ask
  AI (`missing_node_hash`) and emptied the lineage path. The effect now stamps
  the real UTC time and writes a `node_index.json` entry whose `node_hash` is
  the derived artifact's content hash (same convention as `stage:raw`;
  legacy runs without an index stay opaque, and a conflicting entry fails
  closed).
- Added `GET /data-operations/column-cast/by-child-node` which resolves the
  durable operation record from the typed `data_child_node_id` binding, and a
  frontend provenance block on cast child nodes: operation id, Operation
  Record id/status, `verification passed`, typed schema diff, execution key,
  and recipe path; annotations keep the block meaningful if the record fetch
  fails.
- Browser-verified on a third cast (`experience int64 → string`,
  `oprec_0d519f1daf90c554147a855f`): the child drawer shows the provenance
  block, Ask AI resolves a real context, the lineage path is
  `Raw input data → Cleaned data → Cast experience → string`, and `Created`
  is the real operation time. No console errors.
- Known limitation recorded: the derived artifact is CSV, so a
  string-of-digits column reads back as int64 in the chained-cast context;
  the schema fingerprint in the recipe remains the authoritative dtype record.

## 2026-07-15 G1: data.columns.cast batch operation (fixes graph explosion)

- User feedback: casting a dozen columns one-by-one produces a dozen sibling
  cast nodes that stack past the screen and explode the lineage graph; and no
  single node represents the fully-cast dataset (per-op audit grain is wrong).
- Fix (治本): added `data.columns.cast` v1 — a batch typed operation carrying N
  (column, target_dtype) pairs. One preview (per-column results + one aggregate
  fingerprint), one confirm, one immutable child artifact with all casts
  applied, one recipe (`data-columns-cast.v1`, N entries), one graph child node,
  one schema diff, one Operation Record. Operation grain now matches user
  intent. This is also the target shape for a future NL proposal.
- Additive design: the shipped singular `data.column.cast` path is untouched
  (zero regression risk). The batch path reuses the leaf helpers
  (`_convert_strict` / `_schema_fingerprint` / `_resolve_source` /
  `_ensure_registered_artifact` / `_ensure_node_index_entry`) and the same
  confirm→execute→reconcile lifecycle via new orchestrator branches keyed on
  `executor_key="data.columns.cast"`.
- Layers: `DataColumnsCastSpecV1`/`DataColumnsCastPreview`/`apply_data_columns_cast`
  in data_operations.py; registry entry + proposal schema + validator in
  agent/operations.py; spec builder + `_prepare_data_columns_cast_effect` +
  4 executor branches + terminalization set in orchestrator.py; batch
  preview/confirm routes + `by-child-node` generalized to both op ids in
  http/data_operation_routes.py; frontend batch multi-row builder in
  DataColumnCastSection.tsx (add/remove rows, cross-row column exclusion,
  per-column preview lines, batch/singular provenance diff).
- Tests: tests/test_data_columns_cast.py (spec validation, per-column preview,
  block-if-any-fails, one-child idempotent effect, shared lifecycle, 4-failpoint
  reconcile); batch route tests; frontend single+multi-column component tests;
  updated capability enumeration test.
- Browser evidence on scratch `/private/tmp/wb-v17-batch-cast-20260715-182820`:
  built wage→string + education→string, `Preview 2 casts` listed both, confirmed
  `oprec_b7a6ddd5fc61a8b92541ff55`; reload showed exactly one `Cast 2 columns`
  child node ("2 columns cast (wage→string, education→string)") and the model
  marked rerun-required. Durable: one record completed/committed/complete,
  verification passed, columns_cast=[wage,education], one derived dir, one
  `data-casts:` node, source SHA unchanged; by-child-node returns diff_ref.casts.
  No console errors.
- Known limitation carried over from singular: derived artifact is CSV, so a
  string-of-digits column reads back as int64 on re-read; the recipe schema
  fingerprint is the authoritative dtype record.
- Not done this pass (per user sequencing): G2 (Ask-AI-about-figure) and G3
  (terminal input dedup + code.execute sandbox); NL enablement of the batch op.

## 2026-07-15 dtype/Excel fix (D1) + G2 figure AI + G3 terminal dedup

### D1 — derived-artifact dtype preservation + CSV/Excel output
- Root cause: derived cast artifacts were CSV; pandas re-infers dtypes on read,
  so a string-of-digits column came back int64 (chained-cast context wrong).
- Fix: every derived cast artifact now writes a `<stem>.schema.json` dtype
  sidecar; `_read_frame` restores exact dtypes from it (format-agnostic). Added
  `output_format` (csv | xlsx) to `data.columns.cast`; xlsx written via a bytes
  durable writer, idempotency checked by re-read frame equality (xlsx bytes are
  not deterministic). Singular `data.column.cast` also writes the sidecar
  (data content unchanged → hashes/registration identical, purely additive).
- Threaded output_format through request → target → orchestrator spec →
  validator. UI: an "Output CSV/Excel" selector in the batch section.
- Browser+durable proof (scratch wb-v17-g2g3-...): Excel cast of wage→string
  wrote data.xlsx + data.schema.json + recipe; `_read_frame` restores wage to
  `string` ['20','21','22'] while a naive pandas read gives int64; source SHA
  unchanged, one derived, one node, oprec_7518eb35cd9386ec8398f5e3.

### G2 — Ask AI about a figure (interpret from numbers, not pixels)
- New serve-time `figure_context.py`: maps each figure artifact_id to its chart
  type and the numeric artifact that backs it (coef_plot→model results,
  histograms/kde/boxplots→data_profile, correlation/scatter→correlations,
  residuals/qq→diagnostics), returns a bounded safe JSON preview + guidance +
  guardrails. Decorate-only (reads the artifacts index), so golden 0-drift holds.
- Route `GET /figures/ai-context`; `/llm/chat` gains a `workbench_figure_context_v1`
  mode with a header that forbids claiming to see pixels and requires grounding
  in the numeric source.
- UI: "Ask AI about this figure" per figure in the Results (Table) figure gallery.
- Browser proof: clicking it on the histogram grid returned an interpretation
  citing exact profile numbers (education mean≈19.0 σ≈4.39, experience mean≈9.5)
  — grounded in the data profile, not the image. No console errors. (Used the
  operator's configured DeepSeek; the smoke config path was empty so it fell
  back to the default provider.)

### G3 — terminal input dedup (+ code.execute design)
- The bottom AgentPanel had an input row synced with the graph composer (pure
  redundancy). Removed it; the panel is now a read-only transcript/inspection
  surface with a one-line hint pointing to the single input (the composer under
  the graph). Elevated capability is deferred to a typed `code.execute`
  operation whose output streams here — permission belongs to the operation,
  not the input box.
- `code.execute` sandbox is designed (roadmap direction doc §G3) but NOT
  implemented: running arbitrary agent code needs a real sandbox (subprocess,
  no network, read-only FS except the derived output dir, resource limits) that
  is a separate security-critical effort. Ships as a typed operation on the same
  proposal→confirm→execute→record→verify lifecycle when that runner exists.

## 2026-07-15 G1 folding + G2 multimodal + G3 sandbox

### G1 — canvas projection folding (closes G1)
- `folding.ts`: generalized `foldVariableClusters` → `foldNodeClusters`, which now
  also buckets data-operation children (`data-cast:` / `data-casts:`, matched on
  the BACKEND node id since the view id may be a forest key `<hash>::<id>`) by
  parent and folds >3 siblings into one `Data operations (N)` card
  (variant `data_operation`). Nothing branches on the variant, so the existing
  collapsed/expanded group rendering works unchanged.
- Principle held: fold the PROJECTION, never the lineage. Every child keeps its
  own node, Operation Record and Merkle identity and stays reachable via the group.
- Tests: 5 new (no-fold ≤3, fold >3 with label/id/variant, per-parent bucketing +
  singular prefix, expand, ordinary dataset nodes untouched). 10 folding tests
  total; 145 graph tests still green.

### G2 — multimodal "actually look at the chart" (closes G2)
- `supports_vision` threaded exactly like `supports_1m`: ModelRecord (+parse,
  +to_dict) → LLMConfig → `/llm/config` → provider request model → refresh
  preservation. It is OPERATOR metadata: a model refresh must not silently
  un-mark a vision model (regression test added).
- `/llm/chat` accepts an optional `image_data_url`, fail-closed on three axes:
  figure mode only, PNG data-URL only, and only when the active model is marked
  vision-capable (else 422 with a distinct code). Bounded at 6MB.
- Correctness detail: the text-only figure header says "You CANNOT see the
  image" — sending an image while claiming that would be a lie, so vision
  requests get their own header. It still forbids reading NUMBERS off pixels:
  numbers must come from the numeric source; the image is only for visual
  structure (shape/outliers/overplotting), and on disagreement trust the numbers.
- UI: default-OFF opt-in that names the destination ("Also send the rendered
  image to <provider> (<model>) — leaves your machine"), shown only when the
  model is vision-capable. This is the one place the binaries-excluded policy is
  broken, so the user sees exactly what leaves the machine.
- Tests: 6 backend (text-only default carries no image part; opt-in produces
  OpenAI multimodal content + vision header; rejected when model lacks vision;
  rejected outside figure mode; non-PNG rejected; /llm/config exposes it) +
  3 frontend (hidden without vision, default-off naming the provider, PNG sent
  only after opt-in). Found and fixed a real test-isolation bug: the new
  describe was a sibling, so the outer beforeEach reset never ran and mock calls
  leaked across tests.

### G3 — sandbox runner (the blocker; operation wiring still open)
- `sandbox.py`: detects an OS isolation backend (macOS `sandbox-exec` seatbelt /
  Linux `bwrap`) and REFUSES to execute when none exists — never degrades to
  in-process exec, because a Python-level guard is not a sandbox and pretending
  it is would be the actual security failure.
- Seatbelt profile: allow default → `deny network*` → `deny file-write*` →
  re-allow only the operation's output dir + a private temp HOME. Plus
  setrlimit (CPU/AS/FSIZE), wall-clock timeout, and a scrubbed env so provider
  API keys are never inherited by transform code.
- Honest boundary (documented in the module): reads are allowed (stdlib/
  site-packages, and the data is the user's own); the threat model is a
  misbehaving LLM/user transform (clobbering the source, hanging, phoning home),
  NOT an adversary who already has code execution.
- 8 tests that PROVE the boundaries by running real code: network egress
  blocked, out-of-dir write blocked (source survives byte-for-byte), in-dir
  write allowed, CPU runaway killed, wall clock enforced, host secrets absent,
  fail-closed with no backend.
- STILL OPEN: the `code.execute` typed operation itself. Deliberately not
  rushed — it has a real undecided design question: arbitrary code has no
  side-effect-free preview, so preview must actually RUN in the sandbox to a
  temp dir and show a schema diff, which gives preview execution semantics and
  redefines fingerprint/idempotency/failure states. Recorded in roadmap G3.
