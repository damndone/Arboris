import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { ModelNodeInspector } from "./ModelNodeInspector";

test("saves full params with base_draft_hash", () => {
  const onSave = vi.fn();
  render(
    <ModelNodeInspector
      draftHash="h1"
      node={{
        node_id: "model_1",
        node_type: "model",
        model_family: "regression",
        model_type: "ols",
        schema_id: "ols@v1",
        editable_schema: [
          {
            key: "model_type",
            kind: "select",
            label: "Model",
            value: "ols",
            options: ["ols", "logit"],
          },
        ],
        editable_schema_hash: "schema",
        source_ref: {},
        source_params: { model_type: "ols" },
        params: { model_type: "ols" },
      }}
      onSave={onSave}
    />,
  );

  fireEvent.change(screen.getByLabelText("Model"), { target: { value: "logit" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  expect(onSave).toHaveBeenCalledWith({
    model_node_id: "model_1",
    base_draft_hash: "h1",
    params: { model_type: "logit" },
  });
});

test("exposes a focal_x multiselect control and saves it", () => {
  const onSave = vi.fn();
  render(
    <ModelNodeInspector
      draftHash="h"
      node={{
        node_type: "model",
        node_id: "m",
        model_type: "ols",
        schema_id: "s",
        params: { focal_x: [] },
        source_params: { focal_x: [] },
        editable_schema: [
          {
            key: "focal_x",
            kind: "multiselect",
            label: "Focal X",
            options: ["education", "age"],
            value: [],
          },
        ],
      } as never}
      onSave={onSave}
    />,
  );
  fireEvent.click(screen.getByLabelText("education"));
  fireEvent.click(screen.getByText("Save changes"));
  expect(onSave).toHaveBeenCalledWith(
    expect.objectContaining({
      params: expect.objectContaining({ focal_x: ["education"] }),
    }),
  );
});

test("shows a changed-fields summary vs source params (§6.5)", () => {
  render(
    <ModelNodeInspector
      draftHash="h1"
      node={{
        node_id: "model_1",
        node_type: "model",
        model_family: "regression",
        model_type: "ols",
        schema_id: "ols@v1",
        editable_schema: [
          { key: "covariance", kind: "select", label: "Covariance", value: "",
            options: ["", "robust", "clustered"] },
        ],
        editable_schema_hash: "schema",
        source_ref: {},
        source_params: { covariance: "" },
        params: { covariance: "" },
      }}
      onSave={vi.fn()}
    />,
  );

  expect(screen.getByTestId("changed-fields-summary")).toHaveTextContent(/no changes/i);

  fireEvent.change(screen.getByLabelText("Covariance"), { target: { value: "robust" } });
  const summary = screen.getByTestId("changed-fields-summary");
  expect(summary).toHaveTextContent("covariance");
  expect(summary).toHaveTextContent(/robust/);
});

test("keeps the OLS Agent envelope out of the human covariance editor", () => {
  render(
    <ModelNodeInspector
      draftHash="h1"
      node={{
        node_id: "model_1",
        node_type: "model",
        model_family: "regression",
        model_type: "ols",
        schema_id: "ols@v1",
        editable_schema: [
          {
            key: "covariance",
            kind: "select",
            label: "Covariance",
            value: "robust",
            options: ["robust", "clustered", "unadjusted"],
          },
          {
            key: "model_options",
            kind: "object",
            label: "OLS model options",
            value: { covariance: "robust" },
          } as never,
        ],
        editable_schema_hash: "schema",
        source_ref: {},
        source_params: {
          covariance: "robust",
          model_options: { covariance: "robust" },
        },
        params: {
          covariance: "robust",
          model_options: { covariance: "robust" },
        },
      }}
      onSave={vi.fn()}
    />,
  );

  expect(screen.getByLabelText("Covariance")).toBeInTheDocument();
  expect(screen.queryByText("OLS model options")).not.toBeInTheDocument();
});
