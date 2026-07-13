import { describe, expect, it } from "vitest";
import { VIEW_TABS } from "./WorkbenchTopbar";

describe("WorkbenchTopbar VIEW_TABS", () => {
  it("does not offer the Pipeline tab (retired in v1.6.7)", () => {
    // Pipeline merges into the main lineage graph; Graph + Table (+ Report,
    // v1.6.11 slice C) are the clickable view tabs. The "pipeline" ViewMode +
    // PipelineView stay as a URL deep-link fallback, but the tab is no longer
    // offered.
    expect(VIEW_TABS.map((t) => t.id)).toEqual(["home", "graph", "table", "report"]);
  });
});
