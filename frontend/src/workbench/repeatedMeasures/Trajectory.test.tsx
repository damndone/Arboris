import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Trajectory } from "./Trajectory";

describe("Trajectory", () => {
  it("renders only canonical server-provided group vectors", () => {
    render(<Trajectory context={{
      chart_type: "lmm_group_trajectory",
      time: [0, 1],
      groups: [
        { label: "control", observed_mean: [10, 9], fitted_mean: [10, 9.1] },
        { label: "treated", observed_mean: [10, 8], fitted_mean: [10, 8.2] },
      ],
    }} />);

    expect(screen.getByLabelText("lmm-group-trajectory")).toHaveTextContent("9.1");
    expect(screen.getAllByText("control")).toHaveLength(2);
  });

  it("renders no trajectory for the old series shape", () => {
    render(<Trajectory context={{
      chart_type: "lmm_group_trajectory",
      series: [{ group: "control", time: [0, 1], observed_mean: [10, 9], fitted_marginal_mean: [10, 9.1] }],
    }} />);

    expect(screen.queryByLabelText("lmm-group-trajectory")).toBeNull();
  });

  it.each([
    ["a non-increasing time vector", { chart_type: "lmm_group_trajectory", time: [0, 0], groups: [
      { label: "control", observed_mean: [10, 9], fitted_mean: [10, 9.1] },
      { label: "treated", observed_mean: [10, 8], fitted_mean: [10, 8.2] },
    ] }],
    ["a duplicate group", { chart_type: "lmm_group_trajectory", time: [0, 1], groups: [
      { label: "control", observed_mean: [10, 9], fitted_mean: [10, 9.1] },
      { label: "control", observed_mean: [10, 8], fitted_mean: [10, 8.2] },
    ] }],
    ["a non-canonical group count", { chart_type: "lmm_group_trajectory", time: [0, 1], groups: [
      { label: "control", observed_mean: [10, 9], fitted_mean: [10, 9.1] },
    ] }],
  ])("renders no trajectory for %s", (_label, context) => {
    render(<Trajectory context={context} />);

    expect(screen.queryByLabelText("lmm-group-trajectory")).toBeNull();
  });
});
