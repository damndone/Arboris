import { describe, expect, it } from "vitest";

import { describeInference, describeSuppressedInference, nobsBasis } from "./inference";

describe("describeInference", () => {
  it("names clusters and t(G - 1) for clustered OLS", () => {
    expect(describeInference({
      covariance_evidence: {
        covariance: "clustered", cluster_count: 18, effective_df: 17, inference_distribution: "t",
        inference_version: "workbench.inference.v2",
      },
    })).toBe("Standard errors: Cluster-robust (CR1) · Clusters: 18 · Inference: t(17)");
  });

  it("names HC1 and t(N - K) for robust OLS", () => {
    expect(describeInference({
      inference_config: { covariance: "robust", effective_df: 296, inference_distribution: "t", inference_version: "v2" },
    })).toBe("Standard errors: Robust (HC1) · Inference: t(296)");
  });

  it("marks a result computed before inference engine v2", () => {
    expect(describeInference({
      covariance_evidence: { covariance: "robust", effective_df: 296, inference_distribution: "normal" },
    })).toBe("Standard errors: Robust (HC1) · Inference: z (legacy asymptotic; rerun for finite-sample t)");
  });

  it("names the kernel, lag, its rule and the time order for Newey-West", () => {
    expect(describeInference({
      covariance_evidence: {
        covariance: "hac", effective_df: 147, inference_distribution: "t", inference_version: "workbench.inference.v2",
        hac: { kernel: "bartlett", lags: 4, lag_rule: "floor(4 * (T / 100) ** (2 / 9)) (Newey and West 1994)", time_order: "year" },
      },
    })).toBe(
      "Standard errors: Newey–West (HAC) · Bartlett kernel, lag 4 (Newey–West 1994 rule), ordered by year · Inference: t(147)",
    );
  });

  it("names the pooling rule for a multiple-imputation result", () => {
    expect(describeInference({
      multiple_imputation: { m: 5 },
      covariance_evidence: {
        covariance: "robust", effective_df: null, inference_distribution: "t", df_method: "barnard_rubin",
        inference_version: "workbench.inference.v2",
      },
    })).toBe(
      "Standard errors: Robust (HC1) · Inference: t, Barnard–Rubin df per coefficient · " +
        "Pooled from m = 5 imputations (Rubin's rules)",
    );
  });

  it("says nothing when a result records no inference", () => {
    expect(describeInference({ model_type: "logit" })).toBeNull();
  });
});

describe("describeSuppressedInference", () => {
  it("states why inference is withheld", () => {
    expect(describeSuppressedInference({ inference_suppressed: { check_id: "fit.perfect", reason: "The model fits the data exactly." } }))
      .toBe("Inference not shown: The model fits the data exactly.");
    expect(describeSuppressedInference({})).toBeNull();
  });
});

describe("nobsBasis", () => {
  it("says when n counts units", () => {
    expect(nobsBasis({ nobs: 12, nobs_basis: "units", n_rows: 120 })).toBe(" units (120 rows)");
    expect(nobsBasis({ nobs: 300 })).toBe("");
  });
});
