import { expect, test, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ArmaGarchResultSection } from "./ArmaGarchResultSection";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import { useArmaGarchArtifacts } from "../../../runResult/useArmaGarchArtifacts";
import type { HeadSetNode } from "../../api/graphViewTypes";

vi.mock("../../../workbench/ProjectRootContext", () => ({
  useProjectRootOptional: vi.fn(),
}));
vi.mock("../../../runResult/useArmaGarchArtifacts", () => ({
  useArmaGarchArtifacts: vi.fn(),
}));

const node = () =>
  ({
    id: "M1",
    nodeKey: "M1",
    kind: "model",
    stage: "model",
    title: "ARMA-GARCH",
    opType: "time_series.arma_garch",
    runs: ["run_a"],
    decisions: [],
    trust: "ok",
  }) as unknown as HeadSetNode;

const report = {
  report: {
    answer: "Selected arma-p1-q0-c with GARCH(1,1).",
    estimation_semantics: { joint_likelihood: false },
    sample: { source_n: 320, training_n: 279, validation_n: 40 },
    scale: { transform: "log_return_pct", lag_unit: "trading observation" },
    acceptance: { overall_status: "accepted", dimensions: {} },
  },
};

beforeEach(() => {
  vi.mocked(useProjectRootOptional).mockReset();
  vi.mocked(useArmaGarchArtifacts).mockReset();
});

test("renders the dashboard for the node's run", () => {
  vi.mocked(useProjectRootOptional).mockReturnValue("/p");
  vi.mocked(useArmaGarchArtifacts).mockReturnValue(report);

  render(<ArmaGarchResultSection node={node()} />);

  expect(useArmaGarchArtifacts).toHaveBeenCalledWith("/p", "run_a");
  expect(screen.getByRole("heading", { name: "ARMA-GARCH Volatility Workbench" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Forecast Validation" })).toBeTruthy();
});

test("renders nothing without a project root", () => {
  vi.mocked(useProjectRootOptional).mockReturnValue(null);
  vi.mocked(useArmaGarchArtifacts).mockReturnValue(undefined);

  const { container } = render(<ArmaGarchResultSection node={node()} />);
  expect(container.firstChild).toBeNull();
});

test("renders nothing when the run has no ARMA-GARCH artifacts", () => {
  vi.mocked(useProjectRootOptional).mockReturnValue("/p");
  vi.mocked(useArmaGarchArtifacts).mockReturnValue(undefined);

  const { container } = render(<ArmaGarchResultSection node={node()} />);
  expect(container.firstChild).toBeNull();
});
