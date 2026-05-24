import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GraphTooltip } from "./GraphTooltip";
import type { LineageNode } from "../types";

const node: LineageNode = {
  id: "n1",
  kind: "model",
  display_label: "Primary OLS",
  summary: "OLS · n = 32",
  created_at: "",
  parent_stage_id: null,
  branch_id: "main",
  trust: "ok",
  trust_reason: null,
  archived: false,
  payload_ref: null,
  decision_points: [
    {
      decision_id: "d1",
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
    },
  ],
  annotations: [],
};

describe("GraphTooltip", () => {
  it("renders nothing when invisible", () => {
    const { container } = render(<GraphTooltip node={node} visible={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders title, summary, review count and CTA when visible", () => {
    render(<GraphTooltip node={node} visible={true} />);
    expect(screen.getByText("Primary OLS")).toBeInTheDocument();
    expect(screen.getByText("OLS · n = 32")).toBeInTheDocument();
    expect(screen.getByText("1 choice needs review")).toBeInTheDocument();
    expect(screen.getByText("Tap to inspect")).toBeInTheDocument();
  });
});
