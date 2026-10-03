import { describe, expect, it } from "vitest";

import { describeInference, describeSuppressedInference } from "./inference";

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
