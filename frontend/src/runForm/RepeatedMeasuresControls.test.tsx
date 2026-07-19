import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RepeatedMeasuresControls, type RepeatedMeasuresOptions } from "./RepeatedMeasuresControls";

const initialOptions: RepeatedMeasuresOptions = {
  subject_id: "participant_id",
  time: "week",
  group: "arm",
  fit_method: "reml",
  random_slope: true,
};

describe("RepeatedMeasuresControls", () => {
  it("emits a complete typed model-options payload without server-owned binding facts", () => {
    const onChange = vi.fn();

    render(
      <RepeatedMeasuresControls
        columns={["participant_id", "week", "arm", "outcome"]}
        value={initialOptions}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Subject ID"), {
      target: { value: "outcome" },
    });

    expect(onChange).toHaveBeenLastCalledWith({
      subject_id: "outcome",
      time: "week",
      group: "arm",
      fit_method: "reml",
      random_slope: true,
    });
    expect(onChange.mock.lastCall?.[0]).not.toHaveProperty("model_options_binding");
  });

  it("strips an unexpected owner binding instead of carrying it through a control edit", () => {
    const onChange = vi.fn();
    const valueWithForgedBinding = {
      ...initialOptions,
      model_options_binding: { owner_model_id: "forged" },
    };

    render(
      <RepeatedMeasuresControls
        columns={["participant_id", "week", "arm", "outcome"]}
        value={valueWithForgedBinding}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByLabelText("Random slope"));

    expect(onChange).toHaveBeenLastCalledWith({
      subject_id: "participant_id",
      time: "week",
      group: "arm",
      fit_method: "reml",
      random_slope: false,
    });
  });
});
