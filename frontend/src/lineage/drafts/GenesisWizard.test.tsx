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
        { key: "linear_mixed_effects", label: "Linear Mixed Effects", group: "Panel" },
        { key: "iv_2sls", label: "IV / 2SLS", group: "IV" },
        { key: "dcdh", label: "DCDH DID", group: "DID" },
        {
          key: "time_series.arma_garch",
          label: "ARMA-GARCH",
          group: "Time series",
          params: [{ key: "model_options", kind: "json", required: true }],
        },
        {
          key: "time_series.ets",
          label: "ETS",
          group: "Time series",
          params: [{ key: "model_options", kind: "json", required: true }],
        },
        { key: "ordinal_logit", label: "Ordinal logit", group: "Ordinal" },
        { key: "multinomial_logit", label: "Multinomial logit", group: "Nominal" },
        { key: "survival_cox", label: "Survival / Cox", group: "Survival" },
        { key: "quantile_regression", label: "Quantile regression", group: "Robust / distributional" },
        { key: "anova", label: "ANOVA / ANCOVA", group: "ANOVA" },
      ],
      survey_design: {
        variance_methods: ["linearization", "replicate"],
        variance_method_requirements: {
          linearization: ["deterministic_refit", "influence_function"],
          replicate: ["deterministic_refit"],
        },
        replicate_types: ["brr", "jackknife"],
        lonely_psu_policies: ["fail", "adjust"],
        design_fields: [],
        sampling_weight_families: ["ols", "logit", "probit", "poisson"],
      },
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

function etsSchemaResponse(
  draftHash: string,
  status: "pending" | "configured",
  params: Record<string, unknown>,
): api.PipelineDraftResponse {
  const response = draftResponse(draftHash, "configured", status);
  response.draft.graph.nodes = response.draft.graph.nodes.map((node) =>
    node.node_type === "model"
      ? {
          ...node,
          model_type: "time_series.ets",
          params,
          schema_id: "time_series.ets@v1",
          editable_schema_hash: "ets-schema-hash",
          editable_schema: [
            {
              key: "model_type",
              kind: "select",
              label: "Model",
              required: true,
              options: ["time_series.ets"],
            },
            {
              key: "model_options",
              kind: "object",
              label: "ETS specification",
              required: true,
              schema: {
                type: "object",
                required: [
                  "time_column",
                  "value_column",
                  "error",
                  "trend",
                  "seasonal",
                  "damped_trend",
                ],
                properties: {
                  time_column: { type: "string", column_options: ["y", "x"] },
                  value_column: { type: "string", column_options: ["y", "x"] },
                  error: { enum: ["add", "mul"] },
                  trend: { enum: ["add", "mul", null] },
                  seasonal: { enum: ["add", "mul", null] },
                  damped_trend: { type: "boolean" },
                },
                additionalProperties: false,
              },
            },
          ],
        }
      : node,
  );
  return response;
}

