# Node Panel Window Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make node detail tabs use the same compact Float/Pin/Collapse window controls as Report review while preserving the existing Actions and close controls, with state that survives view changes.

**Architecture:** Extract the report window-control buttons and SVG icons into a reusable presentational component. Keep the left run-version row outside this change. Store node-panel layout state in the Workbench shell beside report-review state, render a floating node drawer through a portal, and pass controls into the existing DetailHeader/DetailDrawer rather than creating a second node implementation.

**Tech Stack:** React, TypeScript, Vitest/Testing Library, existing Workbench PanelHost, CSS custom properties, browser-based local acceptance.

---

### Task 1: Create the shared window-control primitive

**Files:**
- Create: `frontend/src/workbench/PanelWindowControls.tsx`
- Create: `frontend/src/workbench/PanelWindowControls.test.tsx`
- Create: `frontend/src/workbench/panelWindowControls.css`
- Modify: `frontend/src/report/ReportReviewPanel.tsx`
- Modify: `frontend/src/report/report.css`

- [ ] **Step 1: Write the failing shared-control tests**

Test the component with `floating=false`, `pinned=false`, and `collapsed=false`; assert the three buttons expose `Float <surface>`, `Pin <surface>`, and `Collapse <surface>`, and assert their `data-icon` values are `float`, `pin`, and `collapse-right`. Test the floating/pinned/collapsed state similarly expects `Dock`, `Unpin`, and `Expand`, with `dock`, `pin`, and `collapse-left`. Click each button and assert its callback is called exactly once.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd frontend && npm exec vitest run src/workbench/PanelWindowControls.test.tsx`

Expected: FAIL because the shared component does not exist.

- [ ] **Step 3: Implement the shared component and styles**

Define `PanelWindowControlsProps` with `surface`, `floating`, `pinned`, `collapsed`, and the six optional transition callbacks. Render a `div` with an accessible group label and only the applicable action for each state. Reuse the report SVG geometry under a local `PanelWindowIcon` function. Give every button the same 27px square, 7px radius, zero padding, 2px group gap, hover/focus treatment, and active-pin tint currently used by Report review. Put these rules in `panelWindowControls.css` so node and report share one source of truth.

- [ ] **Step 4: Replace Report review’s local controls**

Remove the duplicate `ReportReviewIcon` window-control rendering from `ReportReviewPanel.tsx`, render `PanelWindowControls surface="report review"` in the same header location, and keep the existing drag handle and callbacks. Preserve the existing aria labels and `data-icon` contracts so current report tests remain valid. Remove only the now-unused report-specific window-button CSS.

- [ ] **Step 5: Run focused shared and report tests**

Run: `cd frontend && npm exec vitest run src/workbench/PanelWindowControls.test.tsx src/report/ReportReviewPanel.test.tsx`

Expected: PASS.

### Task 2: Add node-header control injection without changing left-side version styling

**Files:**
- Modify: `frontend/src/lineage/header/DetailHeader.tsx`
- Modify: `frontend/src/lineage/header/DetailHeader.test.tsx`
- Modify: `frontend/src/lineage/detail/DetailDrawer.tsx`
- Modify: `frontend/src/lineage/detail/DetailDrawer.test.tsx`

- [ ] **Step 1: Write failing header/drawer tests**

Render `DetailHeader` with a test `windowControls` element and an `onShowJson` callback; assert the controls, Actions button, and Close button all remain present. Render `DetailDrawer` with the same injected control and assert it is forwarded into the header. Render the drawer with `collapsed` and assert the header remains visible while the regular detail sections are not rendered.

- [ ] **Step 2: Run focused tests and verify the new assertions fail**

Run: `cd frontend && npm exec vitest run src/lineage/header/DetailHeader.test.tsx src/lineage/detail/DetailDrawer.test.tsx`

Expected: the new assertions fail because the props are not defined or forwarded.

- [ ] **Step 3: Add explicit injection props**

Add `windowControls?: ReactNode` and `collapsed?: boolean` to the existing props. In the DetailHeader toolbar, place `windowControls` before the existing NodeActionMenu and close button, preserving the current Actions and close semantics. In DetailDrawer, pass the element to DetailHeader and skip the body sections only when `collapsed === true`; do not alter the default behavior for existing callers.

- [ ] **Step 4: Run the focused tests**

Run: `cd frontend && npm exec vitest run src/lineage/header/DetailHeader.test.tsx src/lineage/detail/DetailDrawer.test.tsx`

Expected: PASS.

### Task 3: Generalize Workbench node-panel layout state and floating portal

**Files:**
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`
- Modify: `frontend/src/workbench/PanelHost.tsx`
- Modify: `frontend/src/lineage/detail/DetailDrawerTabs.tsx` (only if the floating surface needs an explicit compact wrapper class)
- Modify: `frontend/src/report/report.css` or create a focused node-panel stylesheet if the existing floating shell cannot be shared without changing Report review

- [ ] **Step 1: Add failing Workbench interaction coverage**

