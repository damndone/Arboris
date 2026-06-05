import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { ImputationSummary } from "./ImputationSummary";
import sample from "../../../tests/contracts/imputation_summary.mice.sample.json";

test("renders core fields from a MICE summary", () => {
  render(<ImputationSummary summary={sample as never} />);
  expect(screen.getByText(/MICE/i)).toBeInTheDocument();
  expect(screen.getByText(/17/)).toBeInTheDocument(); // rows_imputed
  expect(screen.getByText(/education/)).toBeInTheDocument();
  expect(screen.getByText(/imputed_dataset/)).toBeInTheDocument();
});

test("renders nothing if summary is undefined", () => {
  const { container } = render(<ImputationSummary summary={undefined} />);
  expect(container.firstChild).toBeNull();
});