describe("GenesisWizard", () => {
  it("uses the returned schema to edit a recipe without a recipe-specific form branch", async () => {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(preview());
    vi.spyOn(api, "uploadDataset").mockResolvedValue({ sha256: sha, filename: "data.csv" });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    const patch = vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(draftResponse("h2", "configured", "pending"))
      .mockResolvedValueOnce(
        etsSchemaResponse("h3", "pending", { model_type: "time_series.ets" }),
      )
      .mockResolvedValueOnce(
        etsSchemaResponse("h4", "configured", {
          model_type: "time_series.ets",
          model_options: {
            time_column: "y",
            value_column: "x",
            error: "add",
            trend: "add",
            seasonal: null,
            damped_trend: true,
          },
        }),
      );

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x\n1,2"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "time_series.ets" },
    });
    await waitFor(() => expect(screen.getByTestId("server-owned-model-options")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("time_column"), { target: { value: "y" } });
    fireEvent.change(screen.getByLabelText("value_column"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("error"), { target: { value: JSON.stringify("add") } });
    fireEvent.change(screen.getByLabelText("trend"), { target: { value: JSON.stringify("add") } });
    fireEvent.change(screen.getByLabelText("seasonal"), { target: { value: "__server_null__" } });
    fireEvent.click(screen.getByLabelText("damped_trend"));
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(3));
    expect(patch.mock.calls[2]?.[3]).toMatchObject({
      params: {
        model_type: "time_series.ets",
        model_options: {
          time_column: "y",
          value_column: "x",
          error: "add",
          trend: "add",
          seasonal: null,
          damped_trend: true,
        },
      },
    });
  });

  it("saves a univariate ARMA-GARCH genesis model with the shared contract controls", async () => {
    const timePreview: api.FilePreview = {
      ...preview(),
      fileName: "vix.csv",
      columns: [
        { name: "date", dtype: "datetime", missingRate: 0, uniqueCount: 3, suggestedRole: "time" },
        { name: "vix", dtype: "numeric", missingRate: 0.1, uniqueCount: 2, suggestedRole: "y" },
      ],
      previewRows: [{ date: "2025-01-02", vix: 14.2 }],
      suggestedY: "vix",
      suggestedX: [],
    };
    const withColumns = (response: api.PipelineDraftResponse): api.PipelineDraftResponse => ({
      ...response,
      draft: {
        ...response.draft,
        graph: {
          ...response.draft.graph,
          nodes: response.draft.graph.nodes.map((node) =>
            node.node_type === "input.upload" || node.node_type === "table"
              ? { ...node, columns: ["date", "vix"] }
              : node,
          ),
        },
      },
    });
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(timePreview);
    vi.spyOn(api, "fetchArmaGarchTransformPreflight").mockResolvedValue({
      schema_version: 1,
      source_row_count: 3,
      analysis_row_count: 2,
      diagnostics: [],
      transform_profiles: {},
      recommendation: { transform_id: "log_return_pct", score: 4, reason: "Full series favors changes." },
      transform_confirmation_required: true,
    });
    vi.spyOn(api, "uploadDataset").mockResolvedValue({ sha256: sha, filename: "vix.csv" });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(withColumns(draftResponse("h1")));
    const patch = vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(withColumns(draftResponse("h2", "configured", "pending")))
      .mockResolvedValueOnce(withColumns(draftResponse("h3", "configured", "configured")));

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["date,vix\n2025-01-02,14.2"], "vix.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "time_series.arma_garch" },
    });
    await waitFor(() => expect(screen.getByLabelText("time column")).toHaveValue("date"));
    expect(screen.getByLabelText("value column")).toHaveValue("vix");
    fireEvent.click(screen.getByLabelText("confirm drop missing values"));
    fireEvent.click(screen.getByLabelText("confirm transform"));
    expect(screen.getByTestId("genesis-save-model")).toBeEnabled();
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    expect(patch.mock.calls[1]?.[3]).toMatchObject({
      params: {
        model_type: "time_series.arma_garch",
        model_options: {
          time_column: "date",
          value_column: "vix",
          missing_value_policy: "drop_missing_confirmed",
          transform_confirmed: true,
        },
      },
    });
    expect(patch.mock.calls[1]?.[3]?.params?.model_options).not.toHaveProperty("dataset_ref");
    expect(patch.mock.calls[1]?.[3]?.params).not.toHaveProperty("y");
    expect(patch.mock.calls[1]?.[3]?.params).not.toHaveProperty("x");
  });

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
    expect(screen.getByText(/Treat rows as variables and columns as observations/i)).toBeInTheDocument();
    expect(screen.getByText(/Use the column cards below to add or remove x variables/i)).toBeInTheDocument();

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

  it("explicitly clears a previously saved analysis weight when the UI selects none", async () => {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(preview());
    vi.spyOn(api, "uploadDataset").mockResolvedValue({
      sha256: sha,
      filename: "data.csv",
    });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    const savedWithWeight = draftResponse("h3", "configured", "configured");
    const modelNode = savedWithWeight.draft.graph.nodes.find(
      (node) => node.node_id === "model_1" && node.node_type === "model",
    );
    if (!modelNode || modelNode.node_type !== "model") {
      throw new Error("model_1 fixture node is missing");
    }
    modelNode.params = {
      model_type: "ols",
      y: "y",
      x: ["x"],
      covariance: "robust",
      analysis_weight: "x",
    };
    vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(draftResponse("h2", "configured", "pending"))
      .mockResolvedValueOnce(savedWithWeight)
      .mockResolvedValueOnce(savedWithWeight);

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x\n1,2"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "ols" },
    });
    fireEvent.change(screen.getByLabelText("analysis weight"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByTestId("genesis-save-model"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByLabelText("analysis weight"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(
        3,
        "/proj",
        "draft_g1",
        "model_1",
        expect.objectContaining({
          params: expect.objectContaining({ analysis_weight: "" }),
        }),
      ),
    );
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

  it("patches bound LMM options from the genesis model step", async () => {
    const lmmPreview: api.FilePreview = {
      ...preview(),
      columnCount: 5,
      columns: [
        { name: "participant_id", dtype: "string", missingRate: 0, uniqueCount: 3, suggestedRole: "id" },
        { name: "week", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "time" },
        { name: "arm", dtype: "string", missingRate: 0, uniqueCount: 2, suggestedRole: "x" },
        { name: "baseline_score", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
        { name: "score", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "y" },
      ],
      previewRows: [{ participant_id: "p1", week: 1, arm: "control", baseline_score: 10, score: 11 }],
      suggestedY: "score",
      suggestedX: ["baseline_score"],
    };
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(lmmPreview);
    vi.spyOn(api, "uploadDataset").mockResolvedValue({ sha256: sha, filename: "data.csv" });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(draftResponse("h2", "configured", "pending"))
      .mockResolvedValueOnce(draftResponse("h3", "configured", "configured"));

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["score\n11"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "linear_mixed_effects" },
    });
    fireEvent.change(screen.getByLabelText("LMM subject"), { target: { value: "participant_id" } });
    fireEvent.change(screen.getByLabelText("LMM time"), { target: { value: "week" } });
    fireEvent.change(screen.getByLabelText("LMM group"), { target: { value: "arm" } });
    fireEvent.click(screen.getByLabelText("LMM random slope"));
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(2, "/proj", "draft_g1", "model_1", {
        params: {
          model_type: "linear_mixed_effects",
          y: "score",
          x: ["baseline_score"],
          covariance: "robust",
          model_options: {
            subject_id: "participant_id",
            time: "week",
            group: "arm",
            fit_method: "reml",
            random_slope: false,
          },
        },
      }),
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

  it("resuming a structural draft round-trips saved params so re-save does not strip them", async () => {
    // B2 regression (2026-07-08): adoptDraft used to restore only
    // y/x/focal/model_type. Resuming an IV draft and pressing Save model then
    // rebuilt params from pristine role state, silently deleting
    // iv_endog/iv_instruments from the saved draft.
    const base = draftResponse("h1", "configured", "configured");
    const ivDraft: api.PipelineDraftResponse = {
      ...base,
      draft: {
        ...base.draft,
        graph: {
          ...base.draft.graph,
          nodes: base.draft.graph.nodes.map((node) =>
            node.node_type === "input.upload" || node.node_type === "table"
              ? { ...node, columns: ["wage", "age", "educ", "distance_college"] }
              : node.node_type === "model"
                ? {
                    ...node,
                    model_type: "iv_2sls",
                    params: {
                      model_type: "iv_2sls",
                      y: "wage",
                      x: ["age"],
                      covariance: "robust",
                      iv_endog: ["educ"],
                      iv_instruments: ["distance_college"],
                    },
                  }
                : node,
          ),
        },
      },
    };
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([
      { draft_id: "draft_g1", status: "draft", draft_hash: "h1" },
    ]);
    vi.spyOn(api, "getPipelineDraft").mockResolvedValue(ivDraft);
    const patchSpy = vi.spyOn(api, "patchDraftNode").mockResolvedValue(ivDraft);

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Resume" }),
    );
    // The IV role picker must show the saved assignment (endog/instrument
    // restored, and those columns folded back into the UI X list).
    await waitFor(() =>
      expect(screen.getByLabelText("role-educ")).toHaveValue("endog"),
    );
    expect(screen.getByLabelText("role-distance_college")).toHaveValue(
      "instrument",
    );

    fireEvent.click(screen.getByTestId("genesis-save-model"));
    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith("/proj", "draft_g1", "model_1", {
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

  it("lets a resumed CSV genesis draft save its table without inventing a sheet name", async () => {
    const base = draftResponse("h1");
    const csvDraft: api.PipelineDraftResponse = {
      ...base,
      draft: {
        ...base.draft,
        graph: {
          ...base.draft.graph,
          nodes: base.draft.graph.nodes.map((node) =>
            node.node_type === "input.upload"
              ? { ...node, sheet_names: [] }
              : node.node_type === "table"
                ? { ...node, params: { sheet_name: undefined, transpose: false } }
                : node,
          ),
        },
      },
    };
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([
      { draft_id: "draft_g1", status: "draft", draft_hash: "h1" },
    ]);
    vi.spyOn(api, "getPipelineDraft").mockResolvedValue(csvDraft);
    const patchSpy = vi.spyOn(api, "patchDraftNode").mockResolvedValue(csvDraft);

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    const saveTable = await screen.findByTestId("genesis-save-table");
    expect(saveTable).toBeEnabled();
    fireEvent.click(saveTable);

    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith("/proj", "draft_g1", "table_1", {
        params: { sheet_name: undefined, transpose: false },
        columns: ["y", "x"],
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
      /algorithm/,
    );
    expect(api.patchDraftNode).toHaveBeenCalledTimes(1);
  });

  it("configures survival Cox columns and persists model_options", async () => {
    const survivalPreview: api.FilePreview = {
      ...preview(),
      columnCount: 4,
      columns: [
        { name: "duration", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "y" },
        { name: "event", dtype: "numeric", missingRate: 0, uniqueCount: 2, suggestedRole: "x" },
        { name: "group", dtype: "string", missingRate: 0, uniqueCount: 2, suggestedRole: "x" },
        { name: "age", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
      ],
      previewRows: [{ duration: 10, event: 1, group: "A", age: 40 }],
      suggestedY: "duration",
      suggestedX: ["age"],
    };
    const withColumns = (response: api.PipelineDraftResponse): api.PipelineDraftResponse => ({
      ...response,
      draft: {
        ...response.draft,
        graph: {
          ...response.draft.graph,
          nodes: response.draft.graph.nodes.map((node) =>
            node.node_type === "input.upload" || node.node_type === "table"
              ? { ...node, columns: ["duration", "event", "group", "age"] }
              : node,
          ),
        },
      },
    });
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(survivalPreview);
    vi.spyOn(api, "uploadDataset").mockResolvedValue({ sha256: sha, filename: "survival.csv" });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(withColumns(draftResponse("h1")));
    vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(withColumns(draftResponse("h2", "configured", "pending")))
      .mockResolvedValueOnce(withColumns(draftResponse("h3", "configured", "configured")));

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["duration,event,group,age\n10,1,A,40"], "survival.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "survival_cox" },
    });
    expect(screen.getByLabelText("survival event column")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("survival event column"), {
      target: { value: "event" },
    });
    fireEvent.change(screen.getByLabelText("survival group column"), {
      target: { value: "group" },
    });
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(2, "/proj", "draft_g1", "model_1", {
        params: {
          model_type: "survival_cox",
          y: "duration",
          x: ["age"],
          covariance: "robust",
          model_options: {
            event_column: "event",
            group_column: "group",
            ties: "breslow",
          },
        },
      }),
    );
  });

  it("persists quantile defaults and bootstrap configuration", async () => {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(preview());
    vi.spyOn(api, "uploadDataset").mockResolvedValue({ sha256: sha, filename: "data.csv" });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    vi.spyOn(api, "patchDraftNode")
      .mockResolvedValueOnce(draftResponse("h2", "configured", "pending"))
      .mockResolvedValueOnce(draftResponse("h3", "configured", "configured"));

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x\n1,2"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "quantile_regression" },
    });
    expect(screen.getByLabelText("quantiles")).toHaveValue("0.25, 0.5, 0.75");
    fireEvent.change(screen.getByLabelText("bootstrap reps"), {
      target: { value: "200" },
    });
    fireEvent.click(screen.getByTestId("genesis-save-model"));

    await waitFor(() =>
      expect(api.patchDraftNode).toHaveBeenNthCalledWith(2, "/proj", "draft_g1", "model_1", {
        params: {
          model_type: "quantile_regression",
          y: "y",
          x: ["x"],
          covariance: "robust",
          model_options: {
            quantiles: [0.25, 0.5, 0.75],
            bootstrap_reps: 200,
            random_state: 0,
          },
        },
      }),
    );
  });

  it("keeps ordinal and multinomial model families selectable with options", async () => {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(preview());
    vi.spyOn(api, "uploadDataset").mockResolvedValue({ sha256: sha, filename: "data.csv" });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    vi.spyOn(api, "patchDraftNode").mockResolvedValue(draftResponse("h2", "configured", "pending"));

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x\n1,2"], "data.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(api.patchDraftNode).toHaveBeenCalledTimes(1));

    const modelSelect = screen.getByLabelText("model type");
    expect(screen.getByRole("option", { name: "Ordinal logit" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Multinomial logit" })).toBeInTheDocument();

    fireEvent.change(modelSelect, { target: { value: "ordinal_logit" } });
    expect(screen.getByLabelText("ordinal model options")).toHaveValue(
      '{"optimizer":"bfgs","maxiter":500}',
    );
    fireEvent.change(modelSelect, { target: { value: "multinomial_logit" } });
    expect(screen.getByLabelText("multinomial model options")).toHaveValue(
      '{"maxiter":500}',
    );
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
    fireEvent.change(screen.getByLabelText("frequency weight"), {
      target: { value: "price" },
    });
    fireEvent.change(screen.getByLabelText("analysis weight"), {
      target: { value: "treated" },
    });
    fireEvent.change(screen.getByLabelText("sampling weight"), {
      target: { value: "market" },
    });
    fireEvent.click(screen.getByLabelText("prediction"));
    fireEvent.change(screen.getByLabelText("algorithm"), {
      target: { value: "prediction_ridge" },
    });
    fireEvent.change(screen.getByLabelText("cv_folds"), {
      target: { value: "7" },
    });
    fireEvent.change(screen.getByLabelText("data structure"), {
      target: { value: "iid" },
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
          treatment_path_col: "treated",
          cs_cluster_var: "market",
          frequency_weight: "price",
          analysis_weight: "treated",
          sampling_weight: "market",
          prediction_model_type: "prediction_ridge",
          prediction_cv_folds: 7,
          prediction_sampling_method: "smote",
          prediction_data_structure: "iid",
          prediction_final_holdout_fraction: 0.2,
          prediction_shuffle: true,
        },
      }),
    );
  });
});


/**
 * GenesisWizard is the entry point a user actually reaches from "Import data
 * and create analysis". RunForm imports the same controls and looks almost
 * identical, and wiring only RunForm left these controls unreachable in the
 * product while every component test and every RunForm test stayed green --
 * the failure was visible only in a browser. These assertions exist so the
 * same mistake fails here instead.
 */
describe("GenesisWizard exposes the v1.8.7 declarations", () => {
  async function reachModelStep() {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    vi.spyOn(api, "previewFile").mockResolvedValue(preview());
    vi.spyOn(api, "uploadDataset").mockResolvedValue({ sha256: sha, filename: "d.csv" });
    vi.spyOn(api, "createGenesisDraft").mockResolvedValue(draftResponse("h1"));
    const patch = vi.spyOn(api, "patchDraftNode")
      .mockResolvedValue(draftResponse("h2", "configured", "pending"));

    render(<GenesisWizard projectRoot="/proj" onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Dataset file"), {
      target: { files: [new File(["y,x\n1,2\n3,4"], "d.csv", { type: "text/csv" })] },
    });
    fireEvent.click(await screen.findByTestId("genesis-save-table"));
    await waitFor(() => expect(patch).toHaveBeenCalled());
  }

  it("renders the survey design controls with options taken from capabilities", async () => {
    await reachModelStep();
    fireEvent.change(await screen.findByLabelText("model type"), { target: { value: "ols" } });
    await waitFor(() => {
      expect(screen.getByLabelText("Complex survey design")).toBeInTheDocument();
    });
    const replicate = screen.getByLabelText("Survey replicate type") as HTMLSelectElement;
    expect([...replicate.options].map((o) => o.value).filter(Boolean)).toEqual([
      "brr",
      "jackknife",
    ]);
  });

  it("keeps the design controls off families whose engine refuses a sampling weight", async () => {
    /**
     * `cs_did` is not in the server's `sampling_weight_families`.  Offering it a
     * design would produce a run the engine rejects for a reason nothing on the
     * form explains.
     */
    await reachModelStep();
    fireEvent.change(await screen.findByLabelText("model type"), { target: { value: "cs_did" } });
    await waitFor(() => {
      expect(screen.queryByLabelText("Complex survey design")).not.toBeInTheDocument();
    });
  });

  it("renders the ANOVA controls with no preset sums-of-squares type", async () => {
    await reachModelStep();
    fireEvent.change(await screen.findByLabelText("model type"), {
      target: { value: "anova" },
    });
    await waitFor(() => {
      expect(screen.getByLabelText("ANOVA settings")).toBeInTheDocument();
    });
    expect((screen.getByLabelText("ANOVA sums of squares") as HTMLSelectElement).value).toBe("");
  });
});
