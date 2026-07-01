import { render, screen } from "@testing-library/react";
import { RoleGroups } from "./RoleGroups";

it("shows role headers and marks dropped focal", () => {
  render(
    <RoleGroups
      groups={[
        { role: "outcome", columns: ["y"], dropped: new Set() },
        { role: "focal", columns: ["x1"], dropped: new Set(["x1"]) },
      ]}
    />,
  );
  expect(screen.getByText("Outcome Variable (Y)")).toBeInTheDocument();
  expect(screen.getByText(/x1/)).toHaveAttribute("data-dropped", "true");
});

it("marks unit/time/cluster groups as dashed", () => {
  render(
    <RoleGroups
      groups={[{ role: "cluster", columns: ["firm"], dropped: new Set() }]}
    />,
  );
  const group = screen.getByText("Cluster (inference)").closest("[data-role]");
  expect(group).toHaveAttribute("data-edge", "dashed");
});
