import { describe, it, expect } from "vitest";
import { DP_REGISTRY, getDPDisplay } from "./dpRegistry";

describe("dpRegistry", () => {
  it("has entries for all 6 V1.4.0 decision IDs", () => {
    const expected = [
      "model_type_auto_select",
      "ols_default_robust_se",
      "categorical_auto_dummy",
      "auto_coerce_to_numeric",
      "handle_missing_values",
      "variable_silently_dropped",
    ];
    expected.forEach((id) => expect(DP_REGISTRY[id]).toBeDefined());
  });

  it("model_type_auto_select translates continuous → OLS", () => {
    expect(DP_REGISTRY.model_type_auto_select.displaySelected("continuous")).toBe(
      "OLS",
    );
    expect(DP_REGISTRY.model_type_auto_select.displaySelected("binary")).toBe(
      "Logit",
    );
    expect(DP_REGISTRY.model_type_auto_select.displaySelected("count")).toBe(
      "Poisson",
    );
  });

  it("ols_default_robust_se passes selected through", () => {
    expect(DP_REGISTRY.ols_default_robust_se.displaySelected("HC1")).toBe("HC1");
  });

  it("getDPDisplay returns humanized fallback for unknown ID", () => {
    const d = getDPDisplay("some_unknown_decision_id");
    expect(d.title).toBe("Some Unknown Decision Id");
  });

  it("whyLong uses chosen_params", () => {
    const why = DP_REGISTRY.model_type_auto_select.whyLong({
      y_unique: 32,
      y_dtype: "float64",
    });
    expect(why).toContain("32 unique");
    expect(why).toContain("float64");
  });
});
