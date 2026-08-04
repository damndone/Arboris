import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  FamilyEvidence,
  type FamilyModelResult,
} from "./FamilyEvidence";

const ordinalResult = {
  contract: "workbench.ordinal_logit.result.v1",
  schema_version: 1,
  model_id: "ordinal_logit_1",
  model_type: "ordinal_logit",
  outcome_levels: ["low", "middle", "high"],
  link: "logit",
  coefficients: {},
  odds_ratios: {
    education: { odds_ratio: 2.15, ci_lower: 1.4, ci_upper: 3.3 },
  },
  marginal_effects: [{
    variable: "education",
    average_effect_by_category: { low: -0.12, middle: 0.03, high: 0.09 },
  }],
  predicted_probabilities: [{
    row: 0,
    probabilities: { low: 0.2, middle: 0.5, high: 0.3 },
  }],
  diagnostic_artifacts: ["diagnostics_ordinal_logit_1"],
} as unknown as FamilyModelResult;

const multinomialResult = {
  contract: "workbench.multinomial_logit.result.v1",
  schema_version: 1,
  model_id: "multinomial_logit_1",
  model_type: "multinomial_logit",
  outcome_levels: ["blue", "red", "green"],
  base_category: "green",
  coefficients: {},
  relative_risk_ratios: {
    "red:education": { relative_risk_ratio: 1.8, ci_lower: 1.1, ci_upper: 2.9 },
  },
  predicted_probabilities: {
    blue: [0.2],
    red: [0.5],
    green: [0.3],
  },
  marginal_effects: [{
    variable: "education",
    "red:education": 0.08,
    "blue:education": -0.03,
  }],
} as unknown as FamilyModelResult;

const survivalResult = {
  schema_version: 1,
  model_id: "survival_cox_1",
  model_type: "survival_cox",
  coefficients: {},
  hazard_ratios: { treatment: 0.72 },
  survival_evidence_artifact: "survival_evidence",
} as unknown as FamilyModelResult;

const survivalEvidence = {
  contract: "workbench.survival.v1",
  model_type: "survival_cox",
  duration_column: "duration",
  event_column: "event",
  entry_column: null,
  nobs: 8,
  censoring: { events: 5, censored: 3 },
  time_to_event: { duration_column: "duration", event_column: "event", entry_column: null },
  kaplan_meier: [{ group: "all", time: 2, survival: 0.875, n_at_risk: 8 }],
  log_rank: { status: "computed", statistic: 3.2, p_value: 0.07, groups: ["control", "treated"] },
  risk_set: [{ time: 2, at_risk: 8, events: 1, censored: 0 }],
  schoenfeld: [{ variable: "treatment", time_correlation: -0.12, status: "computed", residuals: [] }],
} as const;

const quantileResult = {
  contract: "workbench.quantile_regression.result.v1",
  schema_version: 1,
  model_id: "quantile_regression_1",
  model_type: "quantile_regression",
  quantiles: [0.25, 0.5, 0.75],
  reference_quantile: 0.5,
  coefficients: {},
  fits: {
    "0.25": { quantile: 0.25, coefficients: { education: { estimate: 0.4, ci_lower: 0.2, ci_upper: 0.6 } } },
    "0.5": { quantile: 0.5, coefficients: { education: { estimate: 0.6, ci_lower: 0.3, ci_upper: 0.9 } } },
    "0.75": { quantile: 0.75, coefficients: { education: { estimate: 0.8, ci_lower: 0.4, ci_upper: 1.2 } } },
  },
  confidence_intervals: {
    "0.5": { education: [0.3, 0.9] },
  },
  bootstrap: {
    repetitions: 100,
    random_state: 7,
    successful_repetitions: { "0.5": 96 },
    intervals: { "0.5": { education: [0.35, 0.88] } },
  },
  cross_quantile_comparisons: [{
    term: "education",
    lower_quantile: 0.25,
    upper_quantile: 0.75,
    difference: 0.4,
    std_error: 0.16,
    p_value: 0.012,
  }],
} as unknown as FamilyModelResult;

describe("FamilyEvidence", () => {
  it("consumes serialized ordered and multinomial model packets plus ordinal diagnostics", () => {
    render(
      <FamilyEvidence
        modelResults={[ordinalResult, multinomialResult]}
        artifacts={{
          diagnostics_ordinal_logit_1: {
            contract: "workbench.ordinal_logit.diagnostics.v1",
            parallel_lines: {
              status: "computed",
              method: "cumulative_logit_slope_range",
              slope_ranges: { education: 0.31 },
              comparisons: [{ threshold: 1, coefficients: { education: 0.9 } }],
            },
          },
        }}
      />,
    );

    expect(screen.getByTestId("family-evidence-ordinal_logit_1")).toHaveTextContent("Odds ratios");
    expect(screen.getByTestId("family-evidence-ordinal_logit_1")).toHaveTextContent("2.15");
    expect(screen.getByTestId("family-evidence-ordinal_logit_1")).toHaveTextContent("Marginal effects");
    expect(screen.getByTestId("family-evidence-ordinal_logit_1")).toHaveTextContent("Predicted probabilities");
    expect(screen.getByTestId("family-evidence-ordinal_logit_1")).toHaveTextContent(/parallel-lines/i);
    expect(screen.getByTestId("family-evidence-multinomial_logit_1")).toHaveTextContent("Base category: green");
    expect(screen.getByTestId("family-evidence-multinomial_logit_1")).toHaveTextContent("Relative risk ratios");
    expect(screen.getByTestId("family-evidence-multinomial_logit_1")).toHaveTextContent("Predicted probabilities");
    expect(screen.getByTestId("family-evidence-multinomial_logit_1")).toHaveTextContent("Marginal effects");
  });

  it("consumes serialized survival and quantile packets without calculating missing evidence", () => {
    render(
      <FamilyEvidence
        modelResults={[survivalResult, quantileResult]}
        artifacts={{ survival_evidence: survivalEvidence }}
      />,
    );

    expect(screen.getByTestId("family-evidence-survival_cox_1")).toHaveTextContent("Events: 5");
    expect(screen.getByTestId("family-evidence-survival_cox_1")).toHaveTextContent("Censored: 3");
    expect(screen.getByTestId("family-evidence-survival_cox_1")).toHaveTextContent("Kaplan-Meier");
    expect(screen.getByTestId("family-evidence-survival_cox_1")).toHaveTextContent("Log-rank");
    expect(screen.getByTestId("family-evidence-survival_cox_1")).toHaveTextContent("Risk set");
    expect(screen.getByTestId("family-evidence-survival_cox_1")).toHaveTextContent("Schoenfeld");
    expect(screen.getByTestId("family-evidence-quantile_regression_1")).toHaveTextContent("Quantile 0.5");
    expect(screen.getByTestId("family-evidence-quantile_regression_1")).toHaveTextContent("Bootstrap");
    expect(screen.getByTestId("family-evidence-quantile_regression_1")).toHaveTextContent("100");
    expect(screen.getByTestId("family-evidence-quantile_regression_1")).toHaveTextContent("Cross-quantile");
  });

  it("shows an explicit degradation when a required survival artifact is absent", () => {
    render(<FamilyEvidence modelResults={[survivalResult]} artifacts={{}} />);

    expect(screen.getByTestId("family-evidence-survival_cox_1")).toHaveTextContent(
      "Survival evidence unavailable",
    );
    expect(screen.getByTestId("family-evidence-survival_cox_1")).toHaveTextContent(
      "generic coefficient table remains available",
    );
  });
});
