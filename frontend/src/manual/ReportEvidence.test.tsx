import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ReportReadingView, factValue } from "./ReportEvidence";
import type { Draft } from "./manualApi";
const fact = { id: "f_x", field: "coefficient/x/p_value", label: "coefficient · x · p_value", value: 0, source: { run_id: "run" } } as Draft["facts"][number];
it("formats exact generated evidence without changing the raw fact", () => {
  render(<ReportReadingView text="- coefficient · x · p_value: 0 [[c:f_x]]" facts={[fact]}/>);
  expect(screen.getByText("< 0.001")).toBeVisible();
  expect(screen.getByText(/Exact value: 0/)).not.toBeVisible();
  expect(fact.value).toBe(0);
});
it("handles Python float representations in actual generated drafts", () => {
  render(<ReportReadingView text={"- coefficient · x · p_value: 0.0 [[c:f_x]]\n- coefficient · x · p_value: 1e-08 [[c:f_small]]"} facts={[fact, {...fact, id: "f_small", value: 1e-8}]}/>);
  expect(screen.getAllByText("< 0.001")).toHaveLength(2);
});
it("never replaces an edited interpretation or unknown citation with a stored fact", () => {
  render(<ReportReadingView text="- My own interpretation: 0 [[c:f_x]]" facts={[fact]}/>);
  expect(screen.getByText("- My own interpretation: 0 [[c:f_x]]")).toBeVisible();
});
it("distinguishes missing, false and numerical zero", () => {
  expect(factValue({...fact, value: null})).toBe("Not reported");
  expect(factValue({...fact, value: false})).toBe("No");
  expect(factValue({...fact, field: "estimate", value: 0})).toBe("0");
});

it("moves generated internal identifiers into expandable technical evidence", () => {
 const internal = {...fact, field: "coefficient/x/result_id", label: "coefficient · x · result_id", value: "coef:private-id"};
 render(<ReportReadingView text="- coefficient · x · result_id: coef:private-id [[c:f_x]]" facts={[internal]}/>);
 expect(screen.getByText("Methods and technical evidence (1)")).toBeVisible();
 expect(screen.getByText("coef:private-id")).not.toBeVisible();
});
