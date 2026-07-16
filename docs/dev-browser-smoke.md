# V1.5.0 Browser Smoke

Reproducible browser smoke for the lineage view. Replaces the ad-hoc
tool-specific harness in `.claude/` so any contributor can run the
same checks regardless of environment.

## Setup (one-time)

```bash
python3 -m pip install -e ".[dev]"   # creates .venv
cd frontend && npm install
```

## Run the smoke

In two terminals from the worktree root:

```bash
# Terminal 1 — backend
.venv/bin/uvicorn workbench.api:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev   # serves http://localhost:5173
```

Create a fresh v3 run:

```bash
SMOKE_NAME="wb-smoke-$(date +%Y%m%d-%H%M%S)"
.venv/bin/workbench create /private/tmp "$SMOKE_NAME"
.venv/bin/workbench run "/private/tmp/$SMOKE_NAME" \
  examples/datasets/cross_section.csv wage \
  --x education --x experience --x region
```

Use a new scratch name for each run. Do not remove or overwrite an existing
scratch project from this document.

The CLI prints two lines:

```
<run_id>
Lineage: http://localhost:5173/runs/<run_id>?project_root=...&tab=lineage
```

Open the `Lineage:` URL — you should land directly on the lineage
tab with the freshly-built graph rendered. **Do not** navigate through
the Submit page first; the URL is self-contained.

## V1.5.0 smoke checklist

Walks the spec §16 L1–L20 items plus V1.5.0 product-path adds.

### Path & navigation

- [ ] CLI URL opens the Lineage tab directly (no manual clicks)
- [ ] `Submit page → click Run workflow` auto-navigates to the same URL
- [ ] No legacy banner (run is fresh v3 → `legacy=false`)
- [ ] No legacy stage hint (≥50% of nodes carry a real stage)

### Graph rendering

- [ ] Graph nodes visible with editorial card layout
- [ ] Left 8px colour bar reflects `stage` (`--stage-*` tokens)
- [ ] Synthetic group nodes (e.g. "Variables (4)") render with
      neutral grey bar (`stage="unknown"` falls back to
      `--label-tertiary`)
- [ ] Trust badges (`REVIEW` / `CAUTION`) appear on nodes whose trust
      or decisions warrant attention
- [ ] No `console.error` from React Flow or our code

### Detail drawer

- [ ] Click a node → drawer slides in from the right
- [ ] Header: `KIND` eyebrow + serif title + actions menu + close
- [ ] T7 L32: Open three different nodes → drawer shows three tabs
- [ ] T7 L33: Click a drawer tab → that tab becomes active and the
      body switches to that node
- [ ] T7 L34: Close the active tab → the neighbouring tab becomes active
- [ ] T7 L35: Open a 9th node tab → the oldest tab is evicted and a
      short eviction notice appears
- [ ] `REVIEW REQUIRED` callout when decisions need confirmation
- [ ] `LINEAGE PATH` row with copy button
- [ ] `BASIC INFO` section (KIND / STAGE / CREATED)
- [ ] `DECISIONS (N)` cards (when N > 0); each card expands inline

### Tooltip

- [ ] Hover a node for ≥240ms → tooltip appears
- [ ] Tooltip position follows the cursor; **does not** scale with
      the canvas zoom (zoom in/out, then re-hover — tooltip stays
      pixel-sized)
- [ ] Tooltip suppressed once a node is selected (drawer takes over)

### Canvas chrome (T8.6)

- [ ] Top-left: `Auto / Fit / Fullscreen` toolbar.
      `Auto` is `disabled` with `aria-pressed="true"` — not a
      clickable no-op.
- [ ] `Fit` re-fits the graph to the viewport.
- [ ] `Fullscreen` toggles the lineage container into fullscreen;
      no error in an iframe-sandboxed or older-browser context
- [ ] Top-right: `run_<id> · waiting <N> reviews` status badge.
      Count survives folding / selection (it iterates the whole
      view model).
