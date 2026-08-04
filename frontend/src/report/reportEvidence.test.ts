import { describe, expect, it } from "vitest";
import type { CitableFact } from "./factTable";
import {
  groupFacts,
  reportCapabilitiesForFacts,
  reportCapabilityManifestForFacts,
} from "./reportEvidence";

function fact(overrides: Partial<CitableFact>): CitableFact {
  return {
    id: "c1",
    node_key: "node:1",
    node_label: "Model",
    field: "metric:r_squared",
    label: "R squared",
    value: 0.86,
    ...overrides,
  };
}

describe("report evidence grouping", () => {
  it("groups current providers in a stable reader-facing order", () => {
    const groups = groupFacts([
      fact({ id: "c1", field: "param:covariance" }),
      fact({ id: "c2", field: "coef:age" }),
      fact({ id: "c3", field: "coef_p:age" }),
      fact({ id: "c4", field: "ts:forecast:rmse" }),
      fact({ id: "c5", field: "figure:plot:source.y" }),
      fact({ id: "c6", field: "post_estimation:step:joint_f" }),
      fact({ id: "c7", field: "future_provider:metric" }),
    ]);

    expect(groups.map((group) => group.id)).toEqual([
      "model-estimation",
      "diagnostics-robustness",
      "time-series",
      "figures",
      "post-estimation",
      "other",
    ]);
    expect(groups.find((group) => group.id === "other")?.facts[0].id).toBe("c7");
  });

  it("keeps human labels in the primary row while retaining raw field metadata", () => {
    const [group] = groupFacts([
      fact({ id: "c1", field: "metric:r_squared", label: "Model fit (R²)" }),
    ]);

    expect(group.facts[0]).toMatchObject({
      id: "c1",
      label: "Model fit (R²)",
      field: "metric:r_squared",
    });
  });

  it("does not mutate fact values while grouping", () => {
    const facts = [fact({ value: 0.86 })];
    const grouped = groupFacts(facts);

    expect(grouped[0].facts[0].value).toBe(0.86);
    expect(facts[0].value).toBe(0.86);
  });

  it("derives stable capability modules from provider groups", () => {
    const facts = [
      fact({ field: "sample:n", label: "N" }),
      fact({ id: "c2", field: "param:x", label: "X" }),
      fact({ id: "c3", field: "diagnostic:normality", label: "Normality" }),
      fact({ id: "c4", field: "ts:forecast:rmse", label: "RMSE" }),
      fact({ id: "c5", field: "post_estimation:joint_f", label: "Joint F" }),
      fact({ id: "c6", field: "figure:coef", label: "Coefficient plot" }),
    ];

    expect(reportCapabilitiesForFacts(facts)).toEqual([
      "data",
      "model.estimation",
      "diagnostics.robustness",
      "time_series",
      "post_estimation",
    ]);
  });

  it("emits a provider manifest without coupling the view to model names", () => {
    const manifest = reportCapabilityManifestForFacts([
      fact({ field: "coef:age" }),
      fact({ id: "c2", field: "diagnostic:normality" }),
    ]);

    expect(manifest).toEqual([
      expect.objectContaining({
        capability_id: "model.estimation",
        provider_id: "evidence.estimation.v1",
        availability: "available",
        report_modules: ["model-estimation"],
      }),
      expect.objectContaining({
        capability_id: "diagnostics.robustness",
        provider_id: "evidence.diagnostics.v1",
        report_modules: ["diagnostics-robustness"],
      }),
    ]);
  });
});
