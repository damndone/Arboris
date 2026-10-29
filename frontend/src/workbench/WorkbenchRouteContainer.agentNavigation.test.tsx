import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../theme";
import * as api from "../api";
import { forestHeadFixture, forestNodeFixture } from "../apiFixtures";
import type { AgentNavigationRef } from "./agent/agentTypes";
import { parseWorkbenchUrl } from "./state/urlSchema";
import { WorkbenchRouteContainer } from "./WorkbenchRouteContainer";

const source: AgentNavigationRef = {
  id: "source:data", kind: "graph_node", relation: "source", label: "Recorded source", available: true,
  href: { view: "graph", run_id: "r1", forest_node_key: "n1", node_ref: "source:data" },
};

// Render a real consumer of the route's AgentSurfaceProvider. The navigation
// handler must reach the Agent, not only its sibling workspace controls.
vi.mock("../workspace/WorkbenchWorkspace", async () => {
  const { useAgentSurface } = await import("./agent/AgentSurfaceContext");
  return { WorkbenchWorkspace: () => {
    const agent = useAgentSurface();
    return <button disabled={!agent.openNavigation} onClick={() => agent.openNavigation?.(source)}>Open recorded source</button>;
  } };
});

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("Agent navigation in the real workspace route", () => {
  it.each([false, true].flatMap(legacy => [false, true].map(withKey => ({ legacy, withKey }))))(
    "opens a recorded source through the Agent (legacy=$legacy, explicit key=$withKey)", async ({ legacy, withKey }) => {
    source.href = { view: "graph", run_id: "r1", node_ref: legacy ? "n1" : "source:data",
      ...(withKey ? { forest_node_key: "n1" } : {}) };
    vi.spyOn(api, "fetchProjectForest").mockResolvedValue(legacy ? { legacy: true } as never : {
      schema_version: 2, legacy: false,
      nodes: { n1: forestNodeFixture({ id: "source:data", kind: "dataset_stage", stage: "source", node_hash: "n1", runs: ["r1"] }) },
      edges: [], heads: [forestHeadFixture({ run_id: "r1", head_node_hash: "n1", status: "completed" })],
    });
    vi.spyOn(api, "getRunGraph").mockResolvedValue({
      schema_version: 3, run_id: "r1", legacy: false,
      stats: { node_count: 1, edge_count: 0, leaf_count: 1, has_dp_count: 0 },
      nodes: { n1: { id: "n1", node_hash: null, kind: "dataset_stage", display_label: "Raw", stage: "source", summary: null,
        created_at: "", parent_stage_id: null, branch_id: "main", trust: "ok", trust_reason: null,
        archived: false, payload_ref: null, decision_points: [], annotations: [] } },
      edges: {}, branches: {},
    });
    render(<ThemeProvider><MemoryRouter initialEntries={["/?view=table"]}>
      <Location /><WorkbenchRouteContainer projectRoot="/proj" runId="r1" />
    </MemoryRouter></ThemeProvider>);
    const open = await screen.findByRole("button", { name: "Open recorded source" });
    expect(open).toBeEnabled();
    fireEvent.click(open);
    await waitFor(() => {
      const params = new URLSearchParams(screen.getByTestId("location").textContent ?? "");
      expect(params.get("run")).toBe("r1");
      expect(params.get("active")).toBe("n1");
      expect(parseWorkbenchUrl(params).view).toBe("graph");
    });
  });
});
