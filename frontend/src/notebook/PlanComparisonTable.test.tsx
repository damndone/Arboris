import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { canonicalOptionRevision } from "./fixtures/canonicalMocks";
import { PlanComparisonTable } from "./PlanComparisonTable";

describe("Plan comparison basis", () => {
  it("compares the fixed dimensions in order without inventing costs or checks", () => {
    const first = canonicalOptionRevision();
    render(<PlanComparisonTable options={[first, { ...first, option_id: "second", rationale: "Alternative question fit" }]} />);
    const table = screen.getByRole("table", { name: "Analysis plan comparison" });
    expect(within(table).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual([
      "Question fit", "Data support", "Assumptions", "Cost", "Domain practice",
    ]);
    expect(within(table).getByText("Alternative question fit")).toBeInTheDocument();
    expect(within(table).getAllByText("Not estimated")).toHaveLength(2);
    expect(within(table).getAllByText("Not independently established")).toHaveLength(2);
    expect(table).not.toHaveTextContent("p-value");
    expect(table).not.toHaveTextContent("R²");
    expect(screen.getByText(/historical options.*original evidence/i)).toBeInTheDocument();
  });

  it("retains exact evidence references and makes missing support visible", () => {
    const first = canonicalOptionRevision();
    render(<PlanComparisonTable options={[{ ...first, evidence_refs: [
      { evidence_id: "profile:source", result_hash: "sha256:record", source_refs: ["dataset:raw"] },
    ] }, { ...first, option_id: "unsupported", evidence_refs: [] }]} />);
    expect(screen.getByText("profile:source")).toHaveAttribute("title", "sha256:record · dataset:raw");
    expect(screen.getByText("No recorded comparison evidence")).toBeInTheDocument();
  });
});