Extend the existing Workbench fixture test to select a node, assert the node header exposes Float node panel, Pin node panel, and Collapse node panel, click Float, and assert a `data-testid="node-panel-floating"` portal is present. Assert Actions and Close remain. Click Pin and assert the floating node surface has `data-pinned="true"`; click Collapse and assert the detail body is hidden while Expand node panel is available. Assert the docked report-review controls still work in the same test file.

- [ ] **Step 2: Run the focused Workbench test and verify it fails**

Run: `cd frontend && npm exec vitest run src/workbench/WorkbenchRouteContainer.test.tsx`

Expected: FAIL because node controls and the floating node portal are not implemented.

- [ ] **Step 3: Define reusable panel state and persistence**

Add a local `PanelLayout = "docked" | "floating"`, `PanelPosition = { x: number; y: number }`, and `PanelUiState` type shared by report/node state. Add a project-scoped node-panel storage key and a safe default matching Report review. Read/write only the node-panel key; do not change the report key or left version state.

- [ ] **Step 4: Add node-panel transitions**

Implement `floatNodePanel`, `dockNodePanel`, `pinNodePanel`, `unpinNodePanel`, and the same pointer/keyboard drag lifecycle used by Report review. Use a fixed width and viewport-clamped position. A floating node panel may remain visible while switching Notebook/Graph/Table/Report; docking returns it to the right PanelHost. Collapse in floating mode hides the detail body but keeps the node tabs and header controls visible.

- [ ] **Step 5: Wire node controls into DetailDrawer**

Construct `PanelWindowControls surface="node panel"` in WorkbenchRouteContainer and pass it as `windowControls` to the selected node’s DetailDrawer. Keep `onShowJson`, `onClose`, and the existing `Actions` menu unchanged. Do not modify `.wb-run-version-picker` or any global left-side version-row CSS.

- [ ] **Step 6: Render the floating node portal and route docked state**

Render a portal wrapper with `data-testid="node-panel-floating"`, `data-floating="true"`, `data-pinned`, and the same drag/resize visual language as Report review. Include `DetailDrawerTabs` inside the floating surface so node tabs remain available. Pass the node drawer to PanelHost only when its layout is docked; otherwise pass `null`. Update PanelHost’s `activeKind`, `collapsed`, and `onCollapsedChange` selection so the correct report or node state controls the docked shell.

- [ ] **Step 7: Run the focused Workbench interaction tests**

Run: `cd frontend && npm exec vitest run src/workbench/WorkbenchRouteContainer.test.tsx src/workbench/PanelHost.test.tsx src/lineage/detail/DetailDrawerTabs.test.tsx`

Expected: PASS.

### Task 4: Explain and verify the existing Rerun action

**Files:**
- Modify: `frontend/src/workbench/WorkbenchTopbar.test.tsx` only if a missing assertion is found
- Modify: `frontend/src/workbench/registry/actionRegistry.ts` only if the current accessible label or help text is insufficient

- [ ] **Step 1: Verify current action semantics**

Trace the topbar registry entry and its dispatch path. Confirm that Rerun opens the selected/first model node’s detail panel and does not submit a rerun until the user edits/confirms the Operation section. Confirm the resulting API path creates a child run rather than mutating the current run.

- [ ] **Step 2: Add a regression assertion if needed**

If the existing test suite does not prove the action opens the node detail, add one test that clicks `Rerun` and asserts the selected node detail is opened. Do not change backend rerun semantics.

- [ ] **Step 3: Run the topbar test**

Run: `cd frontend && npm exec vitest run src/workbench/WorkbenchTopbar.test.tsx`

Expected: PASS.

### Task 5: Browser acceptance and regression verification

**Files:**
- No source changes unless browser acceptance identifies a concrete defect.

- [ ] **Step 1: Check the source diff boundary**

Run: `git diff -- frontend/src/styles.css frontend/src/lineage/tokens/lineage.css`

Expected: no new change to the left `.wb-run-version-picker` rule; any right-panel alignment rule remains scoped under `.panel-host-tabs`.

- [ ] **Step 2: Run frontend verification**

Run: `cd frontend && npm exec vitest run`, then `cd frontend && npm run typecheck`, then `git diff --check`.

Expected: all Vitest tests pass, TypeScript exits 0, and diff check is clean.

- [ ] **Step 3: Perform native browser acceptance**

Claim the current user Workbench tab. On a node tab, verify the header has equal-sized Float/Pin/Collapse icon controls plus Actions and Close. Verify Float creates the floating node surface, Pin changes the pinned state, Collapse hides the body and Expand restores it, and switching views does not remove the floating surface. Dock it again and verify Report review still has the same controls. Capture DOM/screenshot evidence of the node and report states.

- [ ] **Step 4: Verify formal development-line status**

Run: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --all`.

Expected: all formal line checks pass. Append a material event through `scripts/devline_control.py append` if implementation or browser verification produces a failure/gap; never edit `.agent/devlines` files manually.
