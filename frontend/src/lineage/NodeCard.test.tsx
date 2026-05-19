import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NodeCard } from "./NodeCard";
import type { DecisionPoint, LineageNode, ReviewStatus } from "./types";

function n(overrides: Partial<LineageNode> = {}): LineageNode {
  return {
    id: "n1",
    kind: "model",
    display_label: "Primary OLS",
    summary: "OLS · HC1 · n = 32",
    created_at: "2026-05-19T00:00:00Z",
    parent_stage_id: null,
    branch_id: "main",
    trust: "ok",
    trust_reason: null,
    archived: false,
    payload_ref: null,
    decision_points: [],
    annotations: [],
    ...overrides,
  };
}

function dp(review: ReviewStatus = "needed"): DecisionPoint {
  return {
    decision_id: "d1",
    decision_id_alias: [],
    selected: "x",
    candidates: [],
    source: "system_default",
    contestability: {
      is_contestable: true,
      assumption_checks_needed: [],
      warnings: [],
      review_status: review,
    },
    reason: null,
  };
}

describe("NodeCard", () => {
  it("renders title and summary", () => {
    render(<NodeCard data={{ node: n() }} selected={false} />);
    expect(screen.getByText("Primary OLS")).toBeInTheDocument();
    expect(screen.getByText("OLS · HC1 · n = 32")).toBeInTheDocument();
  });

  it("hides second line when summary is null", () => {
    render(<NodeCard data={{ node: n({ summary: null }) }} selected={false} />);
    expect(screen.queryByTestId("node-summary")).toBeNull();
  });

  it("shows ⚠ Review pill when review_count > 0", () => {
    render(
      <NodeCard
        data={{ node: n({ decision_points: [dp(), dp()] }) }}
        selected={false}
      />,
    );
    expect(screen.getByText(/Review · 2/)).toBeInTheDocument();
  });

  it("shows trust pill when trust=warning and no DP needs review", () => {
    render(<NodeCard data={{ node: n({ trust: "warning" }) }} selected={false} />);
    expect(screen.getByText(/warning/i)).toBeInTheDocument();
  });

  it("shows no pill when clean", () => {
    render(<NodeCard data={{ node: n() }} selected={false} />);
    expect(screen.queryByTestId("node-pill")).toBeNull();
  });

  it("applies selected class when selected", () => {
    const { container } = render(
      <NodeCard data={{ node: n() }} selected={true} />,
    );
    expect(container.querySelector(".ln-node--selected")).toBeInTheDocument();
  });
});
