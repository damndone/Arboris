// frontend/src/workbench/LineageBridge.test.tsx
//
// V1.5.3 F2/F3 — LineageBridge coverage.
//
// LineageBridge replaced useSelectedNode as the source of LineageContext.
// When useSelectedNode.ts was deleted, its 15 tests went with it — and 7
// of those covered subtle auto-select behaviour (review > caution
// priority, stable-id selection, "don't override explicit selection",
// "don't re-select after user clears", "re-arm on run scope change").
// That logic now lives in LineageBridge.tsx but had ZERO tests. This
// file recovers that coverage by mounting the REAL Provider + Bridge and
// asserting through the LineageContext the bridge produces.
//
// It also locks the two behaviours that are the whole point of F2/F3:
//   - select(null) closes the active tab (deselect)
//   - selection state is sourced from the Provider (single URL writer)

import "@testing-library/jest-dom/vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { LineageBridge } from "./LineageBridge";
import { useLineage } from "../lineage/LineageContext";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../lineage/api/graphViewTypes";

function n(
  id: string,
  overrides: Partial<GraphViewNode> = {},
): GraphViewNode {
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
    ...overrides,
  };
}

function model(
  nodes: GraphViewNode[],
  runId = "r1",
): GraphViewModel {
  return {
    schemaVersion: 3,
    runId,
    legacy: false,
    nodes,
    edges: [],
    stats: {
      nodeCount: nodes.length,
      edgeCount: 0,
      leafCount: nodes.length,
      hasDpCount: 0,
    },
  };
}

// Probe surfaces the LineageContext the bridge produces + the live URL.
interface ProbeRef {
  selectedKey: string | null;
  select: (key: string | null) => void;
  tabs: string[];
  activeTabId: string | null;
  search: string;
}
const ref: { current: ProbeRef | null } = { current: null };

function Probe() {
  const { selectedKey, select, tabs, activeTabId } = useLineage();
  const loc = useLocation();
  ref.current = {
    selectedKey,
    select,
    tabs: tabs?.map((t) => t.id) ?? [],
    activeTabId: activeTabId ?? null,
    search: loc.search,
  };
  return <div data-testid="probe">{String(selectedKey)}</div>;
}

function mount(m: GraphViewModel, initialPath = "/") {
  ref.current = null;
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="*"
          element={
            <WorkbenchStateProvider runId={m.runId}>
              <LineageBridge model={m}>
                <Probe />
              </LineageBridge>
            </WorkbenchStateProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LineageBridge — auto-select (recovered from useSelectedNode)", () => {
  it("auto-selects the first review node when no selection in URL", async () => {
    mount(
      model([
        n("a", { trust: "ok" }),
        n("b", { trust: "review" }),
        n("c", { trust: "caution" }),
      ]),
    );
    await waitFor(() => expect(ref.current!.selectedKey).toBe("b"));
    expect(ref.current!.activeTabId).toBe("b");
  });

  it("auto-selects the first caution node when no review node exists", async () => {
    mount(
      model([
        n("a", { trust: "ok" }),
        n("c", { trust: "caution" }),
      ]),
    );
    await waitFor(() => expect(ref.current!.selectedKey).toBe("c"));
  });

  it("review takes priority over caution regardless of order", async () => {
    mount(
      model([
        n("c", { trust: "caution" }),
        n("r", { trust: "review" }),
      ]),
    );
    await waitFor(() => expect(ref.current!.selectedKey).toBe("r"));
  });

  it("does NOT auto-select when every node is ok", async () => {
    mount(model([n("a"), n("b"), n("c")]));
    // Flush effects across several ticks; selection must STAY null the
    // whole time (guards against a delayed/async auto-select sneaking in
    // — a single microtask wait could pass before the effect even ran).
    for (let i = 0; i < 5; i++) await act(async () => {});
    expect(ref.current!.selectedKey).toBeNull();
    expect(ref.current!.activeTabId).toBeNull();
  });

  it("does NOT override an explicit selection from the URL", async () => {
    mount(
      model([n("a", { trust: "review" }), n("b")]),
      "/?tabs=b&active=b",
    );
    // b was explicitly active via URL; auto-select must not steal to "a".
    // Flush multiple ticks so a late auto-select would be caught.
    for (let i = 0; i < 5; i++) await act(async () => {});
    expect(ref.current!.selectedKey).toBe("b");
  });
});

describe("LineageBridge — select() semantics", () => {
  it("select(key) opens/activates a tab", async () => {
    mount(model([n("a"), n("b")]));
    act(() => ref.current!.select("a"));
    await waitFor(() => expect(ref.current!.selectedKey).toBe("a"));
    expect(ref.current!.tabs).toContain("a");
    expect(ref.current!.activeTabId).toBe("a");
  });

  it("select(null) closes the active tab (deselect)", async () => {
    mount(model([n("a"), n("b")]), "/?tabs=a&active=a");
    expect(ref.current!.selectedKey).toBe("a");
    act(() => ref.current!.select(null));
    await waitFor(() => expect(ref.current!.selectedKey).toBeNull());
    expect(ref.current!.activeTabId).toBeNull();
  });
});

describe("LineageBridge — single URL writer", () => {
  it("selection writes tabs/active to the URL via the Provider", async () => {
    mount(model([n("a"), n("b")]));
    act(() => ref.current!.select("b"));
    await waitFor(() => {
      const p = new URLSearchParams(ref.current!.search);
      expect(p.get("tabs")).toBe("b");
      expect(p.get("active")).toBe("b");
    });
  });
});
