import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DIDDiagnosticsCard, type DIDDiagnostics } from "./DIDDiagnosticsCard";

const diag: DIDDiagnostics = {
  att: { estimate: 2.13, std_error: 0.41, pvalue: 0.0, ci: [1.33, 2.93],
    spec: "twfe", covariance: "robust" },
  event_study: { applicable: true, event_time: [-2, 0, 1], coef: [0.0, 1.8, 2.4],
    se: [0.3, 0.4, 0.5], ci_lower: [-0.6, 1.0, 1.4], ci_upper: [0.6, 2.6, 3.4],
    ref_period: -1 },
  parallel_trends: { test: "joint_pre_leads_f", statistic: 0.62, pvalue: 0.71,
    n_pre_leads: 1, verdict: "not_rejected", message: "ok" },
  goodman_bacon: { applicable: true, components: [
    { type: "treated_vs_untreated", weight: 0.7, estimate: 2.3 },
    { type: "later_vs_earlier", weight: 0.3, estimate: 1.1 }],
    weighted_avg: 2.06, forbidden_weight: 0.3, message: "..." },
  spec: { entity: "id", time: "year", cohort: "_did_cohort", n_treated_units: 4,
    n_never_treated: 2, staggered: true, mode: "cohort" },
};

describe("DIDDiagnosticsCard", () => {
  it("shows ATT headline and verdict pill collapsed", () => {
    render(<DIDDiagnosticsCard diagnostics={diag} />);
    expect(screen.getByText(/2\.13/)).toBeInTheDocument();
    expect(screen.getByText(/未拒绝/)).toBeInTheDocument();
  });

  it("reveals the full event-study table on expand", () => {
    render(<DIDDiagnosticsCard diagnostics={diag} />);
    expect(screen.queryByLabelText("did-event-study-table")).toBeNull();
    fireEvent.click(screen.getByText(/展开完整数据/));
    expect(screen.getByLabelText("did-event-study-table")).toBeInTheDocument();
  });

  it("renders an 'not identified' note when event study is not applicable", () => {
    const skipped: DIDDiagnostics = { ...diag, event_study: {
      applicable: false, message: "DID_EVENT_STUDY_UNIDENTIFIED: ...",
      event_time: [], coef: [], se: [], ci_lower: [], ci_upper: [], ref_period: -1 } };
    render(<DIDDiagnosticsCard diagnostics={skipped} />);
    expect(screen.getByText(/事件研究.*不可识别|不可识别/)).toBeInTheDocument();
    // ATT still shown
    expect(screen.getByText(/2\.13/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/展开完整数据/));
    expect(screen.queryByLabelText("did-event-study-table")).toBeNull();
  });

  it("does not crash when event-study values contain nulls", () => {
    const withNull: DIDDiagnostics = { ...diag, event_study: {
      applicable: true, event_time: [-2, 0, 1],
      coef: [0.0, null as unknown as number, 2.4],
      se: [0.3, null as unknown as number, 0.5],
      ci_lower: [-0.6, null as unknown as number, 1.4],
      ci_upper: [0.6, 2.6, 3.4], ref_period: -1 } };
    expect(() => render(<DIDDiagnosticsCard diagnostics={withNull} />)).not.toThrow();
    fireEvent.click(screen.getByText(/展开完整数据/));
    const table = screen.getByLabelText("did-event-study-table");
    expect(table).toBeInTheDocument();
    // the null cell renders an em-dash placeholder
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    // a non-null row still renders its value
    expect(screen.getByText("2.400")).toBeInTheDocument();
  });
});
