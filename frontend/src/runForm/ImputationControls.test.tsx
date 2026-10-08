import { expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ImputationControls } from "./ImputationControls";
import type { Capabilities } from "../capabilities/types";
import { capabilitiesFixture } from "../apiFixtures";

const caps_one: Capabilities = capabilitiesFixture({
  imputation_methods: [
    { key: "mice", label: "MICE (Multiple Imputation)", description: "" },
  ],
});

const caps_two: Capabilities = capabilitiesFixture({
  imputation_methods: [
    { key: "mice", label: "MICE", description: "" },
    { key: "knn", label: "KNN", description: "" },
  ],
});

test("with exactly one imputation method renders a checkbox", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={null} onChange={onChange} />);
  expect(screen.getByRole("checkbox", { name: /mice/i })).toHaveClass("imputation-controls__toggle");
  expect(screen.getByText(/MICE estimates plausible numeric values/i)).toBeInTheDocument();
});

test("with two+ methods renders a select", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_two} value={null} onChange={onChange} />);
  expect(screen.getByRole("combobox")).toBeInTheDocument();
});

test("checkbox emits the method key on change", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={null} onChange={onChange} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /mice/i }));
  expect(onChange).toHaveBeenCalledWith("mice");
});

test("checkbox emits null when unchecked", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={"mice"} onChange={onChange} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /mice/i }));
  expect(onChange).toHaveBeenCalledWith(null);
});

test("renders nothing when capabilities undefined or imputation_methods empty", () => {
  const { container, rerender } = render(
    <ImputationControls capabilities={undefined} value={null} onChange={() => {}} />,
  );
  expect(container.firstChild).toBeNull();

  rerender(
    <ImputationControls
      capabilities={capabilitiesFixture()}
      value={null}
      onChange={() => {}}
    />,
  );
  expect(container.firstChild).toBeNull();
});
