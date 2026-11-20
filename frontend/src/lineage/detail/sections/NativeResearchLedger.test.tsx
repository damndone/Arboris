import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { GraphViewNode } from "../../api/graphViewTypes";
import type { Outcome } from "../../../manual/manualApi";
import * as api from "../../../manual/manualApi";
import { OutcomeView } from "../../../manual/operations/OutcomeView";
import { NativeResearchResultSection } from "./NativeResearchResultSection";

vi.mock("../../../manual/manualApi", async (original) => ({
  ...await original<typeof api>(), readArtifact: vi.fn(),
}));
vi.mock("../../../workbench/ProjectRootContext", () => ({ useProjectRootOptional: () => "/project" }));
vi.mock("../../../workspace/workspaceCommands", () => ({ useWorkspaceCommands: () => null }));
vi.mock("../NodeOperationContextProvider", () => ({
  useResolvedNodeOperationContext: () => ({ ok: true, context: {
    operation_target: { owner_run_id: "saved-owner", op_node_id: "native-result:summary" },
  } }),
}));

const ledger = { type: "quant_replay_ledger", artifact_id: "quant_replay_ledger_run_step", sha256: "a".repeat(64), row_count: 269 };
const node: GraphViewNode = {
  id: "native-result:summary", nodeKey: "saved", raw: { annotations: [ledger] },
  stage: "diag", kind: "operation", title: "Portfolio replay", parentStageId: null, trust: "ok", decisions: [],
};

beforeEach(() => {
  vi.mocked(api.readArtifact).mockResolvedValue(new Response(JSON.stringify({
    result: { operation_id: "quant.replay", metrics: { final_equity: 123 } },
  }), { headers: { "Content-Type": "application/json" } }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("separates the complete ledger download from the primary saved JSON receipt", () => {
  const outcome: Outcome = {
    request_id: "request", preview_id: "preview", fingerprint: "fp", revision: 1,
    status: "completed", confirmation_required: false, operation_record_id: "record", workflow_id: "workflow",
    target: {}, expected_effect: [], risks: [], error: null,
    steps: [{ step_id: "replay", operation_id: "quant.replay", status: "completed", error: null,
      spec: {}, row_counts: {}, node_refs: [], artifact_refs: [
        { run_id: "saved-owner", artifact_id: "summary" },
        { run_id: "saved-owner", artifact_id: ledger.artifact_id },
      ] }],
  };
  render(<OutcomeView projectRoot="/project" outcome={outcome} operations={[]} busy={false}
    onConfirm={vi.fn()} onOpenRun={vi.fn()} />);
  expect(screen.getByRole("link", { name: "Download full ledger CSV" })).toHaveAttribute("href", api.artifactUrl("/project", "saved-owner", ledger.artifact_id));
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", api.artifactUrl("/project", "saved-owner", "summary"));
  expect(screen.getAllByRole("button", { name: "View saved result" })).toHaveLength(1);
});

it("reopens the full ledger using the selected result's owner and exact persisted reference", async () => {
  render(<NativeResearchResultSection node={node} />);
  const link = await screen.findByRole("link", { name: "Download full ledger CSV · 269 periods" });
  expect(link).toHaveAttribute("href", api.artifactUrl("/project", "saved-owner", ledger.artifact_id));
  expect(api.readArtifact).toHaveBeenCalledWith("/project", "saved-owner", "summary");
  expect(screen.getByRole("link", { name: "Download result JSON" })).toBeVisible();
});

it("retains old results without inventing a complete ledger", async () => {
  render(<NativeResearchResultSection node={{ ...node, raw: { annotations: [] } }} />);
  await screen.findByRole("link", { name: "Download result JSON" });
  expect(screen.queryByRole("link", { name: /Download full ledger/ })).toBeNull();
});

it("shows a malformed saved ledger reference instead of fabricating a download", async () => {
  render(<NativeResearchResultSection node={{ ...node, raw: { annotations: [{ ...ledger, row_count: "269" }] } }} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Saved ledger reference is invalid");
  expect(screen.queryByRole("link", { name: /Download full ledger/ })).toBeNull();
});