- [ ] Bottom-right: collapsed `STAGES` chip; hover-expands to 8
      swatches with Chinese labels (原始 / 探索 / 清洗 / 变换 /
      模型 / 诊断 / 可视化 / 报告). No `unknown` row.
- [ ] Bottom-left: React Flow Controls as a horizontal dark pill
      (3 buttons: zoom-in / zoom-out / fit-view)

### Tri-state highlighting (T8.5)

- [ ] No selection → all nodes at full opacity (`data-state=related`)
- [ ] Select middle node → in/out neighbours stay full opacity;
      unrelated nodes drop to `opacity: 0.4` (`data-state=dim`)

### Keyboard

- [ ] `⌘J` (macOS) / `Ctrl+J` (Linux/Windows) toggles the Raw JSON
      modal even while the drawer is open and scrolled
- [ ] `Esc` closes the modal first (without clearing selection),
      then on a second press clears the selection

## Known V1.5.0 visual gaps vs uiux/screenshots/initial.png

These are **intentional** at V1.5.0 scope — listed here so smoke
reviewers don't file them as defects.

| Gap | Status |
|---|---|
| Left rail (stage navigation with counts) | Replaced by V1.5.1 Run History rail |
| Top-row workspace breadcrumb / search-K / rerun / generate-report buttons | Deferred to V1.5.1+ |
| Bottom terminal panel | Deferred to V1.5.1+ |
| Drawer header uses flat text path instead of breadcrumb chip path | Cosmetic, deferred |
| Trust banner has no inline action buttons (查看产物 / 回滚 / 标记为坏决策) | Deferred — rerun + AI are V1.5.1+ features |

The outer-chrome dark theming on `/runs/<id>` was P1 and has landed
in commit `e039adf`. AppShell header + Submit/History tabs +
Overview/Lineage tabs now flip to the dark editorial surface when
the route matches `/^\/runs\/[^/?#]+$/`. Submit (`/`) and the
History list (`/runs`) intentionally stay on the V1.4 light surface.

The lineage interior (graph, drawer, tooltip, chrome) matches the
design intent for V1.5.0 scope.

## Stopping the servers

`Ctrl-C` in each terminal. If a port is stuck:

```bash
lsof -i :8000 -i :5173 | awk 'NR>1 {print $2}' | sort -u | xargs kill
```

## Tool-specific harness

A `.claude/launch.json` may exist locally for the Claude Code preview
tooling — it's gitignored, optional, and not required. Use the
plain terminal flow above if you don't have that tool.

## V1.6.3 Context Hardening + Compare/Edit Smoke

Create a source run, rerun it through a context-driven node operation, open the rerun child node, and verify:

- `Compare with source` appears only on the rerun child node.
- The compare view shows summary sections for params, metrics, diagnostics, artifacts, and upstream path.
- The operation panel says `Rerun source with changes`.
- Preview shows old/new values before submit.
- Confirming rerun creates a new child.
- The UI reflects the backend-updated active head.
- If focus is pending, polling selects the child after indexing.
- No source, focus, owner, or patch target is inferred from `runs[0]`.

## V1.6.4 Draft Graph Smoke

Open an eligible executed model node from Lineage Detail and verify:

- `Open as Draft Graph` appears only for a resolved editable model node.
- The action creates a `PipelineDraft` and navigates to `/pipeline-drafts/<draft_id>?project_root=<root>`.
- The Draft Graph view renders the fixed `Input Dataset -> Model` graph.
- The InputNode inspector is read-only.
- Selecting ModelNode shows editable controls from `editable_schema`.
- Changing one editable field marks the draft `Unsaved` and keeps `Validate` and `Execute Draft` disabled.
- Clicking `Save changes` persists the draft, marks any prior validation stale, enables `Validate`, and keeps `Execute Draft` disabled.
- `Execute Draft` stays disabled until `Validate` returns a matching `validated_draft_hash`.
- After `Validate`, `Execute Draft` is enabled only for the current draft hash.
- Clicking `Execute Draft` creates/navigates to the child run lineage view.
- If the focus is pending, polling resolves using source run/model/op identifiers.
- Selecting the produced child model node exposes `Compare with source`.
- Direct `/runs/{run_id}/rerun` still works from the operation section.
- Run-level `Open in Graph` remains deferred until the route can prove exactly one eligible model node without guessing.

