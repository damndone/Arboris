import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GenesisWizard } from "./GenesisWizard";
import * as api from "../../api";

vi.mock("../../capabilities/useCapabilities", () => ({
  useCapabilities: () => ({
    data: {
      schema_version: 1,
      model_types: [
        { key: "auto", label: "Auto", group: "auto" },
        { key: "ols", label: "OLS", group: "Linear" },
      ],
      imputation_methods: [],
      covariance_options: [{ key: "robust", label: "Robust" }],
    },
  }),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const sha = "a".repeat(64);

function preview(): api.FilePreview {
  return {
    fileName: "data.csv",
    sheetNames: ["Sheet1"],
    selectedSheet: "Sheet1",
    rowCount: 3,
    columnCount: 2,
    columns: [
      { name: "y", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "y" },
      { name: "x", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
    ],
    previewRows: [{ y: 1, x: 2 }],
    suggestedY: "y",
    suggestedX: ["x"],
    excludedColumns: [],
  };
}

function draftResponse(
  draftHash: string,
  tableStatus: "pending" | "configured" = "pending",
  modelStatus: "pending" | "configured" = "pending",
): api.PipelineDraftResponse {
  return {
    draft_hash: draftHash,
    draft: {
      draft_id: "draft_g1",
      schema_version: "pipeline_draft.v1",
      created_at: "t",
      updated_at: "t",
      status: "draft",
      created_from: {
        source_type: "genesis",
        source_input_fingerprint: sha,
      },
      graph: {
        nodes: [
          {
            node_id: "source_1",
            node_type: "input.upload",
            upload: { sha256: sha, filename: "data.csv" },
            sheet_names: ["Sheet1"],
            columns: ["y", "x"],
            status: "bound",
          },
          {
            node_id: "table_1",
            node_type: "table",
            params: { sheet_name: "Sheet1", transpose: false },
            columns: ["y", "x"],
            status: tableStatus,
          },
          {
            node_id: "model_1",
            node_type: "model",
            model_type: modelStatus === "configured" ? "ols" : undefined,
            params:
              modelStatus === "configured"
                ? { model_type: "ols", y: "y", x: ["x"] }
                : {},
            status: modelStatus,
          },
        ],
        edges: [
          { from: "source_1", to: "table_1" },
          { from: "table_1", to: "model_1" },
        ],
      },
      default_execution_mode: "genesis",
    },
  };
}

describe("GenesisWizard", () => {
  it("creates a genesis draft, patches table/model nodes, then validates and executes as genesis", async () => {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(preview());
    vi.spyOn(api, "uploadDataset").mockResolvedValue({
      sha256: sha,
      filename: "data.csv",
    });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(draftResponse("h2", "configured", "pending"))
      .mockResolvedValueOnce(draftResponse("h3", "configured", "configured"));
    vi.spyOn(api, "validatePipelineDraft").mockResolvedValue({
      ok: true,
      status: "valid",
      executable: true,
      checks: [],
      resolved_execution: {
        execution_mode: "genesis",
        genesis: true,
      } as never,
      validated_execution_mode: "genesis",
      validated_draft_hash: "vh1",
      validated_at: "t",
    });
    const executeResult = {
      ok: true,
      run_id: "run_first",
      draft_id: "draft_g1",
      executed_draft_hash: "eh1",
      execution_mode: "genesis",
      produced_lineage: { genesis: true },
      focus: {
        status: "pending_index",
        run_id: "run_first",
        poll: { genesis: true },
      },
    } as api.DraftExecutionResult;
    vi.spyOn(api, "executePipelineDraft").mockResolvedValue(executeResult);
    const onDraftUpdated = vi.fn();
    const onDraftValidated = vi.fn();
    const onDraftExecuting = vi.fn();
    const onDraftExecuted = vi.fn();

    render(
      <GenesisWizard
        projectRoot="/proj"
        onClose={() => {}}
        onDraftUpdated={onDraftUpdated}
        onDraftValidated={onDraftValidated}
        onDraftExecuting={onDraftExecuting}
        onDraftExecuted={onDraftExecuted}
      />,
    );

    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x\n1,2"], "data.csv", { type: "text/csv" })] },
    });

    await waitFor(() =>
      expect(api.createGenesisDraft).toHaveBeenCalledWith("/proj", {
        upload_sha256: sha,
        filename: "data.csv",
        sheet_names: ["Sheet1"],
        columns: ["y", "x"],
      }),
    );
    expect(onDraftUpdated).toHaveBeenCalledWith(draftResponse("h1"));
    expect(screen.getByLabelText("dependent variable")).toHaveValue("y");
    expect(screen.getByLabelText("independent variables")).toHaveValue("x");

    fireEvent.click(screen.getByTestId("genesis-save-table"));
    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(1, "/proj", "draft_g1", "table_1", {
        params: { sheet_name: "Sheet1", transpose: false },
        columns: ["y", "x"],
      }),
    );

    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "ols" },
    });
    fireEvent.click(screen.getByTestId("genesis-save-model"));
    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(2, "/proj", "draft_g1", "model_1", {
        params: { model_type: "ols", y: "y", x: ["x"] },
      }),
    );

    fireEvent.click(screen.getByTestId("genesis-run"));
    await waitFor(() =>
      expect(api.validatePipelineDraft).toHaveBeenCalledWith(
        "/proj",
        "draft_g1",
        "genesis",
      ),
    );
    expect(api.executePipelineDraft).toHaveBeenCalledWith("/proj", "draft_g1", {
      validated_draft_hash: "vh1",
      execution_mode: "genesis",
    });
    expect(onDraftValidated).toHaveBeenCalledWith("draft_g1", expect.any(Object));
    expect(onDraftExecuting).toHaveBeenCalledWith("draft_g1");
    expect(onDraftExecuted).toHaveBeenCalledWith(executeResult, "draft_g1");
  });
});
