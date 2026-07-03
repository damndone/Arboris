import { describe, expect, it } from "vitest";
import { VIEW_TABS } from "./WorkbenchTopbar";

describe("WorkbenchTopbar VIEW_TABS", () => {
  it("does not offer the Pipeline tab (retired in v1.6.7)", () => {
    // Pipeline merges into the main lineage graph; only Graph + Table remain
    // as clickable view tabs. The "pipeline" ViewMode + PipelineView stay as a
    // URL deep-link fallback, but the tab is no longer offered.
    expect(VIEW_TABS.map((t) => t.id)).toEqual(["graph", "table"]);
  });
});
