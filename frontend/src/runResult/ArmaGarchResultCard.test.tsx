import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ArmaGarchResultCard, type ArmaGarchArtifacts } from "./ArmaGarchResultCard";

const artifacts: ArmaGarchArtifacts = {
  report: {
    answer: "Selected ARMA(1,0)-GARCH(1,1).",
    estimation_semantics: { strategy: "joint", joint_likelihood: true },
    sample: { source_n: 120, training_n: 100, validation_n: 20 },
    scale: { transform: "log_return_pct", lag_unit: "trading observation" },
    acceptance: { overall_status: "accepted_with_warnings", dimensions: {} },
    warnings: ["NORMALITY_REJECTED"],
  },
  contract: {
    time_column: "date",
    value_column: "vix",
    transform: "log_return_pct",
    time_index_semantics: "business_or_trading_observations",
  },
  dataAudit: { source_unchanged: true, diagnostics: [] },
  meanCandidates: {
    candidates: [
      { candidate_id: "arma-p1-q0-c", p: 1, q: 0, aicc: 101.2, bic: 104.1, failure_code: null },
      { candidate_id: "arma-p2-q0-c", p: 2, q: 0, aicc: null, bic: null, failure_code: "ARMA_NOT_CONVERGED" },
    ],
  },
  volatilityCandidates: {
    searches: [{ candidates: [{ candidate_id: "variance-garch-p1-q1-normal", display_name: "GARCH(1,1)", aicc: 88.2, bic: 92.1, failure_code: null }] }],
  },
  diagnostics: { normality: { p_value: 0.01 }, arch_lm: { p_value: 0.2 } },
  metrics: { validation_n: 20, successful_forecast_n: 20, rmse: 1.2, pinball_loss: 0.3, interval_coverage: 0.9 },
  nextForecast: { target_time: null, conditional_mean: 0.2, conditional_volatility: 1.1, predictive_interval: "plugin_conditional" },
  comparison: { comparison_validation_n: 20, arma_garch: { rmse: 1.2 }, arma_only: { rmse: 1.4 } },
  conditionalSeries: { volatility: [null, 1.0, 1.2] },
  artifactManifest: { status: "complete", artifact_count_before_manifest: 30 },
};

describe("ArmaGarchResultCard", () => {
  it("renders an answer-first overview with honest forecast limitations", () => {
    render(<ArmaGarchResultCard artifacts={artifacts} />);
    expect(screen.getByText("Selected ARMA(1,0)-GARCH(1,1).")).toBeInTheDocument();
    expect(screen.getByText(/Joint likelihood/i)).toBeInTheDocument();
    expect(screen.getByText(/Next observation time is unknown/i)).toBeInTheDocument();
    expect(screen.getByText(/plug-in conditional/i)).toBeInTheDocument();
  });

  it("filters failed mean candidates without hiding the failure code", () => {
    render(<ArmaGarchResultCard artifacts={artifacts} />);
    fireEvent.click(screen.getByRole("tab", { name: "Mean Model Selection" }));
    expect(screen.getByText("arma-p1-q0-c")).toBeInTheDocument();
    expect(screen.getByText("arma-p2-q0-c")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("mean candidate status"), {
      target: { value: "failed" },
    });
    expect(screen.queryByText("arma-p1-q0-c")).not.toBeInTheDocument();
    expect(screen.getByText("ARMA_NOT_CONVERGED")).toBeInTheDocument();
  });

  it("shows locked ARMA-only comparison metrics", () => {
    render(<ArmaGarchResultCard artifacts={artifacts} />);
    fireEvent.click(screen.getByRole("tab", { name: "ARMA vs ARMA-GARCH" }));
    expect(screen.getByText(/20 common successful origins/i)).toBeInTheDocument();
    expect(screen.getByText("1.2000")).toBeInTheDocument();
    expect(screen.getByText("1.4000")).toBeInTheDocument();
  });

  it("does not invent semantics or locked comparison claims when artifacts are absent", () => {
    render(<ArmaGarchResultCard artifacts={{ report: { answer: "Partial result" } }} />);
    expect(screen.getByText(/Estimation semantics unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Next-forecast artifact is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/Intervals are/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "ARMA vs ARMA-GARCH" }));
    expect(screen.getByText(/comparison artifact is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/origins; transform, split/)).not.toBeInTheDocument();
  });
});
