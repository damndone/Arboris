import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { Operation } from "../manualApi";
import { StepCard } from "./StepCard";
import type { Step } from "./steps";

afterEach(cleanup);

const models = [
  { run_id: "training-a", node_id: "native-result:forest", artifact_id: "forest", sha256: "a".repeat(64), model_type: "native_random_forest_regression" as const, label: "Demand · 80 training rows · 16 trees", predictors: ["price", "week"] },
  { run_id: "training-b", node_id: "native-result:forest", artifact_id: "forest", sha256: "b".repeat(64), model_type: "native_random_forest_regression" as const, label: "Demand · 120 training rows · 8 trees", predictors: ["price", "week"] },
  { run_id: "training-c", node_id: "native-result:forest", artifact_id: "forest", sha256: "c".repeat(64), model_type: "native_random_forest_classification" as const, label: "Churn · 120 training rows · 8 trees", predictors: ["price", "week"] },
];
const operation: Operation = {
  id: "prediction.native_forest_apply", name: "Apply saved forest", summary: "Predict new rows without refitting.",
  version: "v1", category: "prediction", blurb: "Predict new rows without refitting.",
  group: "prediction", group_label: "Prediction", group_order: 1,
  field_hints: {}, target_requirements: ["dataset_node"], confirmation_policy: "explicit",
  risk_level: "low", output_schema_ref: null, declaration_source: "native_research",
  capability_ids: ["prediction.native_forest_apply"], column_resolver: null,
  execution: { kind: "workflow", method: "POST", path: "/operations/execute" },
  availability: { status: "available", reason_code: "ready", message: "Ready" },
  saved_models: models,
  spec_schema: { type: "object", properties: { options: { type: "object", properties: {
    model_run_id: { type: "string" }, model_artifact_id: { type: "string" }, model_sha256: { type: "string" },
    prediction_column: { type: "string", default: "prediction" },
    probability_column: { type: "string", default: "probability" },
  }, required: ["model_run_id", "model_artifact_id", "model_sha256", "prediction_column"] } }, required: ["options"] },
};

function Editor({ saved = models, options = {} }: { saved?: typeof models; options?: Record<string, string> }) {
  const [step, setStep] = useState<Step>({ step_id: "score", operation_id: operation.id,
    spec: { input_mode: "frame", column_bindings: {}, options: { prediction_column: "demand_prediction", ...options } } });
  return <><StepCard step={step} index={0} steps={[step]} operations={[{ ...operation, saved_models: saved }]}
    onChange={setStep} onRemove={() => {}} /><output data-testid="spec">{JSON.stringify(step.spec)}</output></>;
}

it("binds the selected saved forest identity and preserves the prediction column", () => {
  render(<Editor />);
  fireEvent.change(screen.getByRole("combobox", { name: "Saved model" }), { target: { value: "1" } });
  expect(JSON.parse(screen.getByTestId("spec").textContent!).options).toEqual({
    prediction_column: "demand_prediction", model_run_id: "training-b", model_artifact_id: "forest", model_sha256: "b".repeat(64),
  });
  expect(screen.getByText("Required columns: price, week")).toBeTruthy();
  expect(screen.queryByLabelText("Step 1.options.model_sha256")).toBeNull();
});

it("shows a restored selection only when all saved identity fields match", () => {
  render(<Editor options={{ model_run_id: "training-a", model_artifact_id: "forest", model_sha256: "b".repeat(64) }} />);
  expect(screen.getByRole("combobox", { name: "Saved model" })).toHaveValue("");
  expect(screen.getByText(/previously selected model is no longer available/i)).toBeTruthy();
});

it("explains when no saved model is available without selecting another model", () => {
  render(<Editor saved={[]} />);
  expect(screen.getByRole("combobox", { name: "Saved model" })).toBeRequired();
  expect(screen.getByText(/no compatible saved forests/i)).toBeTruthy();
  expect(JSON.parse(screen.getByTestId("spec").textContent!).options).toEqual({ prediction_column: "demand_prediction" });
});

it("shows a binary classifier with both output columns and the fixed probability rule", () => {
  render(<Editor />);
  expect(screen.getByRole("option", { name: /Binary classification.*Churn/ })).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Saved model" }), { target: { value: "2" } });
  expect(JSON.parse(screen.getByTestId("spec").textContent!).options).toEqual({
    prediction_column: "demand_prediction", probability_column: "probability",
    model_run_id: "training-c", model_artifact_id: "forest", model_sha256: "c".repeat(64),
  });
  expect(screen.getByRole("textbox", { name: "Step 1.options.probability_column" })).toHaveValue("probability");
  expect(screen.getByText(/class 1 when.*0\.5/i)).toBeTruthy();
});

it("drops the classifier-only probability option when switching back to regression", () => {
  render(<Editor options={{ model_run_id: "training-c", model_artifact_id: "forest", model_sha256: "c".repeat(64), probability_column: "churn_probability" }} />);
  expect(screen.getByRole("textbox", { name: "Step 1.options.probability_column" })).toHaveValue("churn_probability");
  fireEvent.change(screen.getByRole("combobox", { name: "Saved model" }), { target: { value: "0" } });
  expect(screen.queryByRole("textbox", { name: "Step 1.options.probability_column" })).toBeNull();
  expect(JSON.parse(screen.getByTestId("spec").textContent!).options).toEqual({
    prediction_column: "demand_prediction", model_run_id: "training-a", model_artifact_id: "forest", model_sha256: "a".repeat(64),
  });
});

it("preserves explicit classifier output names when selecting another saved classifier", () => {
  render(<Editor options={{ probability_column: "churn_probability" }} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Saved model" }), { target: { value: "2" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Step 1.options.probability_column" }), { target: { value: "probability_of_churn" } });
  expect(JSON.parse(screen.getByTestId("spec").textContent!).options.probability_column).toBe("probability_of_churn");
  expect(JSON.parse(screen.getByTestId("spec").textContent!).options.prediction_column).toBe("demand_prediction");
});
