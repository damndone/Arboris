import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataColumnCastSection } from "./DataColumnCastSection";
import type { GraphViewNode } from "../../api/graphViewTypes";

const { resolvedMock, contextMock, previewMock, confirmMock, recordMock } = vi.hoisted(() => ({
  resolvedMock: { current: null as unknown },
  contextMock: { current: null as unknown },
  previewMock: vi.fn(),
  confirmMock: vi.fn(),
  recordMock: vi.fn(),
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
});
