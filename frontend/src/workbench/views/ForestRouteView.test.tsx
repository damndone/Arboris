import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ForestRouteView } from "./ForestRouteView";
import * as api from "../../api";
import type { HeadSetResponse } from "../../lineage/api/graphViewTypes";

function headset(): HeadSetResponse {
  return {
    schema_version: 4,
    legacy: false,
    nodes: {
      C: { id: "stage:cleaned", kind: "dataset_stage", display_label: "Cleaned",
        stage: "clean", trust: "ok", node_hash: "C", producing_stage: "cleaning",
        cas_ref: null, runs: ["run_a"] },
      M1: { id: "model:ols_1", kind: "model", display_label: "OLS", stage: "model",
        trust: "ok", node_hash: "M1", producing_stage: "estimation", cas_ref: null,
        runs: ["run_a"] },
    },
    edges: [{ source: "C", target: "M1" }],
    heads: [
      { run_id: "run_a", head_node_hash: "M1", from_node: null, rerun_of: null,
        rerun_reason: null, status: "completed", created_at: null },
    ],
  };
}

describe("ForestRouteView", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("loads then renders the forest canvas", async () => {
    vi.spyOn(api, "getRunGraphHeadSet").mockResolvedValue(headset());
    render(<ForestRouteView projectRoot="/p" runId="run_a" />);
    expect(screen.getByTestId("forest-loading")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("forest-route")).toBeTruthy());
    expect(screen.getByTestId("forest-node-C")).toBeTruthy();
    expect(screen.getByTestId("forest-node-M1")).toBeTruthy();
    expect(api.getRunGraphHeadSet).toHaveBeenCalledWith("/p", "run_a");
  });

  it("degrades to a notice for a legacy target", async () => {
    vi.spyOn(api, "getRunGraphHeadSet").mockResolvedValue({
      legacy: true,
      nodes: { "stage:cleaned": { id: "stage:cleaned", kind: "k", display_label: "C" } },
    } as unknown as HeadSetResponse);
    render(<ForestRouteView projectRoot="/p" runId="old" />);
    await waitFor(() => expect(screen.getByTestId("forest-legacy")).toBeTruthy());
  });

  it("shows an error state on fetch failure", async () => {
    vi.spyOn(api, "getRunGraphHeadSet").mockRejectedValue(
      new api.ApiError(422, "corrupt"),
    );
    render(<ForestRouteView projectRoot="/p" runId="bad" />);
    await waitFor(() => expect(screen.getByTestId("forest-error")).toBeTruthy());
  });
});
