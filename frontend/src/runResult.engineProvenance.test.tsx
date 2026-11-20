import "@testing-library/jest-dom/vitest";
import {render, screen} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {RunResultView} from "./runResult";
import {fetchRunArtifacts, fetchRunDetail, type RunDetail} from "./api";

vi.mock("./api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./api")>(), fetchRunArtifacts: vi.fn(), fetchRunDetail: vi.fn(),
}));
afterEach(() => vi.clearAllMocks());

it("shows the actual engine in the reachable legacy result overview", async () => {
  vi.mocked(fetchRunArtifacts).mockResolvedValue({groups: []});
  vi.mocked(fetchRunDetail).mockResolvedValue({run_id: "owner-run", status: "completed", errors: {issues: []}, artifact_counts: {},
    model_results: [{model_id: "iv_1", model_type: "iv_2sls", coefficients: {},
      engine_provenance: {requested: "fast", used: "reference", reason: "native engine is not built"}}],
  } as unknown as RunDetail);
  render(<RunResultView projectRoot="/project" runId="owner-run" onError={() => {}}/>);
  expect(await screen.findByText("Actual engine: reference")).toBeInTheDocument();
  expect(screen.getByText("native engine is not built")).toBeInTheDocument();
});
