import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { IVDiagnosticsCard, type IVDiagnostics } from "./IVDiagnosticsCard";

const over: IVDiagnostics = {
  identification: "over",
  weak_instruments: { first_stage_f: 24.3, threshold: 10, verdict: "strong", message: "Instruments are strong (first-stage F > 10, rule of thumb)." },
  endogeneity: { test: "wu_hausman", statistic: 8.1, pvalue: 0.004, verdict: "endogenous", message: "Endogeneity confirmed (p < 0.05); IV is warranted." },
  overidentification: { applicable: true, test: "sargan", statistic: 1.9, pvalue: 0.168, verdict: "not_rejected", message: "Instrument exogeneity not rejected (p >= 0.05)." },
};

describe("IVDiagnosticsCard", () => {
  it("renders all three diagnostics + over-identified badge", () => {
    render(<IVDiagnosticsCard diagnostics={over} />);
    expect(screen.getByText(/over-identified/i)).toBeInTheDocument();
    expect(
      screen.getByText(/第一阶段 F \(first-stage F\)/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/IV is warranted/i)).toBeInTheDocument();
    expect(screen.getByText(/24\.3/)).toBeInTheDocument(); // statistic visible
  });

  it("renders 'not applicable' for just-identified overid", () => {
    const just: IVDiagnostics = { ...over, identification: "just",
      overidentification: { applicable: false, verdict: "Not applicable (just-identified)." } };
    render(<IVDiagnosticsCard diagnostics={just} />);
    expect(screen.getByText(/just-identified · 恰好识别/i)).toBeInTheDocument();
    expect(screen.getByText(/not applicable/i)).toBeInTheDocument();
  });

  it("renders nothing when diagnostics is undefined", () => {
    const { container } = render(<IVDiagnosticsCard diagnostics={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
