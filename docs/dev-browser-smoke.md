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
| AppShell header + Submit/History/Overview/Lineage tabs render against a light page background instead of full-bleed dark editorial | P1 — outer-chrome theming patch tracked separately |
| Left rail (stage navigation with counts) | Deferred to V1.5.1 |
| Top-row workspace breadcrumb / search-K / rerun / generate-report buttons | Deferred to V1.5.1+ |
| Bottom terminal panel | Deferred to V1.5.1+ |
| Drawer header uses flat text path instead of breadcrumb chip path | Cosmetic, deferred |
| Trust banner has no inline action buttons (查看产物 / 回滚 / 标记为坏决策) | Deferred — rerun + AI are V1.5.1+ features |

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
