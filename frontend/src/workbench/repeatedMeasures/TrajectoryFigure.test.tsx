import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrajectoryFigure } from "./TrajectoryFigure";

describe("TrajectoryFigure", () => {
  it("renders a server-provided trajectory fact table without calculating values", () => {
    render(
      <TrajectoryFigure
        context={{
          chart_type: "lmm_group_trajectory",
          time: [0, 1],
          groups: [
            {
              label: "control",
              observed_mean: [10, 8],
              fitted_mean: [10, 8.1],
            },
            {
              label: "treated",
              observed_mean: [10, 3],
              fitted_mean: [10, 3.2],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("组别轨迹")).toBeInTheDocument();
    expect(screen.getByLabelText("组别轨迹数据表")).toBeInTheDocument();
    expect(screen.getByText("3.2")).toBeInTheDocument();
  });
});
