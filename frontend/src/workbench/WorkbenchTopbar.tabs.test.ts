import { describe, expect, it } from "vitest";
import { WORKSPACE_VIEWS } from "../workspace/WorkspaceTopbar";

describe("WorkbenchTopbar WORKSPACE_VIEWS", () => {
  it("does not offer the Pipeline tab (retired in v1.6.7)", () => {
    // Pipeline merges into the main lineage graph; Graph + Table (+ Report,
    // v1.6.11 slice C) are the clickable view tabs. The "pipeline" ViewMode +
    // PipelineView stay as a URL deep-link fallback, but the tab is no longer
    // offered. Data (v1.8.9) browses datasets and edits variable metadata.
    expect(WORKSPACE_VIEWS.map((t) => t.id)).toEqual(["home", "data", "graph", "table", "report", "plans"]);
    expect(WORKSPACE_VIEWS.map((t) => t.id)).not.toContain("pipeline");
  });
});
