import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildEstimatedEquation,
  equationLhs,
  EstimatedEquationSection,
} from "./EstimatedEquationSection";
import { LineageContext, type LineageContextValue } from "../../LineageContext";
import type { GraphViewModel, GraphViewNode } from "../../api/graphViewTypes";
import * as api from "../../../api";

afterEach(() => {
  vi.restoreAllMocks();
});

function olsResult(): api.ModelResult {
  return {
    model_id: "ols_1",
    model_type: "ols_robust",
    nobs: 120,
    r_squared: 0.9283,
    coefficients: {
      Intercept: {
        estimate: 1.5174906844239744,
        std_error: 0.04498728559476688,
        p_value_display: "< 0.001",
      },
      x1: { estimate: 1.8568725665749004, std_error: 0.05726314402442773 },
      x2: { estimate: -0.8453316786176757, std_error: 0.043781272713577145 },
    },
  };
}

describe("buildEstimatedEquation", () => {
  it("builds intercept + signed terms with tooltips from the coefficient table", () => {
    const eq = buildEstimatedEquation(olsResult(), "y");
    expect(eq).not.toBeNull();
    expect(eq!.lhs).toBe("y");
    expect(eq!.intercept?.coef).toBeCloseTo(1.5175, 3);
    expect(eq!.terms.map((t) => t.label)).toEqual(["x1", "x2"]);
    expect(eq!.terms[1].coef).toBeLessThan(0);
    expect(eq!.terms[0].tooltip).toContain("se 0.05726");
    expect(eq!.intercept?.tooltip).toContain("p < 0.001");
    expect(eq!.meta).toContain("n=120");
    expect(eq!.meta).toContain("R²=0.9283");
  });

  it("returns null when there is no coefficient table (CS/SA/dCDH effect bundles)", () => {
    expect(
      buildEstimatedEquation(
        { model_id: "cs_did_1", coefficients: {} } as api.ModelResult,
        "y",
      ),
    ).toBeNull();
  });

  it("renders the TWFE DID treatment dummy as the ATT and notes absorbed FE", () => {
    const eq = buildEstimatedEquation(
      {
        model_id: "did_1",
        model_type: "did",
        coefficients: {
          _did_D: { estimate: 0.42, std_error: 0.1 },
          market: { estimate: 0.05, std_error: 0.02 },
        },
      } as unknown as api.ModelResult,
      "y",
    );
    expect(eq!.intercept).toBeNull();
    expect(eq!.terms[0].label).toBe("D (ATT)");
    expect(eq!.meta).toContain("fixed effects absorbed");
  });

  it("uses link-function LHS for non-identity families", () => {
    expect(equationLhs("logit", "y")).toBe("logit(P(y=1))");
    expect(equationLhs("glm_binomial", "employed")).toBe("logit(P(employed=1))");
    expect(equationLhs("probit", "y")).toBe("probit(P(y=1))");
    expect(equationLhs("poisson_robust", "visits")).toBe("log(E[visits])");
    expect(equationLhs("ols_robust", "wage")).toBe("wage");
  });
});

describe("EstimatedEquationSection", () => {
  function modelNode(): GraphViewNode {
    return {
      id: "model:ols_1",
      nodeKey: "model:ols_1",
      raw: null,
      stage: "model",
      kind: "model",
      title: "Primary OLS",
      parentStageId: null,
      trust: "ok",
      decisions: [],
    };
  }

  function renderSection() {
    const model: GraphViewModel = {
      schemaVersion: 3,
      runId: "run-1",
      legacy: false,
      nodes: [modelNode()],
      edges: [],
      stats: { nodeCount: 1, edgeCount: 0, leafCount: 1, hasDpCount: 0 },
    };
    const ctx: LineageContextValue = {
      model,
      selectedKey: "model:ols_1",
      select: vi.fn(),
    };
    return render(
      <LineageContext.Provider value={ctx}>
        <EstimatedEquationSection node={modelNode()} />
      </LineageContext.Provider>,
    );
  }

  it("fetches the owner run and renders the fitted equation for this model id", async () => {
    // No ProjectRootProvider in this harness → the section takes the legacy
    // ?project_root= query fallback.
    const search = vi
      .spyOn(window, "location", "get")
      .mockReturnValue({
        ...window.location,
        search: "?project_root=/proj",
      } as Location);
    vi.spyOn(api, "fetchRunDetail").mockResolvedValue({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "t",
      y: "y",
      x: ["x1", "x2"],
      lineage: [],
      artifact_counts: {},
      errors: { issues: [] },
      model_results: [olsResult()],
    } as unknown as api.RunDetail);

    renderSection();

    await waitFor(() =>
      expect(screen.getByTestId("estimated-equation-section")).toBeInTheDocument(),
    );
    expect(api.fetchRunDetail).toHaveBeenCalledWith("/proj", "run-1");
    const eq = screen.getByTestId("estimated-equation");
    expect(eq.textContent).toContain("y = 1.517");
    expect(eq.textContent).toContain("+ 1.857·x1");
    expect(eq.textContent).toContain("− 0.8453·x2");
    search.mockRestore();
  });

  it("renders nothing when the run has no matching coefficient table", async () => {
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      search: "?project_root=/proj",
    } as Location);
    vi.spyOn(api, "fetchRunDetail").mockResolvedValue({
      run_id: "run-1",
      status: "completed",
      y: "y",
      model_results: [{ model_id: "other_model", coefficients: {} }],
    } as unknown as api.RunDetail);

    renderSection();

    await waitFor(() => expect(api.fetchRunDetail).toHaveBeenCalled());
    expect(screen.queryByTestId("estimated-equation-section")).toBeNull();
  });
});