## V1.7 Agent navigation smoke fixture

This is the repeatable browser acceptance path for the real Agent/Graph
relationship. The seeder uses the production run dispatcher, `RerunService`,
`WorkbenchOrchestrator`, and the project-local Agent stores. It is local-only:
it does not call DeepSeek or any LLM provider, and it refuses a non-empty
project directory before creating storage.

### Seed a fresh fixture

Run this from the v1.7 worktree root. The directory must be new or empty and
must stay under `/private/tmp` (or the platform temp directory):

```bash
SMOKE_ROOT="/private/tmp/wb-v17-agent-navigation-$(date +%Y%m%d-%H%M%S)"
.venv/bin/python scripts/seed_agent_navigation_smoke.py \
  --project-root "$SMOKE_ROOT" \
  | tee "/private/tmp/wb-v17-agent-navigation-$(date +%Y%m%d-%H%M%S).json"
```

Keep the JSON output and the fixture manifest at
`$SMOKE_ROOT/workbench/agent-navigation-smoke.json`. They expose the source
and child URLs, all durable IDs, the `execution_key`, expected effect counts,
the recovery contract, the `/api` proxy scope, and the exact `project_root`
query value. The source graph URL is the starting URL.

### Start the local servers

Use separate terminals from the same worktree. The backend config path is
explicitly scratch-only; no provider request is made during this smoke:

```bash
PYTHONPATH=backend \
  env WORKBENCH_LLM_CONFIG_PATH=/Users/jiayuanren/.config/econometrics-workbench/smoke-llm.json \
  .venv/bin/uvicorn workbench.api:app --host 127.0.0.1 --port 8000
```

This smoke is a single-worker acceptance path. Start exactly one Uvicorn
worker; this v1.7 JSONL control plane does not claim cross-process or
multi-worker concurrency safety. The supported concurrency checks below are
same-process duplicate requests, HTTP retries, and an expired on-disk Chain
lease. Do not add `--workers > 1` to this procedure until the control plane is
migrated to a transactional store with unique constraints.

`PYTHONPATH=backend` is required for this checkout-local smoke: it prevents
Uvicorn from importing an older installed `workbench` package from another
worktree.

```bash
cd frontend
VITE_API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev
```

Open the `urls.source_graph` value printed by the seeder. The legacy `/runs`
URL may redirect to the current `/p/<project>/graph` route; record the final
URL rather than treating the redirect as a failure.

### Verify the complete chain

- [ ] Source graph renders the seeded completed run and the model node.
- [ ] Open the model node's actions menu. `Agent lineage` loads links instead
      of `Agent lineage unavailable`.
- [ ] From the graph projection, open the source Agent session. The URL keeps
      `project_root`, has `panel=agent`, and includes `agent_session`.
- [ ] The Agent panel shows the read-only `Main / Chain hierarchy` tree. It
      contains the Main session, source Chain, completed operation, and child
      Chain/child Agent relationship from durable records.
- [ ] The seeded user message is visible. Its typed message link opens the
      `model.rerun · completed` operation record; no run, node, fork, or
      operation is inferred from message prose.
- [ ] The message exposes `Fork from Agent message <entry_id>` only when its
      typed graph-node link is available. Click it, verify a pending
      `graph.fork` proposal, confirm it, and verify a completed operation with
      a durable active fork, child Chain, and child Agent. This graph fork has
      no child run until a later run operation is executed.
