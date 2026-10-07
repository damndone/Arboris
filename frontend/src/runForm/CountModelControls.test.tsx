import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CountModelControls, buildCountModelOptions, countModelValidationError, emptyCountOptions } from "./CountModelControls";

describe("Count model options", () => {
  it("keeps the ML default without inventing fixed alpha", () => {
    expect(buildCountModelOptions("negative_binomial", emptyCountOptions)).toEqual({dispersion: "mean"});
    expect(countModelValidationError("negative_binomial", emptyCountOptions)).toBeNull();
  });
  it("requires explicit positive alpha for the negative binomial GLM", () => {
    expect(countModelValidationError("glm:negative_binomial", emptyCountOptions)).toMatch(/positive alpha/);
    expect(buildCountModelOptions("glm:negative_binomial", {...emptyCountOptions, alpha: "0.7"})).toEqual({alpha: .7});
  });
  it("rejects incompatible NB1 fixed-alpha input", () => {
    expect(countModelValidationError("negative_binomial", {...emptyCountOptions, dispersion: "constant", fixed: true, alpha: ".7"})).toMatch(/NB2/);
  });
  it("updates dispersion and fixed-alpha fields through real change events", () => {
    const changed=vi.fn();
    render(<CountModelControls modelType="negative_binomial" value={emptyCountOptions} onChange={changed}/>);
    fireEvent.change(screen.getByLabelText("Dispersion"), {target:{value:"constant"}});
    expect(changed).toHaveBeenCalledWith({...emptyCountOptions, dispersion:"constant"});
    fireEvent.click(screen.getByLabelText("Fix alpha (advanced)"));
    expect(changed).toHaveBeenCalledWith({...emptyCountOptions, fixed:true});
  });
});
