import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ModelOptionsProvenance } from "./ModelOptionsProvenance";

describe("ModelOptionsProvenance", () => {
  it("renders server-owned binding facts as non-editable provenance", () => {
    render(
      <ModelOptionsProvenance
        binding={{
          owner_model_type: "linear_mixed_effects",
          owner_model_id: "linear_mixed_effects",
          producer_version: "linear_mixed_effects@1.0",
          input_contract_version: "1.0",
          normalized_options_hash: "a1b2c3",
        }}
      />,
    );

    expect(screen.getByText("linear_mixed_effects@1.0")).toBeInTheDocument();
    expect(screen.getByText("a1b2c3")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
