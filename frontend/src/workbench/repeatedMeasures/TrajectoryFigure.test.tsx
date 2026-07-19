import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrajectoryFigure } from "./TrajectoryFigure";

describe("TrajectoryFigure", () => {
  it("renders server-provided drawing paths without calculating a trajectory", () => {
    render(
      <TrajectoryFigure
        context={{
          title: "Group trajectory",
          aria_label: "Estimated group trajectory",
          paths: [
            { id: "control", label: "Control", d: "M0 10 L20 8" },
            { id: "treated", label: "Treated", d: "M0 10 L20 3" },
          ],
        }}
      />,
    );

    expect(screen.getByText("Group trajectory")).toBeInTheDocument();
    expect(screen.getByLabelText("Estimated group trajectory")).toBeInTheDocument();
    expect(screen.getByTestId("trajectory-treated")).toHaveAttribute("d", "M0 10 L20 3");
  });
});