- [ ] Return to the source graph and open the model node's actions. Click
      `Fork Agent context`, confirm the proposal, and verify the same durable
      fork/child Chain/child Agent relationship from the graph-node entrypoint.
- [ ] The operation projection shows the real child run and fork links. Open
      the child run and record the URL's `run`/`focus` values.
- [ ] The child graph renders the real completed child run. Open its model
      node's actions and then open the child Agent session.
- [ ] The child Agent URL has `panel=agent` and the child `agent_session`; the
      inherited transcript and completed operation result are visible.
- [ ] Open the `AI activity` bottom panel. It loads the read-only
      `/api/agent/activity` projection in the same `project_root` scope and
      shows `Main → Chain → model.rerun · completed`, `verified`, and the
      deterministic diff kind/changed fields from the operation record.
- [ ] The AI Activity hierarchy is backend-owned and renders Main → Chain →
      operation → diff, with the durable fork/run/child Agent nodes beneath
      the operation. Do not reconstruct this parentage from row order or text.
- [ ] The AI Activity event projection renders the durable event stream with
      stable sequence numbers, event types, bounded structured details, and
      typed links. Check `operation_submitted`, `needs_confirmation`,
      `proposal_confirmed`, `fork_created`, and `operation_completed`; event
      rows must resolve through typed navigation rather than event prose.
- [ ] Open the typed `Diff · ...` link. The URL must contain
      `panel=agent`, the operation's `agent_session`, `operation`, and
      `diff=1`; the Agent panel must show the authoritative diff kind,
      changed fields, and verification result from the operation record.
- [ ] The AI Activity operation row exposes typed child run/fork/child Agent
      links. Click one and record the resulting URL; the browser must navigate
      through the existing Agent navigation adapter, not a URL guessed from
      operation text.

### URL, proxy, scope, reload, and data checks

At each navigation step, record the visible URL and check that the browser
network request uses the frontend `/api` proxy. For the source graph it should
include `/api/agent/navigation/graph` plus the same `project_root`, `run_id`,
`node_ref`, and `forest_node_key` shown in the fixture JSON. Agent requests
must stay in that exact project scope; do not replace it with a real project
path or a direct provider URL.

Reload at these checkpoints and verify the same typed state returns:

- source Agent message (`panel=agent`, `agent_session`, `agent_entry`);
- operation (`panel=agent`, `agent_session`, `operation`);
- operation diff (`panel=agent`, `agent_session`, `operation`, `diff=1`);
- child graph (`run` plus `focus`); and
- child Agent (`panel=agent`, child `agent_session`), including the same
      `Main / Chain hierarchy` tree.
- AI Activity (`panel=ai`) and verify the durable hierarchy, operation row,
      diff summary, typed links, and the same content after reload. Reload the
      `diff=1` URL as a separate checkpoint.
- message-created and graph-node-created `graph.fork` proposals, including
      their pending → confirmed → completed state and the resulting durable
      fork/child Chain/child Agent records.

After the smoke, inspect the fixture manifest and durable records: both run
manifests are `completed`, `run_inputs.rerun_of` points from child to source,
the operation record is `completed` with `verification.passed=true`, the fork
is `active`, and the child chain active head is the child run. The AI Activity
request must be a GET through `/api` with the fixture's exact `project_root`,
and its operation/diff values must match the operation record rather than
localStorage. A `404` for an
unknown project/session, missing proxy scope, missing typed link, or a changed
source run is a failure. Stop the two servers with `Ctrl-C`; leave the unique
scratch fixture in place for inspection rather than deleting it from the
smoke procedure.

### V1.7 Agent Operations Foundation v2 checks

The navigation fixture is also the browser entrypoint for typed-operation
hardening. Record these backend facts from the manifest and visible operation
panel; do not infer them from assistant prose:

- [ ] `proposal_id → operation_record_id → execution_key` is stable after
      reload, and the operation record is authoritative for status, child run,
      diff, and verification.
