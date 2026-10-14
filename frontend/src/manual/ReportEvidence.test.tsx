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
  // The person's words stay; the citation becomes a source marker, and the
  // stored p-value is not substituted for their "0".
  expect(screen.getByRole("listitem")).toHaveTextContent(/My own interpretation: 0\s*source/);
  expect(screen.queryByText("< 0.001")).toBeNull();
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

it("keeps generated model ownership identifiers out of the reading surface", () => {
 const internal = {...fact,field:"post_estimation/lincom/model_run_id",label:"post estimation · model run id",value:"run-internal"};
 render(<ReportReadingView text="- post estimation · model run id: run-internal [[c:f_x]]" facts={[internal]}/>);
 expect(screen.getByText("run-internal")).not.toBeVisible();
});

it("reads a drafted report: headings, lists and values filled from the evidence", () => {
  const estimate = { ...fact, id: "f_e", field: "coefficient/x/estimate", label: "coefficient · x · estimate", value: 2564.322 };
  const text = "# Analysis report\n\n## ols\n\nModel of **wage**.\n\n- **x**: [[v:f_e]] (p [[v:f_x]])\n- gone: [[v:f_missing]]";
  render(<ReportReadingView text={text} facts={[fact, estimate]} />);
  expect(screen.getByRole("heading", { name: "Analysis report" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "ols" })).toBeVisible();
  const [first, second] = screen.getAllByRole("listitem");
  expect(first).toHaveTextContent("x: 2,564 (p < 0.001)");
  expect(screen.getByText("2,564")).toHaveAttribute("title", expect.stringContaining("exact value 2564.322"));
  expect(second).toHaveTextContent("gone: value unavailable");
  expect(screen.queryByText(/\[\[v:/)).toBeNull();
});

it("a marker may name its fact by a unique prefix, never an ambiguous one", async () => {
  const { resolveFact } = await import("./ReportEvidence");
  const a = { ...fact, id: "f_abcdef1234aa" };
  const b = { ...fact, id: "f_abcdef1234bb" };
  const byId = new Map([[a.id, a], [b.id, b]]);
  expect(resolveFact("f_abcdef1234a", byId)).toBe(a);
  expect(resolveFact("f_abcdef12", byId)).toBeUndefined();
  expect(resolveFact("f_abc", byId)).toBeUndefined();
});
