import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PredictionControls } from "./PredictionControls";
import type { Capabilities } from "../capabilities/types";

const caps: Capabilities = {
  schema_version: 2, model_types: [], imputation_methods: [],
  prediction_models: [
    { key: "prediction_lasso", label: "Lasso" },
    { key: "prediction_ridge", label: "Ridge" },
  ],
  sampling_methods: [{ key: "smote", label: "SMOTE" }],
};

describe("PredictionControls", () => {
  it("reports enabling via the toggle", () => {
    const onEnabled = vi.fn();
    render(<PredictionControls capabilities={caps} enabled={false}
      modelType="" cvFolds={5} sampling=""
      onEnabled={onEnabled} onModelType={vi.fn()} onCvFolds={vi.fn()} onSampling={vi.fn()} />);
    fireEvent.click(screen.getByLabelText(/预测|prediction/i));
    expect(onEnabled).toHaveBeenCalledWith(true);
  });

  it("when enabled, reports algorithm selection", () => {
    const onModel = vi.fn();
    render(<PredictionControls capabilities={caps} enabled={true}
      modelType="prediction_lasso" cvFolds={5} sampling=""
      onEnabled={vi.fn()} onModelType={onModel} onCvFolds={vi.fn()} onSampling={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/algorithm|算法/i), { target: { value: "prediction_ridge" } });
    expect(onModel).toHaveBeenCalledWith("prediction_ridge");
  });

  it("hides detail controls when disabled", () => {
    render(<PredictionControls capabilities={caps} enabled={false}
      modelType="" cvFolds={5} sampling=""
      onEnabled={vi.fn()} onModelType={vi.fn()} onCvFolds={vi.fn()} onSampling={vi.fn()} />);
    expect(screen.queryByLabelText(/algorithm|算法/i)).toBeNull();
  });

  it("renders nothing when manifest has no prediction models", () => {
    const none: Capabilities = { schema_version: 2, model_types: [], imputation_methods: [] };
    const { container } = render(<PredictionControls capabilities={none} enabled={true}
      modelType="" cvFolds={5} sampling=""
      onEnabled={vi.fn()} onModelType={vi.fn()} onCvFolds={vi.fn()} onSampling={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it("requires an explicit data structure and exposes the grouped key", () => {
    const onStructure = vi.fn();
    const onGroup = vi.fn();
    render(<PredictionControls capabilities={caps} enabled={true}
      modelType="prediction_ridge" cvFolds={5} sampling=""
      columns={["y", "x", "firm", "year"]}
      dataStructure="grouped" groupColumn="firm" timeColumn=""
      onEnabled={vi.fn()} onModelType={vi.fn()} onCvFolds={vi.fn()} onSampling={vi.fn()}
      onDataStructure={onStructure} onGroupColumn={onGroup} onTimeColumn={vi.fn()} />);
    expect(screen.getByLabelText(/data structure|数据结构/i)).toHaveValue("grouped");
    fireEvent.change(screen.getByLabelText(/data structure|数据结构/i), {
      target: { value: "iid" },
    });
    expect(onStructure).toHaveBeenCalledWith("iid");
    fireEvent.change(screen.getByLabelText(/group column|分组列/i), {
      target: { value: "year" },
    });
    expect(onGroup).toHaveBeenCalledWith("year");
  });
});
