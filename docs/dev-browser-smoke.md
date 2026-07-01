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
rm -rf /tmp/wb-smoke && \
  .venv/bin/workbench create /tmp wb-smoke && \
  .venv/bin/workbench run /tmp/wb-smoke \
    examples/datasets/cross_section.csv wage \
    --x education --x experience --x region
```

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
