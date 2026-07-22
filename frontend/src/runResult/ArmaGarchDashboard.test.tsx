import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { ArmaGarchDashboard } from "./ArmaGarchDashboard";
import type { ArmaGarchArtifacts } from "./ArmaGarchResultCard";

function artifacts(): ArmaGarchArtifacts {
  return {
    report: {
      answer: "Selected arma-p1-q0-c with GARCH(1,1); acceptance is accepted.",
      estimation_semantics: { joint_likelihood: false },
      sample: { source_n: 320, training_n: 279, validation_n: 40 },
      scale: { transform: "log_return_pct", lag_unit: "trading observation" },
      warnings: [],
      acceptance: {
        overall_status: "accepted",
        dimensions: {
          data_readiness: { status: "accepted" },
          mean_adequacy: { status: "accepted" },
          volatility_adequacy: { status: "accepted" },
          distribution_adequacy: { status: "accepted_with_warnings" },
          forecast_validation: { status: "accepted" },
          volatility_value_added: { status: "accepted" },
        },
      },
    },
    contract: {
      time_column: "trade_date",
      value_column: "price",
      time_index_semantics: "business_or_trading_observations",
      transform: "log_return_pct",
    },
    dataAudit: { source_unchanged: true },
    meanCandidates: {
      candidates: [
        { candidate_id: "arma-p1-q0-c", p: 1, q: 0, aicc: 541.4268, bic: 552.2331 },
      ],
    },
    volatilityCandidates: {
      searches: [
        { candidates: [{ candidate_id: "garch-1-1", display_name: "GARCH(1,1)", aicc: 3434, bic: 3457 }] },
      ],
    },
    diagnostics: { normality: { p_value: 0.03 }, arch_lm: { p_value: 0.41 } },
    metrics: {
      successful_forecast_n: 40,
      validation_n: 40,
      rmse: 0.4433,
      pinball_loss: 0.0385,
      interval_coverage: 0.946,
    },
    nextForecast: {
      conditional_mean: -0.0037,
      conditional_volatility: 0.4183,
      predictive_interval: "plugin_conditional",
      target_time: null,
    },
    comparison: {
      comparison_validation_n: 40,
      arma_garch: { rmse: 0.4433, pinball_loss: 0.0385 },
      arma_only: { rmse: 0.4461, pinball_loss: 0.048 },
    },
    conditionalSeries: { volatility: [0.1, 0.2, 0.3] },
    artifactManifest: { status: "complete", artifact_count_before_manifest: 30 },
  };
}

test("shows every section at once with no tab strip", () => {
  render(<ArmaGarchDashboard artifacts={artifacts()} />);

  // No tab-switching UI at all.
  expect(screen.queryAllByRole("tab")).toHaveLength(0);

  // All nine section headings are simultaneously present.
  for (const heading of [
    "Overview",
    "Data & Transformation",
    "Mean Model Selection",
    "Volatility Selection",
    "Diagnostics",
    "Forecast Validation",
    "Conditional Volatility",
    "ARMA vs ARMA-GARCH",
    "Reproducibility",
  ]) {
    expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
  }

  // Content from sections that used to be behind different tabs is co-visible.
  expect(screen.getByText(/Selected arma-p1-q0-c/)).toBeTruthy();
  expect(screen.getByText("arma-p1-q0-c")).toBeTruthy();
  expect(screen.getByText("GARCH(1,1)")).toBeTruthy();
  expect(screen.getByText("320 / 279 / 40")).toBeTruthy();
});

test("renders the six acceptance dimensions as chips", () => {
  render(<ArmaGarchDashboard artifacts={artifacts()} />);
  const chips = screen.getByTestId("arma-garch-acceptance-chips");
  for (const dimension of [
    "data readiness",
    "mean adequacy",
    "volatility adequacy",
    "distribution adequacy",
    "forecast validation",
    "volatility value added",
  ]) {
    expect(chips.textContent?.toLowerCase()).toContain(dimension);
  }
});

test("keeps the honest statistical labelling invariants", () => {
  const { container } = render(<ArmaGarchDashboard artifacts={artifacts()} />);
  const body = container.textContent ?? "";
  expect(body).not.toMatch(/VaR/);
  expect(body.toLowerCase()).not.toContain("composite");
  expect(body).toMatch(/plug-in conditional/);
  expect(body).toMatch(/exclude parameter uncertainty/);
  // Sequential must not be mislabelled as joint.
  expect(body).toMatch(/Sequential two-stage likelihood/);
});

test("renders nothing without a report artifact", () => {
  const { container } = render(<ArmaGarchDashboard artifacts={{}} />);
  expect(container.firstChild).toBeNull();
});
