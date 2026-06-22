import { render, screen } from "@testing-library/react";
import { DCDHControls, type DCDHValue } from "./DCDHControls";

const base: DCDHValue = { entity: "", time: "", treatmentPath: "", clusterVar: "" };

test("renders entity/time/treatment/cluster selectors", () => {
  render(<DCDHControls value={base} columns={["id", "year", "d", "x1"]} onChange={() => {}} />);
  expect(screen.getByLabelText("dcdh-entity")).toBeInTheDocument();
  expect(screen.getByLabelText("dcdh-time")).toBeInTheDocument();
  expect(screen.getByLabelText("dcdh-treatment-path")).toBeInTheDocument();
  expect(screen.getByLabelText("dcdh-cluster-var")).toBeInTheDocument();
});

test("shows a pre-check note (backend diagnostics authoritative)", () => {
  render(<DCDHControls value={base} columns={["id", "year", "d"]} onChange={() => {}} />);
  expect(screen.getByLabelText("dcdh-precheck-note").textContent).toMatch(/pre-check/i);
});
