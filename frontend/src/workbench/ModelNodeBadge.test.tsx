import { render, screen } from "@testing-library/react";
import { it, expect } from "vitest";
import { ModelNodeBadge, runShort, hashShort } from "./ModelNodeBadge";

it("shows readable time and keeps exact identity in collapsed Source", () => {
  render(
    <ModelNodeBadge runId="20260630_021506_881210_d5cbd8a7" nodeHash="bb21bce…" role="source" />,
  );
  expect(screen.getByText("02:15:06")).toBeVisible();
  expect(screen.getByText(/bb21b/)).not.toBeVisible();
  expect(screen.getByText("Source")).toBeVisible();
  expect(screen.getByText(/source/)).toBeInTheDocument();
});

it("extracts the HHMMSS run segment and 5-char hash", () => {
  expect(runShort("20260630_021506_881210_d5cbd8a7")).toBe("021506");
  expect(hashShort("bb21bce0deadbeef")).toBe("bb21b");
});

it("falls back to the whole run id when shape is unexpected", () => {
  expect(runShort("weirdid")).toBe("weirdid");
});

it("tags the badge with the rerun role", () => {
  render(<ModelNodeBadge runId="a_b" nodeHash="hhhhh" role="rerun" />);
  expect(screen.getByTestId("model-node-badge")).toHaveAttribute("data-role", "rerun");
});
