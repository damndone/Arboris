import { describe, expect, it } from "vitest";
import {
  buildRegressionTablePacket,
  RegressionTable,
} from "./RegressionTable";

describe("RegressionTable", () => {
  it("keeps side-by-side coefficient provenance and configurable stars", () => {
    const packet = buildRegressionTablePacket(
      [
        {
          model_id: "ols_1",
          model_type: "Baseline",
          nobs: 100,
          coefficients: {
            x: {
              estimate: 1.25,
              std_error: 0.2,
              p_value: 0.15,
              ci_lower: 0.8,
              ci_upper: 1.7,
              source_id: "model_results.ols_1.coefficients.x",
            },
          },
        },
        {
          model_id: "ols_2",
          model_type: "With control",
          nobs: 95,
          coefficients: {
            x: {
              estimate: 1.1,
              std_error: 0.18,
              p_value: 0.04,
              source_id: "model_results.ols_2.coefficients.x",
            },
          },
        },
      ],
      { "*": 0.2, "**": 0.05, "***": 0.01 },
    );

    expect(packet.models.map((model) => model.label)).toEqual([
      "Baseline",
      "With control",
    ]);
    expect(packet.rows[0].models.ols_1).toMatchObject({
      estimate: 1.25,
      p_value: 0.15,
      significance: "*",
      source_id: "model_results.ols_1.coefficients.x",
    });
    expect(packet.rows[0].models.ols_2?.significance).toBe("**");
    expect(packet.rows[0].models.ols_1?.ci_lower).toBe(0.8);
    expect(packet.significance.legend).toContain("* p < 0.2");
  });

  it("renders missing model terms as unavailable instead of inventing values", () => {
    const packet = buildRegressionTablePacket([
      {
        model_id: "ols_1",
        coefficients: { x: { estimate: 1, p_value: 0.5 } },
      },
      {
        model_id: "ols_2",
        coefficients: { z: { estimate: 2, p_value: 0.5 } },
      },
    ]);

    const { rows } = packet;
    expect(rows.find((row) => row.term === "x")?.models.ols_2).toBeNull();
    expect(rows.find((row) => row.term === "z")?.models.ols_1).toBeNull();
    expect(() => RegressionTable({ packet })).not.toThrow();
  });
});
