import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RepeatedMeasuresInspector } from "./RepeatedMeasuresInspector";

describe("RepeatedMeasuresInspector", () => {
  it("composes server-owned provenance and a packet-only result view", () => {
    render(
      <RepeatedMeasuresInspector
        binding={{
          owner_model_type: "linear_mixed_effects",
          owner_model_id: "linear_mixed_effects_1",
          producer_version: "linear_mixed_effects@1.0",
          input_contract_version: "1.0",
          normalized_options_hash: "abc123",
        }}
        packet={{
          contract: "linear_mixed_effects.result",
          contract_version: "1.0",
          producer_version: "linear_mixed_effects@1.0",
          payload: {
            status: "complete",
            result_id: "group_time_interaction",
            estimate: 0.9,
            fit_method: "reml",
            inference_method: "asymptotic_wald_z_v1",
          },
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "重复测量检查器" })).toBeInTheDocument();
    expect(screen.getByText("abc123")).toBeInTheDocument();
    expect(screen.getByText("运行成功")).toBeInTheDocument();
  });
});
