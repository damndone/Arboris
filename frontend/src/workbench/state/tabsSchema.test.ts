// frontend/src/workbench/state/tabsSchema.test.ts
//
// V1.5.2 P2 — pure reducer tests. Asserts the parse / write / reduce
// functions agree with useTabs's behaviour (V1.5.1 useTabs.test.tsx
// is the authoritative integration spec; this file is the unit spec).

import { describe, expect, it } from "vitest";
import {
  MAX_TABS,
  nodeTabOf,
  parseTabsParams,
  REPORT_REVIEW_TAB_ID,
  reduceCloseTab,
  reduceOpenTab,
  reduceSetActive,
  writeTabsParams,
  type TabsSlice,
} from "./tabsSchema";

function p(qs: string): URLSearchParams {
  return new URLSearchParams(qs);
}

describe("parseTabsParams", () => {
  it("returns empty for bare URL", () => {
    expect(parseTabsParams(p(""))).toEqual({ tabs: [], activeTabId: null });
  });

  it("parses tabs + active", () => {
    const s = parseTabsParams(p("tabs=a,b,c&active=b"));
    expect(s.tabs.map((t) => t.id)).toEqual(["a", "b", "c"]);
    expect(s.activeTabId).toBe("b");
  });

  it("parses report:review as a non-node workspace tab", () => {
    const s = parseTabsParams(
      p("tabs=node:a,report:review&active=report:review"),
    );
    const reportTab = s.tabs.find((tab) => tab.id === "report:review");

    expect(reportTab?.kind).toBe("report-review");
    expect(reportTab).not.toHaveProperty("nodeKey");
    expect(s.activeTabId).toBe("report:review");
  });

  it("defaults active to last tab when active param is missing/invalid", () => {
    expect(parseTabsParams(p("tabs=a,b")).activeTabId).toBe("b");
    expect(parseTabsParams(p("tabs=a,b&active=ghost")).activeTabId).toBe(
      "b",
    );
  });

  it("dedupes and caps at MAX_TABS", () => {
    const ids = Array.from({ length: 12 }, (_, i) => `n${i}`).join(",");
    const s = parseTabsParams(p(`tabs=${ids}`));
    expect(s.tabs).toHaveLength(MAX_TABS);
    expect(s.tabs.map((t) => t.id)).toEqual([
      "n0",
      "n1",
      "n2",
      "n3",
      "n4",
      "n5",
      "n6",
      "n7",
    ]);
  });

  it("migrates legacy ?node= to single tab", () => {
    const s = parseTabsParams(p("node=legacy"));
    expect(s.tabs.map((t) => t.id)).toEqual(["legacy"]);
    expect(s.activeTabId).toBe("legacy");
  });
});

describe("writeTabsParams", () => {
  it("preserves unrelated params and deletes legacy node", () => {
    const out = writeTabsParams(p("project_root=/x&node=old&view=table"), {
      tabs: [nodeTabOf("a", 1)],
      activeTabId: "a",
    });
    expect(out.get("project_root")).toBe("/x");
    expect(out.get("view")).toBe("table");
    expect(out.get("node")).toBeNull();
    expect(out.get("tabs")).toBe("a");
    expect(out.get("active")).toBe("a");
  });

  it("strips tabs/active when slice is empty", () => {
    const out = writeTabsParams(p("tabs=a,b&active=b"), {
      tabs: [],
      activeTabId: null,
    });
    expect(out.get("tabs")).toBeNull();
    expect(out.get("active")).toBeNull();
  });
});

