import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DatasetVariable } from "./dataViewApi";

const ops = {
  previewDataTransform: vi.fn(),
  confirmDataTransform: vi.fn(),
  previewFeatureRecipe: vi.fn(),
  confirmFeatureRecipe: vi.fn(),
};

vi.mock("../lineage/dataOperations", () => ({
  previewDataTransform: (...args: unknown[]) => ops.previewDataTransform(...args),
  confirmDataTransform: (...args: unknown[]) => ops.confirmDataTransform(...args),
  previewFeatureRecipe: (...args: unknown[]) => ops.previewFeatureRecipe(...args),
  confirmFeatureRecipe: (...args: unknown[]) => ops.confirmFeatureRecipe(...args),
}));

import { TransformPanel } from "./TransformPanel";

const variable = (name: string, type: DatasetVariable["type"]): DatasetVariable => ({
  position: 1, name, type, dtype: type === "numeric" ? "float64" : "object", missing: 0,
  declared_missing_matches: 0, unique: 3, variable_label: null, value_labels: {},
  measurement_level: null, user_missing_values: [],
});

const variables = [variable("age", "numeric"), variable("wage", "numeric"), variable("city", "string")];
const readyPreview = {
  row_count_before: 100, row_count_after: 64, output_columns: ["age", "wage", "city"],
  downstream_invalidation: ["model:ols_1"], status: "ready", reason: null, fingerprint: "fp1",
};

function renderPanel(onCreated = vi.fn()) {
  render(
    <TransformPanel projectRoot="/p" runId="r1" nodeId="stage:raw" artifactId="raw_d.csv" variables={variables} onCreated={onCreated} />,
  );
  return onCreated;
}

beforeEach(() => Object.values(ops).forEach((fn) => fn.mockReset()));

describe("TransformPanel", () => {
  it("selects rows with typed values, previews, then applies as a child dataset", async () => {
    ops.previewDataTransform.mockResolvedValue({ preview: readyPreview });
    ops.confirmDataTransform.mockResolvedValue({ effect: { child_node_id: "data-subset:abc" } });
    const onCreated = renderPanel();
    fireEvent.change(screen.getByLabelText("Condition 1 value"), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/Rows 100 → 64/)).toBeTruthy();
    expect(ops.previewDataTransform).toHaveBeenCalledWith("/p", {
      source_run_id: "r1", source_node_id: "stage:raw", source_artifact_id: "raw_d.csv",
      operation: "subset",
      parameters: { columns: ["age", "wage", "city"], filters: [{ column: "age", op: "ge", value: 30 }] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply as new dataset" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("data-subset:abc"));
    expect(ops.confirmDataTransform.mock.calls[0][1].preview_fingerprint).toBe("fp1");
  });

  it("recodes a numeric variable into bands", async () => {
    ops.previewDataTransform.mockResolvedValue({ preview: { ...readyPreview, row_count_after: 100 } });
    renderPanel();
    fireEvent.click(screen.getByRole("radio", { name: "Recode into new variable" }));
    fireEvent.change(screen.getByLabelText("New variable"), { target: { value: "age_group" } });
    fireEvent.change(screen.getByLabelText("Recode rules"), { target: { value: "18..29 = 1\n30..49 = 2\nelse = 3" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByTestId("transform-preview");
    expect(ops.previewDataTransform.mock.calls[0][1].parameters).toEqual({
      column: "age", output: "age_group",
      rules: [{ from: { low: 18, high: 29 }, to: 1 }, { from: { low: 30, high: 49 }, to: 2 }, { from: "else", to: 3 }],
    });
  });

  it("computes a ratio through the feature recipe", async () => {
    ops.previewFeatureRecipe.mockResolvedValue({ preview: { ...readyPreview, row_count: 100 } });
    renderPanel();
    fireEvent.click(screen.getByRole("radio", { name: "Compute new variable" }));
    fireEvent.change(screen.getByLabelText("Compute operation"), { target: { value: "ratio" } });
    fireEvent.change(screen.getByLabelText("Second variable"), { target: { value: "wage" } });
    fireEvent.change(screen.getByLabelText("New variable"), { target: { value: "age_per_wage" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByTestId("transform-preview");
    expect(ops.previewFeatureRecipe.mock.calls[0][1]).toMatchObject({
      operation_id: "ratio", inputs: ["age", "wage"], output: "age_per_wage",
      parameters: { numerator: "age", denominator: "wage", zero_policy: "fail_closed" },
    });
  });

  it("shows a blocked preview without an apply button, and the server's refusal", async () => {
    ops.previewDataTransform.mockResolvedValueOnce({ preview: { ...readyPreview, status: "blocked", reason: "no rows remain" } });
    renderPanel();
    fireEvent.change(screen.getByLabelText("Condition 1 value"), { target: { value: "999" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect((await screen.findByRole("alert")).textContent).toContain("no rows remain");
    expect(screen.queryByRole("button", { name: "Apply as new dataset" })).toBeNull();
    ops.previewDataTransform.mockRejectedValueOnce(new Error("recode: 3 value(s) of age match no rule"));
    fireEvent.click(screen.getByRole("radio", { name: "Recode into new variable" }));
    fireEvent.change(screen.getByLabelText("New variable"), { target: { value: "g" } });
    fireEvent.change(screen.getByLabelText("Recode rules"), { target: { value: "18..29 = 1" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect((await screen.findByRole("alert")).textContent).toContain("match no rule");
  });

  it("refuses to preview an empty condition value locally", async () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect((await screen.findByRole("alert")).textContent).toContain("give a value for age");
    expect(ops.previewDataTransform).not.toHaveBeenCalled();
  });
});
