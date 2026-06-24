import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { OperationSection } from "./OperationSection";
import { RerunContext } from "../RerunContext";
import type { RerunContextValue } from "../RerunContext";
import type { GraphViewNode, HeadSetNode } from "../../api/graphViewTypes";

function modelNode(): HeadSetNode {
  return {
    id: "M1",
    nodeKey: "M1",
    opNodeId: "model:ols_1",
    raw: {},
    stage: "model",
    kind: "model",
    title: "OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    nodeHash: "M1",
    producingStage: "estimation",
    casRef: null,
    runs: ["run_a"],
    editable: true,
    opType: "ols",
    schemaId: "ols@v1",
    editableSchemaSource: "run_inputs",
    editableSchema: [
      {
        kind: "select",
        key: "covariance",
        label: "Covariance",
        options: ["robust", "clustered", "unadjusted"],
        value: "clustered", // backfilled current value (not the capabilities default)
      },
    ],
  };
}

function renderWithRerun(node: GraphViewNode, submitRerun = vi.fn().mockResolvedValue(undefined)) {
  const value: RerunContextValue = { submitRerun };
  render(
    <RerunContext.Provider value={value}>
      <OperationSection node={node} />
    </RerunContext.Provider>,
  );
  return { submitRerun };
}

describe("OperationSection (editable)", () => {
  it("seeds controls from the backfilled editable_schema value", () => {
    renderWithRerun(modelNode());
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("clustered"); // not the capabilities default "robust"
  });

  it("submit is disabled until a value changes", () => {
    renderWithRerun(modelNode());
    expect((screen.getByTestId("operation-rerun-submit") as HTMLButtonElement).disabled).toBe(true);
  });

  it("submits from_node + only-changed op_overrides, then shows success without navigating", async () => {
    const { submitRerun } = renderWithRerun(modelNode());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    fireEvent.click(screen.getByTestId("operation-rerun-submit"));
    await waitFor(() => expect(submitRerun).toHaveBeenCalledTimes(1));
    expect(submitRerun).toHaveBeenCalledWith({
      fromNode: "model:ols_1",
      opOverrides: { covariance: "robust" },
    });
    await screen.findByTestId("operation-rerun-done");
  });

  it("degrades to read-only without a RerunProvider", () => {
    render(<OperationSection node={modelNode()} />);
    expect(screen.queryByTestId("operation-rerun-submit")).toBeNull();
    // read-only row still shows the value
    expect(screen.getByTestId("operation-control-covariance").textContent).toContain("clustered");
  });
});
