import { beforeEach, describe, expect, test } from "vitest";
import {
  stageIsOpen,
  columnSpec,
  effectiveLayout,
  mapPresentation,
  mapWidthFor,
  projectedPosition,
  readAgentOpen,
  readLayout,
  releaseLayout,
  writeAgentOpen,
  writeLayout,
} from "./layoutModel";

describe("column widths", () => {
  test("a 14-inch MacBook Pro gets the full columns", () => {
    expect(columnSpec(1512)).toEqual({ map: 280, inspector: 360, agent: 380, rail: 52 });
    expect(columnSpec(1280)).toEqual({ map: 240, inspector: 320, agent: 340, rail: 52 });
  });

  test("results first keeps a map column; lineage first gives the map what the inspector and Agent leave", () => {
    const spec = columnSpec(1512);
    const open = { layout: "results" as const, stageOpen: true, mapHidden: false, agentOpen: true };
    expect(mapWidthFor(open, 1512, spec)).toBe(280);
    expect(mapWidthFor({ ...open, mapHidden: true }, 1512, spec)).toBe(0);
    expect(mapWidthFor({ ...open, layout: "lineage" }, 1512, spec)).toBe(1512 - 380 - 360);
    expect(mapWidthFor({ ...open, layout: "lineage", agentOpen: false }, 1512, spec)).toBe(1512 - 52 - 360);
    expect(mapWidthFor({ ...open, layout: "lineage" }, 600, spec)).toBe(280);
  });

  test("with the stage closed the map takes the whole width, as the full graph", () => {
    const spec = columnSpec(1512);
    const closed = { layout: "results" as const, stageOpen: false, mapHidden: false, agentOpen: true };
    expect(mapWidthFor(closed, 1512, spec)).toBe(1512 - 380);
    expect(mapPresentation(closed)).toBe("graph");
    expect(mapPresentation({ ...closed, stageOpen: true })).toBe("tree");
    expect(mapPresentation({ ...closed, stageOpen: true, mapHidden: true })).toBe("none");
    expect(mapPresentation({ ...closed, stageOpen: true, layout: "lineage" })).toBe("graph");
  });
});

describe("releasing the divider", () => {
  const detents = { results: 280, lineage: 772 };

  test("a slow release lands on the nearer detent", () => {
    expect(releaseLayout(500, 0, detents)).toBe("results");
    expect(releaseLayout(560, 0, detents)).toBe("lineage");
  });

  test("a flick carries past the midpoint (momentum projection)", () => {
    expect(projectedPosition(400, 0.5)).toBeCloseTo(400 + 249.5, 5);
    expect(releaseLayout(400, 0.5, detents)).toBe("lineage");
    expect(releaseLayout(650, -0.6, detents)).toBe("results");
  });
});

describe("wide views and memory", () => {
  beforeEach(() => localStorage.clear());

  test("Data, Tables, Report and Plans borrow the wide stage in lineage first", () => {
    expect(effectiveLayout("lineage", "data")).toBe("results");
    expect(effectiveLayout("lineage", "notebook")).toBe("results");
    expect(effectiveLayout("lineage", "graph")).toBe("lineage");
    expect(effectiveLayout("results", "report")).toBe("results");
  });

  test("each project remembers its own layout; results first is the default", () => {
    expect(readLayout("/a")).toBe("results");
    writeLayout("/a", "lineage");
    expect(readLayout("/a")).toBe("lineage");
    expect(readLayout("/b")).toBe("results");
  });

  test("the Agent column starts open and remembers being folded", () => {
    expect(readAgentOpen()).toBe(true);
    writeAgentOpen(false);
    expect(readAgentOpen()).toBe(false);
  });
});

describe("stageIsOpen", () => {
  test("Analyze and document views always show the stage; Analysis only with an open, unfolded step", () => {
    const base = { analyzing: false, analysisView: true, hasOpenItem: false, folded: false };
    expect(stageIsOpen(base)).toBe(false);
    expect(stageIsOpen({ ...base, hasOpenItem: true })).toBe(true);
    expect(stageIsOpen({ ...base, hasOpenItem: true, folded: true })).toBe(false);
    expect(stageIsOpen({ ...base, analyzing: true })).toBe(true);
    expect(stageIsOpen({ ...base, analysisView: false })).toBe(true);
  });
});
