import { render, screen } from "@testing-library/react";
import { DCDHResultCard, type DCDHResult } from "./DCDHResultCard";

const base: DCDHResult = {
  estimator: "dcdh",
  event_study: {
    label_kind: "event_time",
    event_time: [-2, 0, 1],
    estimate: [0.02, 0.8, 1.0],
    se: [0.1, 0.1, 0.1],
    pointwise_ci: [[-0.2, 0.2], [0.6, 1.0], [0.8, 1.2]],
    uniform_band: [[-0.3, 0.3], [0.5, 1.1], [0.7, 1.3]],
    uniform_crit: 2.4,
    kind: ["placebo", "effect", "effect"],
    n_switchers: [72, 72, 72],
  },
  overall_att: { estimate: 0.9, se: 0.1, experimental: true },
  diagnostics: { risk_set_by_ell: [], excluded_units: [] },
  honest_did: null,
  honest_did_supported: false,
  interpretation_restrictions: [],
};

test("renders event study rows + experimental overall ATT", () => {
  render(<DCDHResultCard result={base} />);
  expect(screen.getByLabelText("dcdh-event-study-table")).toBeInTheDocument();
  expect(screen.getByLabelText("dcdh-experimental")).toBeInTheDocument();
});

test("does NOT render a Honest-DID block when honest_did_supported is false", () => {
  render(<DCDHResultCard result={base} />);
  expect(screen.queryByLabelText("dcdh-honest-did")).toBeNull();
  expect(screen.queryByText(/honest/i)).toBeNull();
});

test("renders nothing when result is undefined", () => {
  const { container } = render(<DCDHResultCard result={undefined} />);
  expect(container.firstChild).toBeNull();
});
