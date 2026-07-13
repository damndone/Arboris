// frontend/src/workbench/state/urlSchema.test.ts
//
// V1.5.2 P2 — Tier 1 URL contract tests. Plan §6.
//
// Each Tier-1 param gets round-trip coverage: parse → state → write →
// parse must equal the starting state. Default/empty values must NOT
// appear in the written URL (URL minimisation rule).

import { describe, expect, it } from "vitest";
import {
  defaultUrlSlice,
  parseWorkbenchUrl,
  writeWorkbenchUrl,
  type WorkbenchUrlSlice,
} from "./urlSchema";

function p(qs: string): URLSearchParams {
  return new URLSearchParams(qs);
}

function roundTrip(slice: WorkbenchUrlSlice): WorkbenchUrlSlice {
  const written = writeWorkbenchUrl(new URLSearchParams(), slice);
  return parseWorkbenchUrl(written);
}

describe("parseWorkbenchUrl", () => {
  it("returns defaults for empty params", () => {
    expect(parseWorkbenchUrl(p(""))).toEqual(defaultUrlSlice);
  });

  it("parses view enum", () => {
    expect(parseWorkbenchUrl(p("view=home")).view).toBe("home");
    expect(parseWorkbenchUrl(p("view=table")).view).toBe("table");
    expect(parseWorkbenchUrl(p("view=pipeline")).view).toBe("pipeline");
  });

  it("ignores unknown view values (graceful default)", () => {
    expect(parseWorkbenchUrl(p("view=garbage")).view).toBe("graph");
  });

  it("parses q (empty string when absent, string when present)", () => {
    expect(parseWorkbenchUrl(p("")).searchQuery).toBe("");
    expect(parseWorkbenchUrl(p("q=income")).searchQuery).toBe("income");
  });

  it("parses panel id and ignores legacy panelOpen", () => {
    const s = parseWorkbenchUrl(p("panel=ai&panelOpen=1"));
    expect(s.bottomPanel).toBe("ai");
  });

  it("ignores unknown panel ids", () => {
    expect(parseWorkbenchUrl(p("panel=bogus")).bottomPanel).toBe("logs");
  });

  it("parses focus + pinned together", () => {
    const s = parseWorkbenchUrl(p("focus=nodeA&pinned=1"));
    expect(s.focusKey).toBe("nodeA");
    expect(s.pinned).toBe(true);
  });

  it("collapses pinned=1 without focus to pinned=0", () => {
    expect(parseWorkbenchUrl(p("pinned=1")).pinned).toBe(false);
  });

  it("drops focus when validNodeKeys is supplied and key is unknown", () => {
    const s = parseWorkbenchUrl(
      p("focus=ghost&pinned=1"),
      new Set(["real"]),
    );
    expect(s.focusKey).toBeNull();
    expect(s.pinned).toBe(false);
  });

  it("keeps focus when validNodeKeys includes it", () => {
    const s = parseWorkbenchUrl(
      p("focus=real&pinned=1"),
      new Set(["real"]),
    );
    expect(s.focusKey).toBe("real");
    expect(s.pinned).toBe(true);
  });

  it("skips validation when validNodeKeys is undefined (loading state)", () => {
    const s = parseWorkbenchUrl(p("focus=anything"));
    expect(s.focusKey).toBe("anything");
  });
});

describe("writeWorkbenchUrl", () => {
  it("strips all workbench params when slice equals defaults", () => {
    const out = writeWorkbenchUrl(new URLSearchParams(), defaultUrlSlice);
    expect(out.toString()).toBe("");
  });

  it("preserves unrelated params verbatim", () => {
    const out = writeWorkbenchUrl(
      p("project_root=/foo&tab=lineage&tabs=a,b&active=b"),
      defaultUrlSlice,
    );
    // tabs/active belong to useTabs, project_root/tab to outer chrome —
    // none should be touched by the workbench URL writer.
    expect(out.get("project_root")).toBe("/foo");
    expect(out.get("tab")).toBe("lineage");
    expect(out.get("tabs")).toBe("a,b");
    expect(out.get("active")).toBe("b");
  });

  it("writes view only when non-default", () => {
    const out = writeWorkbenchUrl(new URLSearchParams(), {
      ...defaultUrlSlice,
      view: "table",
    });
    expect(out.get("view")).toBe("table");
  });

  it("writes panel id when panel is non-default and strips legacy panelOpen", () => {
    const out = writeWorkbenchUrl(new URLSearchParams(), {
      ...defaultUrlSlice,
      bottomPanel: "ai",
    });
    expect(out.get("panel")).toBe("ai");
    expect(out.get("panelOpen")).toBeNull();
  });

  it("strips stale legacy panelOpen even when preserving unrelated params", () => {
    const out = writeWorkbenchUrl(
      p("project_root=/foo&panelOpen=1"),
      defaultUrlSlice,
    );
    expect(out.get("project_root")).toBe("/foo");
    expect(out.get("panelOpen")).toBeNull();
  });

  it("strips pinned when focus is null", () => {
    const out = writeWorkbenchUrl(new URLSearchParams(), {
      ...defaultUrlSlice,
      focusKey: null,
      pinned: true, // caller-passed garbage; writer normalises
    });
    expect(out.get("focus")).toBeNull();
    expect(out.get("pinned")).toBeNull();
  });
});

describe("round-trip (parse → write → parse)", () => {
  const cases: Array<[string, WorkbenchUrlSlice]> = [
    ["all defaults", defaultUrlSlice],
    [
      "table view + focus pinned + search",
      {
        view: "table",
        searchQuery: "income",
        bottomPanel: "ai",
        focusKey: "n42",
        pinned: true,
      },
    ],
    [
      "pipeline + focus unpinned + no search",
      {
        view: "pipeline",
        searchQuery: "",
        bottomPanel: "logs",
        focusKey: "n9",
        pinned: false,
      },
    ],
    [
      "home view round-trips",
      {
        view: "home",
        searchQuery: "",
        bottomPanel: "logs",
        focusKey: null,
        pinned: false,
      },
    ],
  ];

  it.each(cases)("%s", (_label, slice) => {
    expect(roundTrip(slice)).toEqual(slice);
  });
});