describe("reduceOpenTab", () => {
  const empty: TabsSlice = { tabs: [], activeTabId: null };

  it("adds the first tab and makes it active", () => {
    const { next, evicted, nextClock } = reduceOpenTab(empty, 0, "a");
    expect(next.tabs.map((t) => t.id)).toEqual(["a"]);
    expect(next.activeTabId).toBe("a");
    expect(evicted).toBeNull();
    expect(nextClock).toBe(1);
  });

  it("focuses an existing tab without re-adding", () => {
    const prev: TabsSlice = {
      tabs: [
        nodeTabOf("a", 1),
        nodeTabOf("b", 2),
      ],
      activeTabId: "a",
    };
    const { next, evicted, nextClock } = reduceOpenTab(prev, 5, "b");
    expect(next.tabs).toHaveLength(2);
    expect(next.activeTabId).toBe("b");
    expect(evicted).toBeNull();
    expect(nextClock).toBe(5); // clock unchanged for re-focus
  });

  it("returns prev unchanged when re-opening the already-active tab", () => {
    const prev: TabsSlice = {
      tabs: [nodeTabOf("a", 1)],
      activeTabId: "a",
    };
    const { next } = reduceOpenTab(prev, 5, "a");
    expect(next).toBe(prev); // referentially identical
  });

  it("evicts the LRU tab when at MAX_TABS", () => {
    const tabs = Array.from({ length: MAX_TABS }, (_, i) => ({
      ...nodeTabOf(`n${i}`, i + 1),
    }));
    const prev: TabsSlice = { tabs, activeTabId: "n7" };
    const { next, evicted } = reduceOpenTab(prev, MAX_TABS, "newkid");
    expect(evicted).toBe("n0"); // oldest by openedAt
    expect(next.tabs.map((t) => t.id)).toContain("newkid");
    expect(next.tabs.map((t) => t.id)).not.toContain("n0");
    expect(next.activeTabId).toBe("newkid");
  });

  it("keeps Report review outside the node LRU capacity", () => {
    const prev: TabsSlice = {
      tabs: [
        { kind: "report-review", id: REPORT_REVIEW_TAB_ID, openedAt: 1 },
        ...Array.from({ length: MAX_TABS }, (_, i) =>
          nodeTabOf(`n${i}`, i + 2),
        ),
      ],
      activeTabId: "n7",
    };

    const { next, evicted } = reduceOpenTab(prev, MAX_TABS + 1, "newkid");

    expect(evicted).toBe("n0");
    expect(next.tabs.some((tab) => tab.id === REPORT_REVIEW_TAB_ID)).toBe(true);
    expect(next.tabs.filter((tab) => tab.kind === "node")).toHaveLength(
      MAX_TABS,
    );
  });
});

describe("reduceCloseTab", () => {
  it("returns prev when tab id is unknown", () => {
    const prev: TabsSlice = {
      tabs: [nodeTabOf("a", 1)],
      activeTabId: "a",
    };
    expect(reduceCloseTab(prev, "ghost")).toBe(prev);
  });

  it("does not close the permanent Report review tab", () => {
    const prev: TabsSlice = {
      tabs: [
        nodeTabOf("a", 1),
        { kind: "report-review", id: REPORT_REVIEW_TAB_ID, openedAt: 2 },
      ],
      activeTabId: REPORT_REVIEW_TAB_ID,
    };

    expect(reduceCloseTab(prev, REPORT_REVIEW_TAB_ID)).toBe(prev);
  });

  it("promotes the right-neighbour when closing the active tab", () => {
    const prev: TabsSlice = {
      tabs: [
        nodeTabOf("a", 1),
        nodeTabOf("b", 2),
        nodeTabOf("c", 3),
      ],
      activeTabId: "b",
    };
    const next = reduceCloseTab(prev, "b");
    expect(next.tabs.map((t) => t.id)).toEqual(["a", "c"]);
    expect(next.activeTabId).toBe("c");
  });

  it("falls back to the left-neighbour when active was last tab", () => {
    const prev: TabsSlice = {
      tabs: [
        nodeTabOf("a", 1),
        nodeTabOf("b", 2),
      ],
      activeTabId: "b",
    };
    expect(reduceCloseTab(prev, "b").activeTabId).toBe("a");
  });

  it("nulls active when closing the last tab", () => {
    const prev: TabsSlice = {
      tabs: [nodeTabOf("a", 1)],
      activeTabId: "a",
    };
    expect(reduceCloseTab(prev, "a").activeTabId).toBeNull();
  });

  it("does not touch active when closing a non-active tab", () => {
    const prev: TabsSlice = {
      tabs: [
        nodeTabOf("a", 1),
        nodeTabOf("b", 2),
      ],
      activeTabId: "b",
    };
    expect(reduceCloseTab(prev, "a").activeTabId).toBe("b");
  });
});

describe("reduceSetActive", () => {
  const prev: TabsSlice = {
    tabs: [
      nodeTabOf("a", 1),
      nodeTabOf("b", 2),
    ],
    activeTabId: "a",
  };

  it("switches active to known tab id", () => {
    expect(reduceSetActive(prev, "b").activeTabId).toBe("b");
  });

  it("returns prev when id is unknown", () => {
    expect(reduceSetActive(prev, "ghost")).toBe(prev);
  });

  it("returns prev when id is already active (no-op)", () => {
    expect(reduceSetActive(prev, "a")).toBe(prev);
  });
});