- [ ] Confirm the same proposal twice (or refresh while confirmation is in
      flight). No second child run/fork is created; a concurrent duplicate
      returns the durable operation state or a fail-closed conflict.
- [ ] Use message and graph-node fork entrypoints independently. Each
      pending → confirmed → completed flow creates exactly one fork, one child
      Chain, and one child Agent session, with zero automatic child runs.
- [ ] If a local failpoint/recovery harness is used, test
      `after_claim`, `before_child_effect`, `after_child_effect`,
      `after_effect_binding`, `before_domain_commit`, `after_domain_commit`,
      and `before_terminal_reconcile`; retry with the same execution key and
      verify that durable records converge without a second effect. In the
      `after_domain_commit` case, confirm that the business effect is already
      committed and recovery only terminalizes its projection.
- [ ] Inspect the JSONL control-plane files with a deliberately incomplete
      final line. Only an unterminated final record may be ignored; a malformed
      complete line must fail closed rather than silently disappearing.
- [ ] Let a Chain lease expire, then retry the same execution key. The lease
      can be recovered by the next attempt, while a live lease owned by another
      execution key remains a stable conflict.
- [ ] Confirm two different proposals against one Chain active head do not
      both execute. The second request is a stable `409` conflict/stale result
      and leaves no second effect.
- [ ] Open `Capabilities` in the Agent composer. Executable operations,
      confirmation/risk metadata, advisory items, unsupported items, and
      examples come from `GET /api/agent/capabilities` with the fixture's exact
      `project_root`; a load failure says unavailable rather than inventing
      local labels.
- [ ] Ask for unsupported data-cleaning, arbitrary file/code/network, or
      multi-step work. The Agent states the boundary and creates no proposal,
      operation record, run, fork, or graph mutation.

### V1.7 V11 `data.column.cast` manual typed-operation smoke

This is a separate deterministic manual-UI path for the first V11 data-layer
operation. It uses the pending rerun fixture because that fixture contains a
real cleaned dataset node and a downstream model, but it does not call
DeepSeek and it never writes to a production project.

Create a fresh scratch fixture and pin both processes to this worktree:

```bash
SMOKE_ROOT="/private/tmp/wb-v17-agent-rerun-$(date +%Y%m%d-%H%M%S)"
.venv/bin/python scripts/seed_agent_rerun_smoke.py \
  --project-root "$SMOKE_ROOT" \
  | tee "/private/tmp/wb-v17-agent-rerun-seed-$(date +%Y%m%d-%H%M%S).json"
```

