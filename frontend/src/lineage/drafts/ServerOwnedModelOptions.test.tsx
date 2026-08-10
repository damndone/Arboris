import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  ServerOwnedModelOptions,
  isServerOwnedObjectComplete,
  type ServerOwnedObjectControl,
} from "./ServerOwnedModelOptions";

const control: ServerOwnedObjectControl = {
  key: "model_options",
  kind: "object",
  label: "ETS specification",
  required: true,
  schema: {
    type: "object",
    required: ["time_column", "value_column", "error", "seasonal"],
    properties: {
      time_column: { type: "string", column_options: ["when", "value"] },
      value_column: { type: "string", column_options: ["when", "value"] },
      error: { enum: ["add", "mul"] },
      seasonal: { enum: ["add", "mul", null] },
      damped_trend: { type: "boolean" },
    },
    additionalProperties: false,
  },
};

describe("ServerOwnedModelOptions", () => {
  it("renders declared fields and emits typed values without a field switch", () => {
    const onChange = vi.fn();
    render(
      <ServerOwnedModelOptions
        control={control}
        value={{ seasonal: null }}
        onChange={onChange}
      />,
    );

    expect(screen.getByLabelText("time_column")).toBeInTheDocument();
    expect(screen.getByLabelText("error")).toBeInTheDocument();
    expect(screen.getByLabelText("damped_trend")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("time_column"), { target: { value: "when" } });
    fireEvent.click(screen.getByLabelText("damped_trend"));

    expect(onChange).toHaveBeenNthCalledWith(1, "time_column", "when");
    expect(onChange).toHaveBeenNthCalledWith(2, "damped_trend", true);
  });

  it("treats an explicitly declared null enum as a complete required value", () => {
    expect(
      isServerOwnedObjectComplete(control, {
        time_column: "when",
        value_column: "value",
        error: "add",
        seasonal: null,
      }),
    ).toBe(true);
  });
});
