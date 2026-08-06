import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SurveyDesignControls, emptySurveyDesign } from "./SurveyDesignControls";
import type { SurveyDesignCapability } from "../capabilities/types";

/**
 * The option sets come from the server. Hard-coding them here would mean the
 * form silently disagrees with what the engine actually accepts the moment a
 * policy is added or removed, and nothing would report the drift.
 */
const capability: SurveyDesignCapability = {
  variance_methods: ["linearization", "replicate"],
  variance_method_requirements: {
    linearization: ["deterministic_refit", "influence_function"],
    replicate: ["deterministic_refit"],
  },
  replicate_types: ["brr", "jackknife", "bootstrap", "provided"],
  lonely_psu_policies: ["fail", "remove", "adjust", "average", "certainty"],
  design_fields: [],
  sampling_weight_families: ["ols", "logit", "probit", "poisson"],
};

const columns = ["stratum", "psu", "fpc", "weight", "region"];

describe("SurveyDesignControls", () => {
  it("renders every declared design field", () => {
    render(
      <SurveyDesignControls
        columns={columns}
        capability={capability}
        value={emptySurveyDesign()}
        onChange={() => {}}
      />,
    );
    for (const label of [
      "Survey strata",
      "Survey PSU",
      "Survey FPC",
      "Survey replicate type",
      "Survey lonely PSU policy",
      "Survey weight frame",
      "Survey subpopulation",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it("takes its option sets from capabilities rather than a local constant", () => {
    const narrowed: SurveyDesignCapability = {
      ...capability,
      replicate_types: ["jackknife"],
      lonely_psu_policies: ["fail", "adjust"],
    };
    render(
      <SurveyDesignControls
        columns={columns}
        capability={narrowed}
        value={emptySurveyDesign()}
        onChange={() => {}}
      />,
    );

    const replicate = screen.getByLabelText("Survey replicate type") as HTMLSelectElement;
    expect([...replicate.options].map((o) => o.value).filter(Boolean)).toEqual(["jackknife"]);

    const lonely = screen.getByLabelText("Survey lonely PSU policy") as HTMLSelectElement;
    expect([...lonely.options].map((o) => o.value).filter(Boolean)).toEqual(["fail", "adjust"]);
  });

  it("reports each edit to its owner", () => {
    const onChange = vi.fn();
    render(
      <SurveyDesignControls
        columns={columns}
        capability={capability}
        value={emptySurveyDesign()}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Survey strata"), { target: { value: "stratum" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ survey_strata_col: "stratum" }),
    );
  });

  it("belongs only to families the server says take a sampling weight", async () => {
    /**
     * A family whose engine refuses a sampling weight must not be offered a
     * design: the run would come back rejected for a reason the user cannot see
     * from the form.  The answer is the server's, not a copy kept here -- a
     * local list is the enumeration matrix this version removed from the backend.
     */
    const { surveyDesignApplies } = await import("./SurveyDesignControls");
    expect(surveyDesignApplies(capability, "ols")).toBe(true);
    expect(surveyDesignApplies(capability, "cs_did")).toBe(false);
    expect(surveyDesignApplies(undefined, "ols")).toBe(false);

    // Follows the server rather than a constant: withdraw ols and it goes away.
    expect(
      surveyDesignApplies({ ...capability, sampling_weight_families: ["logit"] }, "ols"),
    ).toBe(false);
  });

  it("starts with no design declared", () => {
    // A design the user did not declare must not appear declared: the backend
    // refuses a sampling weight without one, and a pre-filled form would make
    // that refusal look like a bug in the product rather than a missing input.
    expect(emptySurveyDesign()).toEqual({
      survey_strata_col: "",
      survey_psu_col: "",
      survey_fpc_col: "",
      survey_replicate_weights: [],
      survey_replicate_type: "",
      survey_lonely_psu: "",
      survey_weight_frame: "",
      survey_subpop: "",
    });
  });
});
