// frontend/src/workbench/useGlobalShortcuts.test.tsx
//
// V1.5.3 F6 — global shortcut dispatcher behaviour.

import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { useGlobalShortcuts } from "./useGlobalShortcuts";
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
    raw: null,
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

function Harness() {
  useGlobalShortcuts();
  return <div data-testid="harness" />;
}

function mount(path: string, selectedKey: string | null) {
  const ctx: LineageContextValue = {
    model: model(),
    selectedKey,
    select: () => {},
  };
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={
            <WorkbenchStateProvider runId="r1">
              <LineageContext.Provider value={ctx}>
                <Harness />
                <textarea data-testid="editable" />
              </LineageContext.Provider>
            </WorkbenchStateProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

let writeText: ReturnType<typeof vi.fn>;
beforeEach(() => {
  writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
});
afterEach(() => {
  vi.restoreAllMocks();
});

function cmdShiftC() {
  fireEvent.keyDown(window, {
    key: "c",
    metaKey: true,
    shiftKey: true,
  });
}

describe("useGlobalShortcuts (F6)", () => {
  it("⌘⇧C copies the SELECTED node's id", () => {
    mount("/?tabs=alpha&active=alpha", "alpha");
    act(() => cmdShiftC());
    expect(writeText).toHaveBeenCalledWith("alpha");
  });

  it("acts on whichever node is selected", () => {
    mount("/?tabs=beta&active=beta", "beta");
    act(() => cmdShiftC());
    expect(writeText).toHaveBeenCalledWith("beta");
  });

  it("does nothing when no node is selected", () => {
    mount("/", null);
    act(() => cmdShiftC());
    expect(writeText).not.toHaveBeenCalled();
  });

  it("does NOT fire while typing into an editable element (F4 guard)", () => {
    const { getByTestId } = mount("/?tabs=alpha&active=alpha", "alpha");
    const ta = getByTestId("editable") as HTMLTextAreaElement;
    ta.focus();
    expect(document.activeElement).toBe(ta);
    act(() => cmdShiftC());
    expect(writeText).not.toHaveBeenCalled();
  });

  it("ignores unbound combos (plain ⌘C)", () => {
    mount("/?tabs=alpha&active=alpha", "alpha");
    act(() => {
      fireEvent.keyDown(window, { key: "c", metaKey: true });
    });
    expect(writeText).not.toHaveBeenCalled();
  });
});
