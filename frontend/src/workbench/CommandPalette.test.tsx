// frontend/src/workbench/CommandPalette.test.tsx
//
// V1.5.3 F7 — ⌘⇧P command palette behaviour. Plan §10.

import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { CommandPalette } from "./CommandPalette";
import {
  LineageContext,
  type LineageContextValue,
} from "../lineage/LineageContext";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../lineage/api/graphViewTypes";

function n(id: string): GraphViewNode {
  return {
    id,
    nodeKey: id,
    raw: { hello: "world" },
    stage: "model",
    kind: "model",
    title: id,
    parentStageId: null,
    trust: "ok",
    decisions: [],
  };
}

function model(): GraphViewModel {
  return {
    schemaVersion: 3,
    runId: "r1",
    legacy: false,
    nodes: [n("alpha"), n("beta")],
    edges: [],
    stats: { nodeCount: 2, edgeCount: 0, leafCount: 2, hasDpCount: 0 },
  };
}

let lastLocation = "";
function CaptureLocation() {
  const location = useLocation();
  lastLocation = `${location.pathname}${location.search}`;
  return null;
}

function mount(selectedKey: string | null, projectRoot: string | null = null) {
  lastLocation = "";
  const ctx: LineageContextValue = {
    model: model(),
    selectedKey,
    select: () => {},
  };
  const tabs = selectedKey ? `?tabs=${selectedKey}&active=${selectedKey}` : "/";
  return render(
    <MemoryRouter initialEntries={[tabs]}>
      <Routes>
        <Route
          path="*"
          element={
            <WorkbenchStateProvider runId="r1">
              <LineageContext.Provider value={ctx}>
                <CommandPalette projectRoot={projectRoot} />
                <CaptureLocation />
              </LineageContext.Provider>
            </WorkbenchStateProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

function cmdShiftP() {
  fireEvent.keyDown(window, { key: "p", metaKey: true, shiftKey: true });
}

let writeText: ReturnType<typeof vi.fn>;
beforeEach(() => {
  writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
});
afterEach(() => vi.restoreAllMocks());

describe("CommandPalette (F7)", () => {
  it("is hidden by default", () => {
    mount("alpha");
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });

  it("⌘⇧P opens it; Escape closes", () => {
    mount("alpha");
    act(() => cmdShiftP());
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });

  it("lists command-palette actions for the selected node", () => {
    mount("alpha");
    act(() => cmdShiftP());
    // A few read-only commands should be present.
    expect(
      screen.getByTestId("command-palette-item-copyNodeId"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("command-palette-item-copyAsJson"),
    ).toBeInTheDocument();
  });

  it("ArrowDown to copyNodeId + Enter invokes it (copies node id)", () => {
    mount("alpha");
    act(() => cmdShiftP());
    const panel = screen.getByTestId("command-palette");
    // Order: openDetail(0), pinTab(1), copyNodeId(2). Move cursor down twice.
    act(() => fireEvent.keyDown(panel, { key: "ArrowDown" }));
    act(() => fireEvent.keyDown(panel, { key: "ArrowDown" }));
    expect(
      screen.getByTestId("command-palette-item-copyNodeId"),
    ).toHaveAttribute("data-active", "true");
    act(() => fireEvent.keyDown(panel, { key: "Enter" }));
    expect(writeText).toHaveBeenCalledWith("alpha");
    // invoking closes the palette
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });

  it("click on a command invokes it", () => {
    mount("beta");
    act(() => cmdShiftP());
    fireEvent.click(screen.getByTestId("command-palette-item-copyNodeId"));
    expect(writeText).toHaveBeenCalledWith("beta");
  });

  it("disabled commands render greyed and cannot be invoked", () => {
    // v1.6.11: askAiAboutNode went live; markNeedsReview is the remaining
    // disabled placeholder (warning-layer backlog W).
    mount("alpha");
    act(() => cmdShiftP());
    const ai = screen.getByTestId("command-palette-item-markNeedsReview");
    expect(ai).toHaveAttribute("data-disabled", "true");
    expect(ai).toBeDisabled();
    fireEvent.click(ai);
    // disabled → no clipboard, palette stays open
    expect(writeText).not.toHaveBeenCalled();
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
  });

  it("Enter on a disabled command is a no-op (JS guard, not just DOM)", () => {
    // The DOM `disabled` attr blocks clicks, but keyboard Enter is
    // handled by the panel's onKeyDown — so the JS disabled guard in
    // invokeAction is what protects this path. Drive the cursor onto a
    // disabled action and press Enter.
    mount("alpha");
    act(() => cmdShiftP());
    const panel = screen.getByTestId("command-palette");
    // Move cursor down until askAiAboutNode is active (it's a disabled
    // command). Bounded loop so a regression can't hang the test.
    let active: string | null = null;
    for (let i = 0; i < 12; i++) {
      const cur = panel.querySelector('[data-active="true"]');
      active = cur?.getAttribute("data-testid") ?? null;
      if (active === "command-palette-item-markNeedsReview") break;
      act(() => fireEvent.keyDown(panel, { key: "ArrowDown" }));
    }
    expect(active).toBe("command-palette-item-markNeedsReview");
    act(() => fireEvent.keyDown(panel, { key: "Enter" }));
    // No side effect, palette stays open (disabled action didn't run).
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
  });

  it("shows empty-state hint when no node is selected", () => {
    mount(null);
    act(() => cmdShiftP());
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    expect(
      screen.getByText(/commands act on the selected node/i),
    ).toBeInTheDocument();
    // no command rows
    expect(
      screen.queryByTestId("command-palette-item-copyNodeId"),
    ).toBeNull();
  });

  it("quick-run legacy command navigates to /submit with project_root", () => {
    mount(null, "/tmp/demo project");
    act(() => cmdShiftP());
    const quickRun = screen.getByTestId("command-palette-item-quick-run-legacy");
    expect(quickRun).toHaveTextContent("快速 run(旧表单)");
    fireEvent.click(quickRun);
    expect(lastLocation).toBe("/submit?project_root=%2Ftmp%2Fdemo+project");
  });

  it("ArrowDown moves the cursor", () => {
    mount("alpha");
    act(() => cmdShiftP());
    const first = screen.getByTestId("command-palette-item-openDetail");
    expect(first).toHaveAttribute("data-active", "true");
    act(() => {
      fireEvent.keyDown(screen.getByTestId("command-palette"), {
        key: "ArrowDown",
      });
    });
    expect(first).not.toHaveAttribute("data-active", "true");
  });
});
