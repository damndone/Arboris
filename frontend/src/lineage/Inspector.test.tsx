import "@testing-library/jest-dom/vitest";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Inspector } from "./Inspector";
import type { LineageNode, DecisionPoint } from "./types";

function node(overrides: Partial<LineageNode> = {}): LineageNode {
  return {
    id: "model:ols_1",
    kind: "model",
    display_label: "Primary OLS",
    summary: "OLS · HC1 · n = 32",
    created_at: "2026-05-19T10:23:45Z",
    parent_stage_id: null,
    branch_id: "main",
    trust: "ok",
    trust_reason: null,
    archived: false,
    payload_ref: "model_results/ols_1.json",
    decision_points: [],
    annotations: [],
    ...overrides,
  };
}

describe("Inspector", () => {
  it("renders title and eyebrow", () => {
    render(<Inspector node={node()} onClose={() => {}} />);
    expect(screen.getByText("Primary OLS")).toBeInTheDocument();
    expect(screen.getByText(/MODEL · model:ols_1/)).toBeInTheDocument();
  });

  it("renders About prose for MODEL kind", () => {
    render(<Inspector node={node()} onClose={() => {}} />);
    expect(screen.getByText(/OLS · HC1 · n = 32/)).toBeInTheDocument();
  });

  it('renders green "All clear" callout when no review needed and trust ok', () => {
    render(<Inspector node={node()} onClose={() => {}} />);
    expect(screen.getByText(/All clear/i)).toBeInTheDocument();
  });

  it('renders orange "Review required" when DPs need review', () => {
    const dp = (id: string): DecisionPoint => ({
      decision_id: id,
      decision_id_alias: [],
      selected: null,
      candidates: [],
      source: "system_default",
      contestability: {
        is_contestable: true,
        assumption_checks_needed: [],
        warnings: [],
        review_status: "needed",
      },
      reason: null,
    });
    render(
      <Inspector
        node={node({ decision_points: [dp("model_type_auto_select")] })}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/Review required/i)).toBeInTheDocument();
    expect(screen.getByText(/1 choice needs/i)).toBeInTheDocument();
  });

  it("renders red trust callout when trust=warning and no DP", () => {
    render(
      <Inspector
        node={node({ trust: "warning", trust_reason: "low n" })}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/Trust/)).toBeInTheDocument();
    expect(screen.getByText(/low n/)).toBeInTheDocument();
  });

  it("calls onClose when close button clicked", () => {
    const onClose = vi.fn();
    render(<Inspector node={node()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("has role=dialog and aria-labelledby", () => {
    render(<Inspector node={node()} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-labelledby");
  });
});
