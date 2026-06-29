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
