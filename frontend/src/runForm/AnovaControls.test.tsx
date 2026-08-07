import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnovaControls, emptyAnovaOptions } from "./AnovaControls";

const columns = ["score", "factor_a", "factor_b", "covariate"];

describe("AnovaControls", () => {
  it("offers no preset sums-of-squares type", () => {
    /**
     * The backend refuses a run whose sums-of-squares type is not declared,
     * because SPSS reports Type III and R's aov reports Type I and on an
     * unbalanced design they disagree -- 166.74 against 104.05 on the committed
     * fixture. A form that quietly pre-selects one would hand the user a choice
     * they never made and make the refusal pointless.
     */
    expect(emptyAnovaOptions().sums_of_squares).toBe("");

    render(
      <AnovaControls columns={columns} value={emptyAnovaOptions()} onChange={() => {}} />,
    );
    const select = screen.getByLabelText("ANOVA sums of squares") as HTMLSelectElement;
    expect(select.value).toBe("");
  });

  it("explains that the choice differs between SPSS and R", () => {
    render(
      <AnovaControls columns={columns} value={emptyAnovaOptions()} onChange={() => {}} />,
    );
    const help = screen.getByTestId("anova-ss-help").textContent ?? "";
    expect(help).toMatch(/SPSS/);
    expect(help).toMatch(/Type III/);
  });

  it("collects factors, interactions and the post-hoc correction", () => {
    const onChange = vi.fn();
    render(
      <AnovaControls columns={columns} value={emptyAnovaOptions()} onChange={onChange} />,
    );

    fireEvent.change(screen.getByLabelText("ANOVA sums of squares"), { target: { value: "3" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ sums_of_squares: "3" }),
    );

    fireEvent.change(screen.getByLabelText("ANOVA post-hoc"), { target: { value: "tukey" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ posthoc: "tukey" }));
  });

  it("serialises to the payload the engine expects", async () => {
    const { toAnovaModelOptions } = await import("./AnovaControls");
    expect(
      toAnovaModelOptions({
        sums_of_squares: "3",
        categorical: ["factor_a", "factor_b"],
        interactions: [["factor_a", "factor_b"]],
        posthoc: "tukey",
      }),
    ).toEqual({
      sums_of_squares: 3,
      categorical: ["factor_a", "factor_b"],
      interactions: [["factor_a", "factor_b"]],
      posthoc: "tukey",
    });
  });

  it("omits the post-hoc key when none was chosen", async () => {
    const { toAnovaModelOptions } = await import("./AnovaControls");
    const payload = toAnovaModelOptions({
      sums_of_squares: "2",
      categorical: ["factor_a"],
      interactions: [],
      posthoc: "",
    });
    expect(payload).not.toHaveProperty("posthoc");
    expect(payload.sums_of_squares).toBe(2);
  });
});
