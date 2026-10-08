import { beforeEach, describe, expect, test } from "vitest";
import {
  columnSpec,
  effectiveLayout,
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
    expect(mapWidthFor("results", 1512, spec, true)).toBe(280);
    expect(mapWidthFor("lineage", 1512, spec, true)).toBe(1512 - 380 - 360);
    expect(mapWidthFor("lineage", 1512, spec, false)).toBe(1512 - 52 - 360);
    expect(mapWidthFor("lineage", 600, spec, true)).toBe(280);
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
