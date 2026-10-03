import { describe, expect, it } from "vitest";

import type { ModelResult } from "../api";
import { buildRegressionTablePacket } from "./RegressionTable";

const byGroup = {
  column: "language",
  n_groups: 4,
  not_estimable: [{ key: "(missing)", nobs: 27, reason: "27 rows for 3 parameters" }],
  difference_tests: {
    status: "estimated",
    tests: [{ label: "effect of education equal across groups", statistic: 1.7235, df_num: 2, df_den: 4776, p_value: 0.1786, distribution: "F" }],
  },
};

function model(id: string, key: string): ModelResult {
  return {
    model_id: id,
    model_type: "ols_robust",
    coefficients: { education: { estimate: 0.9, std_error: 0.05, p_value: 0.001 } },
    by_group: { ...byGroup, key },
  } as unknown as ModelResult;
}

describe("regression table for a by-group run", () => {
  it("names each column's group and lists what side-by-side columns do not show", () => {
    const packet = buildRegressionTablePacket([model("ols_1_g01", "English"), model("ols_1_g02", "French")], {
      "***": 0.01,
    });
    expect(packet.models.map((item) => item.label)).toEqual([
      "ols_robust [language = English]",
      "ols_robust [language = French]",
    ]);
    expect(packet.byGroup?.[0]).toContain("not a test of a difference");
    expect(packet.byGroup).toContain("Not estimated: language = (missing) (27 rows): 27 rows for 3 parameters");
    expect(packet.byGroup?.some((note) => note.includes("F(2, 4776) = 1.724") && note.includes("p = 0.179"))).toBe(true);
  });

  it("adds nothing for an ordinary model", () => {
    const plain = { model_id: "ols_1", model_type: "ols", coefficients: { x: { estimate: 1 } } } as unknown as ModelResult;
    expect(buildRegressionTablePacket([plain], { "***": 0.01 }).byGroup).toBeUndefined();
  });
});
