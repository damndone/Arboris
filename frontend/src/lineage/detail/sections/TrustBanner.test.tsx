// frontend/src/lineage/detail/sections/TrustBanner.test.tsx
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TrustBanner, _deriveCopy } from "./TrustBanner";
import type {
  DecisionViewModel,
  GraphViewNode,
} from "../../api/graphViewTypes";

function dp(overrides: Partial<DecisionViewModel> = {}): DecisionViewModel {
  return {
    id: "model_type_auto_select",
    question: "Which model type?",
    picked: "ols",
    alternatives: ["ols", "logit"],
    why: "y is continuous",
    evidence: [],
    reviewStatus: "not_needed",
    ...overrides,
  };
}

function node(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "n1",
    nodeKey: "n1",
    raw: null,
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-22T00:00:00Z",
    ...overrides,
  };
}

describe("TrustBanner", () => {
  describe("_deriveCopy", () => {
    it("returns null for ok-trust + no decisions needing review", () => {
      expect(_deriveCopy(node())).toBeNull();
    });

    it("review-required wins over trust=review (precedence)", () => {
      const n = node({
        trust: "review", // would trigger "review-suggested" alone
        decisions: [dp({ reviewStatus: "needed" })],
      });
      expect(_deriveCopy(n)?.variant).toBe("review-required");
    });

    it("review-required body uses dpRegistry-derived title", () => {
      const n = node({
        decisions: [dp({ id: "model_type_auto_select", reviewStatus: "needed" })],
      });
      const copy = _deriveCopy(n);
      expect(copy?.body).toMatch(/1 choice needs confirmation:/);
      // dpRegistry title for model_type_auto_select is lowercased in the body
      expect(copy?.body.toLowerCase()).toContain("model type");
    });

    it("multi-DP review-required pluralises + joins with 'and'", () => {
      const n = node({
        decisions: [
          dp({ id: "model_type_auto_select", reviewStatus: "needed" }),
          dp({ id: "ols_default_robust_se", reviewStatus: "failed" }),
        ],
      });
      const copy = _deriveCopy(n);
      expect(copy?.body).toMatch(/2 choices need confirmation:/);
      expect(copy?.body).toContain(" and ");
    });

    it("trust=review (no DPs needing review) → 'Review suggested'", () => {
      const copy = _deriveCopy(node({ trust: "review" }));
      expect(copy?.variant).toBe("review-suggested");
      expect(copy?.title).toBe("Review suggested");
      expect(copy?.token).toBe("review");
    });

    it("trust=review with trustReason uses the reason as body", () => {
      const copy = _deriveCopy(
        node({ trust: "review", trustReason: "Default model type chosen." }),
      );
      expect(copy?.body).toBe("Default model type chosen.");
    });

    it("trust=caution → 'Caution' variant with --caution token", () => {
      const copy = _deriveCopy(node({ trust: "caution" }));
      expect(copy?.variant).toBe("caution");
      expect(copy?.title).toBe("Caution");
      expect(copy?.token).toBe("caution");
    });

    it("trust=caution with trustReason uses it verbatim", () => {
      const copy = _deriveCopy(
        node({ trust: "caution", trustReason: "Logit fitted to >2 levels." }),
      );
      expect(copy?.body).toBe("Logit fitted to >2 levels.");
    });
  });

  describe("render", () => {
    it("renders nothing when shouldRender false-like state (defensive null)", () => {
      const { container } = render(<TrustBanner node={node()} />);
      expect(container.firstChild).toBeNull();
    });

    it("renders aria-live=polite + role=status for screen readers", () => {
      render(<TrustBanner node={node({ trust: "review" })} />);
      const banner = screen.getByRole("status");
      expect(banner.getAttribute("aria-live")).toBe("polite");
    });

    it("review-required variant exposes data-testid for downstream assertions", () => {
      render(
        <TrustBanner
          node={node({ decisions: [dp({ reviewStatus: "needed" })] })}
        />,
      );
      expect(screen.getByTestId("trust-banner-review-required")).toBeInTheDocument();
    });

    it("caution variant renders title and body", () => {
      render(
        <TrustBanner
          node={node({ trust: "caution", trustReason: "manual confirm" })}
        />,
      );
      expect(screen.getByText("Caution")).toBeInTheDocument();
      expect(screen.getByText("manual confirm")).toBeInTheDocument();
    });
  });
});
