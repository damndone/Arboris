import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StatisticalExplorationSection } from "./StatisticalExplorationSection";
import type { GraphViewNode } from "../../api/graphViewTypes";

const { resolvedMock, contextMock, schemaMock, previewMock, confirmMock } = vi.hoisted(() => ({
  resolvedMock: { current: null as unknown },
  contextMock: { current: null as unknown },
  schemaMock: vi.fn(),
  previewMock: vi.fn(),
  confirmMock: vi.fn(),
}));

vi.mock("../NodeOperationContextProvider", () => ({
  useResolvedNodeOperationContext: () => resolvedMock.current,
}));
vi.mock("../../../workbench/ProjectRootContext", () => ({
  useProjectRootOptional: () => contextMock.current,
}));
vi.mock("../../dataOperations", () => ({
  fetchDataColumnCastContext: (...args: unknown[]) => schemaMock(...args),
}));
vi.mock("../../statisticalExploration", () => ({
  previewStatisticalExploration: (...args: unknown[]) => previewMock(...args),
  confirmStatisticalExploration: (...args: unknown[]) => confirmMock(...args),
}));

function node(): GraphViewNode {
  return {
    id: "stage:raw",
    nodeKey: "stage:raw",
    raw: { id: "stage:raw", payload_ref: "data.csv" },
    stage: "source",
    kind: "dataset_stage",
    title: "Raw data",
    parentStageId: null,
    trust: "ok",
    decisions: [],
  };
}

describe("StatisticalExplorationSection", () => {
  beforeEach(() => {
    contextMock.current = "/tmp/project";
    resolvedMock.current = {
      ok: true,
      context: {
        ownership: { owner_run_id: "run-1" },
        operation_target: { op_node_id: "stage:raw" },
      },
    };
    schemaMock.mockResolvedValue({
      source_run_id: "run-1",
      source_node_id: "stage:raw",
      source_artifact_id: "source_data",
      row_count: 12,
      columns: [
        { name: "year", dtype: "int64" },
        { name: "middle", dtype: "int64" },
        { name: "bdsnew", dtype: "int64" },
        { name: "pfl", dtype: "float64" },
      ],
    });
    previewMock.mockResolvedValue({
      spec: { operation: "summarize" },
      preview: {
        status: "ready",
        fingerprint: "fp-1",
        source_sha256: "sha-1",
        source_artifact_id: "source_data",
        result: {
          filtered_row_count: 2,
          missing_policy: "variablewise",
          variables: { bdsnew: { obs: 2, mean: 316045, std_dev: 304098.34, min: 101015, max: 531075 } },
        },
      },
    });
    confirmMock.mockResolvedValue({
      status: "completed",
      exploration: { artifact_id: "statistical_exploration_fp-1" },
    });
  });

  it("supports multiple typed filters combined with AND before preview and confirm", async () => {
    render(<StatisticalExplorationSection node={node()} />);

    await waitFor(() => expect(screen.getByTestId("statistical-exploration-section")).toBeInTheDocument());
    expect(screen.getByTestId("statistical-exploration-source")).toHaveTextContent("source_data");

    fireEvent.click(screen.getByTestId("statistical-exploration-add-filter"));
    fireEvent.click(screen.getByTestId("statistical-exploration-add-filter"));
    fireEvent.change(screen.getByTestId("statistical-filter-column-0"), { target: { value: "year" } });
    fireEvent.change(screen.getByTestId("statistical-filter-value-0"), { target: { value: "1998" } });
    fireEvent.change(screen.getByTestId("statistical-filter-column-1"), { target: { value: "middle" } });
    fireEvent.change(screen.getByTestId("statistical-filter-value-1"), { target: { value: "0" } });

    fireEvent.click(screen.getByTestId("statistical-exploration-preview"));
    await waitFor(() => expect(screen.getByTestId("statistical-exploration-result")).toBeInTheDocument());
    const request = previewMock.mock.calls[0][1] as { filters: Array<{ column: string; value: number }> };
    expect(request.filters).toEqual([
      { column: "year", operator: "eq", value: 1998 },
      { column: "middle", operator: "eq", value: 0 },
    ]);
    expect(screen.getByTestId("statistical-exploration-result")).toHaveTextContent("Rows after filters: 2");

    fireEvent.click(screen.getByTestId("statistical-exploration-confirm"));
    await waitFor(() => expect(screen.getByTestId("statistical-exploration-complete")).toBeInTheDocument());
    expect(confirmMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({
      preview_fingerprint: "fp-1",
    }));
  });

  it("does not render for a model node", () => {
    render(<StatisticalExplorationSection node={{ ...node(), kind: "model" }} />);
    expect(screen.queryByTestId("statistical-exploration-section")).not.toBeInTheDocument();
  });
});
