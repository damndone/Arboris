import { expect, test, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ModelTypeSelect } from "./ModelTypeSelect";
import type { Capabilities } from "../capabilities/types";
import { capabilitiesFixture } from "../apiFixtures";

const capabilities: Capabilities = capabilitiesFixture({
  model_types: [
    { key: "auto", label: "Auto (infer from y)", group: "auto", description: "" },
    { key: "ols", label: "OLS (linear)", group: "Linear", description: "" },
    { key: "logit", label: "Logit", group: "Binary", description: "" },
    { key: "poisson", label: "Poisson", group: "Count", description: "" },
    { key: "panel_ols", label: "Panel OLS", group: "Panel", description: "" },
  ],
});

test("renders model types from capabilities grouped by group", () => {
  render(<ModelTypeSelect value="auto" onChange={() => {}} capabilities={capabilities} />);

  const select = screen.getByRole("combobox", { name: "model type" });
  expect(within(select).getByRole("option", { name: "OLS (linear)" })).toHaveValue("ols");
  expect(within(select).getByRole("group", { name: "Linear" })).toBeInTheDocument();
  expect(within(select).getByRole("group", { name: "Binary" })).toBeInTheDocument();
});

test("emits the selected model type key", () => {
  const onChange = vi.fn();
  render(<ModelTypeSelect value="auto" onChange={onChange} capabilities={capabilities} />);

  fireEvent.change(screen.getByRole("combobox", { name: "model type" }), {
    target: { value: "panel_ols" },
  });

  expect(onChange).toHaveBeenCalledWith("panel_ols");
});

test("falls back to auto while capabilities are loading", () => {
  render(<ModelTypeSelect value="auto" onChange={() => {}} capabilities={undefined} />);

  expect(screen.getByRole("option", { name: "Auto (infer from y)" })).toHaveValue("auto");
  expect(screen.queryByRole("option", { name: "OLS (linear)" })).not.toBeInTheDocument();
});
