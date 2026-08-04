import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataColumnCastSection } from "./DataColumnCastSection";
import type { GraphViewNode } from "../../api/graphViewTypes";

const {
  resolvedMock,
  contextMock,
  previewMock,
  confirmMock,
  recordMock,
  featurePreviewMock,
  featureConfirmMock,
  transformPreviewMock,
  transformConfirmMock,
  modelStartMock,
} = vi.hoisted(() => ({
  resolvedMock: { current: null as unknown },
  contextMock: { current: null as unknown },
  previewMock: vi.fn(),
  confirmMock: vi.fn(),
  recordMock: vi.fn(),
  featurePreviewMock: vi.fn(),
  featureConfirmMock: vi.fn(),
  transformPreviewMock: vi.fn(),
  transformConfirmMock: vi.fn(),
  modelStartMock: vi.fn(),
}));

vi.mock("../NodeOperationContextProvider", () => ({
  useResolvedNodeOperationContext: () => resolvedMock.current,
}));
vi.mock("../../../workbench/ProjectRootContext", () => ({
  useProjectRootOptional: () => contextMock.current,
}));
vi.mock("../../dataOperations", () => ({
  fetchDataColumnCastContext: (...args: unknown[]) => previewMock(...args),
  previewDataColumnsCast: (...args: unknown[]) => previewMock("preview", ...args),
  confirmDataColumnsCast: (...args: unknown[]) => confirmMock(...args),
  fetchDataColumnCastRecordByChildNode: (...args: unknown[]) => recordMock(...args),
  previewFeatureRecipe: (...args: unknown[]) => featurePreviewMock(...args),
  confirmFeatureRecipe: (...args: unknown[]) => featureConfirmMock(...args),
  previewDataTransform: (...args: unknown[]) => transformPreviewMock(...args),
  confirmDataTransform: (...args: unknown[]) => transformConfirmMock(...args),
  startModelFromDataNode: (...args: unknown[]) => modelStartMock(...args),
}));

function node(): GraphViewNode {
  return {
    id: "hash-source::stage:cleaned",
    nodeKey: "hash-source::stage:cleaned",
    raw: { id: "stage:cleaned", payload_ref: "processed/cleaned_dataset.parquet" },
    stage: "clean",
    kind: "dataset_stage",
    title: "Cleaned data",
    parentStageId: null,
    trust: "ok",
    decisions: [],
  };
}