Start the backend from the worktree root with the checkout-local import path;
the absolute `PYTHONPATH` avoids accidentally loading an installed package
from another Workbench worktree:

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.7
env PYTHONPATH=/Users/jiayuanren/项目规划/.worktrees/workbench-v1.7/backend \
  WORKBENCH_LLM_CONFIG_PATH=/Users/jiayuanren/.config/econometrics-workbench/smoke-llm.json \
  .venv/bin/uvicorn workbench.api:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal from the same checkout:

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.7/frontend
VITE_API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev
```

Open the seeded `urls.source_graph` URL and perform the following exact
browser actions:

- [ ] Select the `Cleaned data` dataset node. The drawer shows the real
      `cleaned_dataset` artifact, row count, and a native `Existing column`
      select populated only from the backend context.
- [ ] Select an existing column, select an enum target type, and click
      `Preview cast`. Record the visible before/after dtype, converted count,
      failure count, new-missing count, and downstream rerun warning.
- [ ] Click `Confirm cast` only after the preview. Record the visible
      `Operation Record <record_id>` and `new child data node created` status.
- [ ] Reload the current graph URL. The source node remains unchanged; the
      new `Cast <column> → <dtype>` child node is visible, and affected model
      nodes show `data source changed; rerun required`.
- [ ] Re-open the source dataset node after reload. The operation result and
      source artifact context remain durable; no second confirmation or child
      artifact is created.
- [ ] Select the new cast child node. Its `Data operation` section shows the
      durable provenance block: `Created by data.column.cast`, the
      `Operation Record <record_id>` with `completed · verification passed`,
      the typed schema diff (`<column>: <before> → <after>`), the
      `exec_…` execution key, and the recipe path. This block is loaded from
      `GET /api/data-operations/column-cast/by-child-node` using the node's
      typed binding, not from operation prose or localStorage.
- [ ] On the same child node, `Ask AI` resolves a real node context (no
      `missing_node_hash`), the `Lineage path` shows
      `Raw input data → Cleaned data → Cast <column> → <dtype>`, and
      `Created` shows the real operation time. The child's Merkle identity is
      the derived artifact's content hash, written into `node_index.json` by
      the effect (legacy runs without a node index stay opaque).
- [ ] Replay the same confirm request twice more over HTTP (same
      `preview_fingerprint`). Both return the same durable
      `record_id`/artifact bindings, append no new state lines to the
      operation record, and leave exactly one derived directory. Two
      concurrent duplicate confirms converge to one record and one child. A
      bogus `preview_fingerprint` returns a stable `409 DATA_OPERATION_STALE`.

For the backend evidence, inspect the exact scratch project named by the
fixture output. The final operation record must show
`status=completed`, `effect_status=committed`, `projection_status=complete`,
`verification.passed=true`, `source_immutable=true`, and one
`data.column.cast` edge. The artifact index must retain the original source
SHA and contain one `derived_data` artifact plus its recipe metadata. This
manual path uses `actor_type=human_ui`; it is not a claim that natural-language
Agent generation for `data.column.cast` is enabled. The capability registry
currently keeps this typed operation out of the natural-language proposal
tool until the manual vertical slice is further hardened.

Record the final normalized browser URL, frontend `/api` proxy scope, visible
status strings, operation record ID, artifact ID, child node ID, and reload
result in the handoff or progress note. Stop both local servers with
`Ctrl-C`. Keep the unique scratch fixture for inspection; never use `rm -rf`
against an existing project.

### V12 `data.columns.cast` batch typed-operation smoke

Same fixture and servers as the V11 cast smoke. This exercises the batch
operation that fixes graph explosion: N columns cast in one Operation Record →
one child node. Open the seeded `urls.source_graph` and:

- [ ] Select the `Cleaned data` node. The `Data operation` section shows a
      multi-row builder: row 0 is `<column> → <dtype>` plus a `+ Add column`
      button. Column selects exclude columns already chosen in other rows.
- [ ] Set row 0 to `wage → string`, click `+ Add column`, set row 1 to
      `education → string`. The `Preview cast` button reads `Preview 2 casts`.
- [ ] Click `Preview 2 casts`. The result lists one line per column
      (`wage: int64 → string · 30 converted · 0 failures`, same for education)
      and one `Downstream models requiring rerun: model:ols_1`.
- [ ] Click `Confirm 2 casts`. Record the single `Operation Record <id>` and
      `new child data node created`.
- [ ] Reload the graph URL. There is exactly **one** new child node
      `Cast 2 columns` with summary `2 columns cast (wage→string,
      education→string)` — not two sibling nodes — and the model shows
      `data source changed; rerun required`.
- [ ] Backend evidence in the scratch project: one `data.columns.cast`
      operation record `completed / committed / complete` with
      `verification.passed=true` and `checks.columns_cast=[wage, education]`;
      exactly one `derived_data` artifact and one `data-casts:` graph node; the
      source `cleaned_dataset` SHA is unchanged; the recipe
      `schema_version=data-columns-cast.v1` lists both casts. The
      `GET /data-operations/column-cast/by-child-node` readback resolves the
      batch record and returns a `diff_ref.casts` array.

`data.columns.cast` is registered with `natural_language_enabled=False` for
now (same posture as the singular cast); it is the intended target shape for a
future NL proposal ("cast these columns to string" → one batch proposal).
