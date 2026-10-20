import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { IVDiagnosticsCard, type IVDiagnostics } from "./IVDiagnosticsCard";

const over: IVDiagnostics = {
  identification: "over",
  weak_instruments: { first_stage_f: 24.3, threshold: 10, verdict: "caution", message: "First-stage F benchmark; validity is not certified." },
  endogeneity: { test: "wu_hausman", statistic: 8.1, pvalue: 0.004, verdict: "rejects_exogeneity", message: "Exogeneity rejected under maintained assumptions." },
  overidentification: { applicable: true, test: "sargan", statistic: 1.9, pvalue: 0.168, verdict: "not_rejected", message: "Instrument exogeneity not rejected (p >= 0.05)." },
};

describe("IVDiagnosticsCard", () => {
  it("renders all three diagnostics + over-identified badge", () => {
    render(<IVDiagnosticsCard diagnostics={over} />);
    expect(screen.getByLabelText("IV identification")).toHaveTextContent("over-identified");
    expect(screen.getByText(/First-stage F =/i)).toBeInTheDocument();
    expect(screen.getByText(/under maintained assumptions/i)).toBeInTheDocument();
    expect(screen.getByText(/24\.3/)).toBeInTheDocument(); // statistic visible
  });

  it("renders 'not applicable' for just-identified overid", () => {
    const just: IVDiagnostics = { ...over, identification: "just",
      overidentification: { applicable: false, verdict: "Not applicable (just-identified)." } };
    render(<IVDiagnosticsCard diagnostics={just} />);
    expect(screen.getByLabelText("IV identification")).toHaveTextContent("just-identified");
    expect(screen.getByText(/not applicable/i)).toBeInTheDocument();
  });

  it("renders nothing when diagnostics is undefined", () => {
    const { container } = render(<IVDiagnosticsCard diagnostics={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("uses the actual robust test names without calibrated F thresholds", () => {
    const robust: IVDiagnostics = { ...over,
      weak_instruments: { first_stage_f: null, first_stage_statistic: 48.6,
        reference_distribution: "chi2(2)", test: "wald_chi2", threshold: null, verdict: "unassessed",
        message: "Instrument strength is not certified." },
      endogeneity: { ...over.endogeneity, test: "wooldridge_regression" },
      overidentification: { applicable: true, test: "wooldridge_overid", statistic: 1.8,
        pvalue: .18, verdict: "not_rejected", message: "Validity is not established." } };
    render(<IVDiagnosticsCard diagnostics={robust} />);
    expect(screen.getByText(/First-stage Wald χ² = 48.60/)).toHaveTextContent("chi2(2)");
    expect(screen.getByText(/Wooldridge exogeneity/)).toBeInTheDocument();
    expect(screen.getByText(/Wooldridge robust score/)).toBeInTheDocument();
    expect(screen.queryByText(/thresholds|Sargan|Wu-Hausman/)).not.toBeInTheDocument();
  });

  it.each(["whole_line", "empty", "union_of_rays", "disjoint", "singleton", "unavailable"])(
    "shows %s AR sets and the global certification status", (kind) => {
      const diagnostics: IVDiagnostics = { ...over, weak_instruments: { ...over.weak_instruments,
        anderson_rubin_95: { kind, lower: -1, upper: 2, reason: "singular_covariance_on_real_line",
          components: [{ lower: -1, upper: 2, lower_closed: true, upper_closed: true }],
          global_certification: { status: kind === "unavailable" ? "certified_on_defined_domain" : "certified" } } } };
      render(<IVDiagnosticsCard diagnostics={diagnostics} />);
      expect(screen.getByTestId("iv-anderson-rubin")).not.toHaveTextContent("undefined");
      expect(screen.getByTestId("iv-anderson-rubin")).toHaveTextContent(
        kind === "unavailable" ? "unavailable" : "Global inversion verified");
    });
});