describe("DataColumnCastSection", () => {
  beforeEach(() => {
    contextMock.current = "/tmp/project";
    resolvedMock.current = {
      ok: true,
      context: {
        ownership: { owner_run_id: "run-1" },
        operation_target: { op_node_id: "stage:cleaned" },
      },
    };
    previewMock.mockReset();
    recordMock.mockReset();
    featurePreviewMock.mockReset();
    featureConfirmMock.mockReset();
    transformPreviewMock.mockReset();
    transformConfirmMock.mockReset();
    modelStartMock.mockReset();
    previewMock.mockImplementation((...args: unknown[]) => {
      if (args[0] === "preview") {
        const request = args[2] as { casts: Array<{ column: string; target_dtype: string }> };
        return Promise.resolve({
          preview: {
            operation_id: "data.columns.cast",
            operation_version: "v1",
            status: "ready",
            fingerprint: "fp-1",
            row_count: 2,
            casts: request.casts,
            items: request.casts.map((c) => ({
              column: c.column,
              target_dtype: c.target_dtype,
              before_dtype: "str",
              after_dtype: c.target_dtype === "numeric" ? "int64" : "string",
              success_count: 2,
              failure_count: 0,
              failure_examples: [],
              new_missing_count: 0,
              status: "ready",
            })),
            downstream_invalidation: ["model:ols"],
          },
        });
      }
      return Promise.resolve({
        source_run_id: "run-1",
        source_node_id: "stage:cleaned",
        source_artifact_id: "cleaned_dataset",
        columns: [
          { name: "age", dtype: "str" },
          { name: "name", dtype: "str" },
        ],
      });
    });
    confirmMock.mockResolvedValue({
      status: "completed",
      operation: { record_id: "op-1", status: "completed" },
    });
    featurePreviewMock.mockResolvedValue({
      preview: {
        status: "ready",
        fingerprint: "feature-fp-1",
        row_count: 2,
        output_columns: ["age", "name", "derived_value"],
      },
    });
    transformPreviewMock.mockResolvedValue({
      preview: {
        status: "ready",
        fingerprint: "transform-fp-1",
        row_count_before: 2,
        row_count_after: 2,
      },
    });
    featureConfirmMock.mockResolvedValue({ status: "completed" });
    transformConfirmMock.mockResolvedValue({ status: "completed" });
    modelStartMock.mockResolvedValue({
      status: "running",
      run_id: "run-model-child",
      model_type: "ols",
      source_lineage: {
        source_run_id: "run-1",
        source_node_id: "stage:cleaned",
        source_artifact_id: "cleaned_dataset",
        source_node_hash: "node-hash-1",
      },
    });
  });

  it("renders the schema diff of a code.execute child, not just who made it", async () => {
    recordMock.mockResolvedValue({
      operation: {
        record_id: "oprec_code_1",
        operation_id: "code.execute",
        operation_version: "v1",
        status: "completed",
        effect_status: "committed",
        projection_status: "complete",
        actor_type: "human_ui",
        diff_ref: {
          kind: "data.schema_diff.v1",
          columns_added: ["senior"],
          columns_removed: ["region"],
          dtype_changes: [{ column: "wage", before_dtype: "int64", after_dtype: "float64" }],
          row_count_before: 30,
          row_count_after: 28,
          source_fingerprint: "fp-before",
          result_fingerprint: "fp-after",
        },
        verification: { status: "completed", passed: true, checks: {} },
        outputs: {},
      },
    });
    const child: GraphViewNode = {
      ...node(),
      id: "code-exec:d46",
      nodeKey: "code-exec:d46",
      title: "Run code",
      raw: {
        id: "code-exec:d46",
        payload_ref: "derived/code_execute/d46/data.csv",
        annotations: [
          {
            type: "data_operation",
            operation_id: "code.execute",
            execution_key: "exec_d46",
            recipe_path: "derived/code_execute/d46/recipe.json",
            schema_fingerprint: "fp-after",
          },
        ],
      },
    };

    render(<DataColumnCastSection node={child} />);

    await waitFor(() =>
      expect(screen.getByTestId("data-cast-provenance-diff")).toBeInTheDocument(),
    );
    const diff = screen.getByTestId("data-cast-provenance-diff");
    expect(diff).toHaveTextContent("Rows 30 → 28");
    expect(diff).toHaveTextContent("+ senior");
    expect(diff).toHaveTextContent("− region");
    expect(diff).toHaveTextContent("wage: int64 → float64");
    expect(screen.getByTestId("data-cast-provenance")).toHaveTextContent(
      "Created by code.execute",
    );
  });

  it("renders durable operation provenance on a cast child node", async () => {
    recordMock.mockResolvedValue({
      operation: {
        record_id: "oprec_child_1",
        operation_id: "data.column.cast",
        operation_version: "v1",
        status: "completed",
        effect_status: "committed",
        projection_status: "complete",
        actor_type: "human_ui",
        diff_ref: {
          kind: "data.schema_diff.v1",
          column: "wage",
          before_dtype: "int64",
          after_dtype: "string",
          source_fingerprint: "fp-before",
          result_fingerprint: "fp-after",
        },
        verification: { status: "completed", passed: true, checks: {} },
        outputs: {},
      },
    });
    const child: GraphViewNode = {
      ...node(),
      id: "data-cast:abc123",
      nodeKey: "data-cast:abc123",
      title: "Cast wage → string",
      raw: {
        id: "data-cast:abc123",
        payload_ref: "derived/data_column_cast/abc123/data.csv",
        annotations: [
          {
            type: "data_operation",
            operation_id: "data.column.cast",
            execution_key: "exec_abc123",
            recipe_path: "derived/data_column_cast/abc123/recipe.json",
            schema_fingerprint: "fp-after",
          },
        ],
      },
    };

    render(<DataColumnCastSection node={child} />);

    await waitFor(() =>
      expect(screen.getByTestId("data-cast-provenance")).toBeInTheDocument(),
    );
    expect(recordMock).toHaveBeenCalledWith("/tmp/project", "data-cast:abc123");
    const provenance = screen.getByTestId("data-cast-provenance");
    expect(provenance).toHaveTextContent("Operation Record oprec_child_1");
    expect(provenance).toHaveTextContent("completed");
    expect(provenance).toHaveTextContent("verification passed");
    expect(provenance).toHaveTextContent("wage: int64 → string");
    expect(provenance).toHaveTextContent("exec_abc123");
    expect(provenance).toHaveTextContent("derived/data_column_cast/abc123/recipe.json");
  });

  it("keeps typed provenance from annotations when the record fetch fails", async () => {
    recordMock.mockRejectedValue(new Error("record store unavailable"));
    const child: GraphViewNode = {
      ...node(),
      id: "data-cast:abc123",
      nodeKey: "data-cast:abc123",
      title: "Cast wage → string",
      raw: {
        id: "data-cast:abc123",
        annotations: [
          {
            type: "data_operation",
            operation_id: "data.column.cast",
            execution_key: "exec_abc123",
            recipe_path: "derived/data_column_cast/abc123/recipe.json",
            schema_fingerprint: "fp-after",
          },
        ],
      },
    };

    render(<DataColumnCastSection node={child} />);

    await waitFor(() =>
      expect(screen.getByTestId("data-cast-provenance")).toBeInTheDocument(),
    );
    const provenance = screen.getByTestId("data-cast-provenance");
    expect(provenance).toHaveTextContent("exec_abc123");
    expect(provenance).toHaveTextContent("operation record unavailable");
  });

  it("previews a single column (batch of one) and requires a second confirm action", async () => {
    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("data-cast-column-0")).toBeInTheDocument());
    expect(screen.getByTestId("data-cast-source-artifact")).toHaveTextContent("cleaned_dataset");

    fireEvent.click(screen.getByTestId("data-cast-preview"));
    await waitFor(() => expect(screen.getByTestId("data-cast-preview-result")).toBeInTheDocument());
    expect(screen.getByTestId("data-cast-preview-item-age")).toHaveTextContent("str → int64");
    expect(confirmMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("data-cast-confirm"));
    await waitFor(() => expect(screen.getByTestId("data-cast-complete")).toBeInTheDocument());
    expect(confirmMock).toHaveBeenCalledWith("/tmp/project", {
      source_run_id: "run-1",
      source_node_id: "stage:cleaned",
      source_artifact_id: "cleaned_dataset",
      casts: [{ column: "age", target_dtype: "numeric" }],
      output_format: "csv",
      preview_fingerprint: "fp-1",
    });
  });

  it("casts multiple columns in one batch operation", async () => {
    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("data-cast-column-0")).toBeInTheDocument());

    // add a second column row; picks the next unused column (name)
    fireEvent.click(screen.getByTestId("data-cast-add-column"));
    await waitFor(() => expect(screen.getByTestId("data-cast-column-1")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("data-cast-target-1"), { target: { value: "string" } });

    fireEvent.click(screen.getByTestId("data-cast-preview"));
    await waitFor(() => expect(screen.getByTestId("data-cast-preview-item-name")).toBeInTheDocument());
    expect(screen.getByTestId("data-cast-preview-item-age")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("data-cast-confirm"));
    await waitFor(() => expect(screen.getByTestId("data-cast-complete")).toBeInTheDocument());
    expect(confirmMock).toHaveBeenCalledWith("/tmp/project", {
      source_run_id: "run-1",
      source_node_id: "stage:cleaned",
      source_artifact_id: "cleaned_dataset",
      casts: [
        { column: "age", target_dtype: "numeric" },
        { column: "name", target_dtype: "string" },
      ],
      output_format: "csv",
      preview_fingerprint: "fp-1",
    });
  });

  it("exposes feature recipes and data transforms from the dataset node", async () => {
    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("feature-recipe-builder")).toBeInTheDocument());
    expect(screen.getByTestId("data-transform-builder")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("feature-recipe-preview"));
    await waitFor(() => expect(screen.getByTestId("feature-recipe-preview-result")).toHaveTextContent("ready"));
    expect(featurePreviewMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({
      operation_id: "interaction",
      source_artifact_id: "cleaned_dataset",
    }));

    fireEvent.click(screen.getByTestId("data-transform-preview"));
    await waitFor(() => expect(screen.getByTestId("data-transform-preview-result")).toHaveTextContent("ready"));
    expect(transformPreviewMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({
      operation: "subset",
      source_node_id: "stage:cleaned",
    }));
  });

  it("exposes a real OLS run action from a numeric data node", async () => {
    previewMock.mockImplementation((...args: unknown[]) => {
      if (args[0] === "preview") return Promise.resolve({ preview: { status: "ready", fingerprint: "fp-1", row_count: 2, items: [], downstream_invalidation: [] } });
      return Promise.resolve({
        source_run_id: "run-1",
        source_node_id: "stage:cleaned",
        source_artifact_id: "cleaned_dataset",
        row_count: 48,
        columns: [
          { name: "score", dtype: "float64" },
          { name: "age", dtype: "int64" },
          { name: "weighted_score", dtype: "float64" },
        ],
      });
    });

    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("data-node-model-run")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("data-node-model-run"));

    await waitFor(() => expect(screen.getByTestId("data-node-model-run-result")).toHaveTextContent("run-model-child"));
    expect(modelStartMock).toHaveBeenCalledWith("/tmp/project", {
      source_run_id: "run-1",
      source_node_id: "stage:cleaned",
      source_artifact_id: "cleaned_dataset",
      model_type: "ols",
      y: "score",
      x: ["age", "weighted_score"],
      covariance: "robust",
    });
  });

  it("exposes and transfers merge how plus an explicit growth policy", async () => {
    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("data-transform-builder")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Data transform operation"), { target: { value: "merge" } });
    fireEvent.change(screen.getByLabelText("Merge keys"), { target: { value: "id" } });
    fireEvent.change(screen.getByLabelText("Merge how"), { target: { value: "inner" } });
    fireEvent.change(screen.getByLabelText("Merge max rows"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("Merge max growth factor"), { target: { value: "1.5" } });
    fireEvent.change(screen.getByLabelText("Secondary run"), { target: { value: "run-right" } });
    fireEvent.change(screen.getByLabelText("Secondary artifact"), { target: { value: "right-data" } });

    fireEvent.click(screen.getByTestId("data-transform-preview"));
    await waitFor(() => expect(transformPreviewMock).toHaveBeenCalled());
    expect(transformPreviewMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({
      operation: "merge",
      parameters: {
        keys: ["id"],
        how: "inner",
        growth_policy: { max_rows: 12, max_growth_factor: 1.5 },
      },
      secondary_run_id: "run-right",
      secondary_artifact_id: "right-data",
    }));
  });

  it("exposes and transfers append schema compatibility plus row-growth policy", async () => {
    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("data-transform-builder")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Data transform operation"), { target: { value: "append" } });
    fireEvent.change(screen.getByLabelText("Append schema policy"), { target: { value: "union" } });
    fireEvent.change(screen.getByLabelText("Append max rows"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Append max growth factor"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Secondary run"), { target: { value: "run-right" } });
    fireEvent.change(screen.getByLabelText("Secondary artifact"), { target: { value: "right-data" } });

    fireEvent.click(screen.getByTestId("data-transform-preview"));
    await waitFor(() => expect(transformPreviewMock).toHaveBeenCalled());
    expect(transformPreviewMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({
      operation: "append",
      parameters: {
        schema_policy: "union",
        row_growth_policy: { max_rows: 100, max_growth_factor: 2 },
      },
    }));
  });

  it("exposes complete parameters for both reshape directions", async () => {
    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("data-transform-builder")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Data transform operation"), { target: { value: "reshape" } });
    fireEvent.change(screen.getByLabelText("Reshape direction"), { target: { value: "long_to_wide" } });
    fireEvent.change(screen.getByLabelText("Long index columns"), { target: { value: "id,group" } });
    fireEvent.change(screen.getByLabelText("Long columns column"), { target: { value: "metric" } });
    fireEvent.change(screen.getByLabelText("Long values column"), { target: { value: "value" } });

    fireEvent.click(screen.getByTestId("data-transform-preview"));
    await waitFor(() => expect(transformPreviewMock).toHaveBeenCalled());
    expect(transformPreviewMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({
      operation: "reshape",
      parameters: {
        direction: "long_to_wide",
        index: ["id", "group"],
        columns: "metric",
        values: "value",
      },
    }));
  });

  it("transfers a user-visible subset row range", async () => {
    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("data-transform-builder")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Subset row range"), { target: { value: "2:8" } });
    fireEvent.click(screen.getByTestId("data-transform-preview"));
    await waitFor(() => expect(transformPreviewMock).toHaveBeenCalled());
    expect(transformPreviewMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({
      operation: "subset",
      parameters: expect.objectContaining({ row_index_range: { start: 2, stop: 8 } }),
    }));
  });

  it("shows the typed FeatureRecipe payload after preview", async () => {
    render(<DataColumnCastSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("feature-recipe-builder")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("feature-recipe-preview"));
    await waitFor(() => expect(screen.getByTestId("feature-recipe-payload")).toBeInTheDocument());
    expect(screen.getByTestId("feature-recipe-payload")).toHaveTextContent("interaction");
    expect(screen.getByTestId("feature-recipe-payload")).toHaveTextContent("cleaned_dataset");
  });
});
