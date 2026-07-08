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
        { key: "panel_ols", label: "Panel OLS", group: "Panel" },
        { key: "iv_2sls", label: "IV / 2SLS", group: "IV" },
        { key: "dcdh", label: "DCDH DID", group: "DID" },
      ],
      imputation_methods: [],
      covariance_options: [{ key: "robust", label: "Robust" }],
      prediction_models: [{ key: "prediction_ridge", label: "Ridge" }],
      sampling_methods: [{ key: "smote", label: "SMOTE" }],
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
        params: { model_type: "ols", y: "y", x: ["x"], covariance: "robust" },
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

  it("renders the preview column role picker so x/y can be selected without comma typing", async () => {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue({
      ...preview(),
      columnCount: 3,
      columns: [
        ...preview().columns,
        { name: "marketing_spend", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
      ],
      previewRows: [{ y: 1, x: 2, marketing_spend: 7 }],
      suggestedX: ["x"],
    });
    vi.spyOn(api, "uploadDataset").mockResolvedValue({
      sha256: sha,
      filename: "data.csv",
    });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(
      draftResponse("h1", "pending", "pending"),
    );

    render(
      <GenesisWizard
        projectRoot="/proj"
        onClose={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x,marketing_spend\n1,2,7"], "data.csv", { type: "text/csv" })] },
    });

    expect(await screen.findByLabelText("column selector")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("column-x-marketing_spend"));
    expect(screen.getByLabelText("independent variables")).toHaveValue(
      "x, marketing_spend",
    );
  });

  it("renders IV role controls and patches structural IV params into the genesis model node", async () => {
    const ivPreview: api.FilePreview = {
      ...preview(),
      columnCount: 4,
      columns: [
        { name: "wage", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "y" },
        { name: "age", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
        { name: "educ", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
        { name: "distance_college", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
      ],
      previewRows: [{ wage: 10, age: 30, educ: 12, distance_college: 5 }],
      suggestedY: "wage",
      suggestedX: ["age", "educ", "distance_college"],
    };
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(ivPreview);
    vi.spyOn(api, "uploadDataset").mockResolvedValue({
      sha256: sha,
      filename: "data.csv",
    });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue({
      ...draftResponse("h1"),
      draft: {
        ...draftResponse("h1").draft,
        graph: {
          ...draftResponse("h1").draft.graph,
          nodes: draftResponse("h1").draft.graph.nodes.map((node) =>
            node.node_type === "input.upload"
              ? { ...node, columns: ["wage", "age", "educ", "distance_college"] }
              : node.node_type === "table"
                ? { ...node, columns: ["wage", "age", "educ", "distance_college"] }
                : node,
          ),
        },
      },
    });
    vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(draftResponse("h2", "configured", "pending"))
      .mockResolvedValueOnce(draftResponse("h3", "configured", "configured"));

    render(
      <GenesisWizard
        projectRoot="/proj"
        onClose={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["wage,age,educ,distance_college\n10,30,12,5"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "iv_2sls" },
    });
    expect(screen.getByLabelText("IV settings")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("role-educ"), {
      target: { value: "endog" },
    });
    fireEvent.change(screen.getByLabelText("role-distance_college"), {
      target: { value: "instrument" },
    });
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(2, "/proj", "draft_g1", "model_1", {
        params: {
          model_type: "iv_2sls",
          y: "wage",
          x: ["age"],
          covariance: "robust",
          iv_endog: ["educ"],
          iv_instruments: ["distance_college"],
        },
      }),
    );
  });

  it("patches covariance for ordinary regression genesis models", async () => {
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

    render(
      <GenesisWizard
        projectRoot="/proj"
        onClose={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x\n1,2"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));

    expect(screen.getByLabelText("covariance")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(2, "/proj", "draft_g1", "model_1", {
        params: {
          model_type: "auto",
          y: "y",
          x: ["x"],
          covariance: "robust",
        },
      }),
    );
  });

  it("blocks incomplete prediction settings like legacy Submit", async () => {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(preview());
    vi.spyOn(api, "uploadDataset").mockResolvedValue({
      sha256: sha,
      filename: "data.csv",
    });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(draftResponse("h2", "configured", "pending"));

    render(
      <GenesisWizard
        projectRoot="/proj"
        onClose={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x\n1,2"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByLabelText("prediction"));
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /请选择算法|algorithm/,
    );
    expect(api.patchDraftNode).toHaveBeenCalledTimes(1);
  });

  it("patches dCDH and prediction params with the same field names as legacy Submit", async () => {
    const dcdhPreview: api.FilePreview = {
      ...preview(),
      columnCount: 6,
      columns: [
        { name: "sales", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "y" },
        { name: "price", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
        { name: "firm", dtype: "string", missingRate: 0, uniqueCount: 3, suggestedRole: "id" },
        { name: "year", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "time" },
        { name: "treated", dtype: "numeric", missingRate: 0, uniqueCount: 2, suggestedRole: "x" },
        { name: "market", dtype: "string", missingRate: 0, uniqueCount: 2, suggestedRole: "x" },
      ],
      previewRows: [{ sales: 1, price: 2, firm: "a", year: 2020, treated: 0, market: "n" }],
      suggestedY: "sales",
      suggestedX: ["price", "firm", "year", "treated", "market"],
    };
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(dcdhPreview);
    vi.spyOn(api, "uploadDataset").mockResolvedValue({
      sha256: sha,
      filename: "data.csv",
    });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(draftResponse("h2", "configured", "pending"))
      .mockResolvedValueOnce(draftResponse("h3", "configured", "configured"));

    render(
      <GenesisWizard
        projectRoot="/proj"
        onClose={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["sales,price,firm,year,treated,market\n1,2,a,2020,0,n"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "dcdh" },
    });
    fireEvent.change(screen.getByLabelText("dcdh-entity"), {
      target: { value: "firm" },
    });
    fireEvent.change(screen.getByLabelText("dcdh-time"), {
      target: { value: "year" },
    });
    fireEvent.change(screen.getByLabelText("dcdh-treatment-path"), {
      target: { value: "treated" },
    });
    fireEvent.change(screen.getByLabelText("dcdh-cluster-var"), {
      target: { value: "market" },
    });
    fireEvent.click(screen.getByLabelText("prediction"));
    fireEvent.change(screen.getByLabelText("algorithm"), {
      target: { value: "prediction_ridge" },
    });
    fireEvent.change(screen.getByLabelText("cv_folds"), {
      target: { value: "7" },
    });
    fireEvent.change(screen.getByLabelText("sampling"), {
      target: { value: "smote" },
    });
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(2, "/proj", "draft_g1", "model_1", {
        params: {
          model_type: "dcdh",
          y: "sales",
          x: ["price", "market"],
          entity_col: "firm",
          time_col: "year",
          did_treatment_path: "treated",
          cs_cluster_var: "market",
          prediction_model_type: "prediction_ridge",
          prediction_cv_folds: 7,
          prediction_sampling_method: "smote",
        },
      }),
    );
  });
});
