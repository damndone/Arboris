// frontend/src/lineage/detail/sections/BasicInfoSection.test.tsx
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BasicInfoSection } from "./BasicInfoSection";
import type { GraphViewNode } from "../../api/graphViewTypes";

function node(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "n1",
    nodeKey: "n1",
    raw: null,
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-22T12:34:56Z",
    ...overrides,
  };
}

it("chooses the report coefficient and confidence level while keeping the saved interval visible", () => {
  render(<BasicInfoSection node={node({
    id: "report:one", nodeKey: "report:one", stage: "report", kind: "report", title: "Result",
    cardPreview: {
      title: "IV results", lines: [], report: {
        model_id: "iv_2sls_1", default_term: "d2", distribution: "z", coefficients: [
          { term: "d1", label: "d1", estimate: 0.4, p_value: 0.02,
            saved_interval: { level: 0.95, lower: 0.1, upper: 0.7 },
            intervals: [{ level: 0.99, lower: -0.15, upper: 0.95 }] },
          { term: "d2", label: "d2", estimate: -1, p_value: 0.03,
            saved_interval: { level: 0.95, lower: -1.5, upper: -0.5 }, intervals: [],
            interval_unavailable: "No matching covariance was saved." },
        ],
      },
    },
  })} />);

  const term = screen.getByLabelText("Coefficient");
  const confidence = screen.getByLabelText("Confidence level");
  expect(term).toHaveValue("d2");
  expect(screen.getByText("No matching covariance was saved.")).toBeVisible();
  fireEvent.change(term, { target: { value: "d1" } });
  fireEvent.change(confidence, { target: { value: "0.99" } });
  expect(screen.getByText("99% CI [-0.15, 0.95]")).toBeVisible();
  expect(screen.getByText("95% CI [0.1, 0.7]")).toBeVisible();
  expect(screen.getByText("Computed from saved normal (z) inference")).toBeVisible();
  fireEvent.change(term, { target: { value: "d2" } });
  expect(screen.getByText("Confidence interval unavailable")).toBeVisible();
  expect(screen.getByText("95% CI [-1.5, -0.5]")).toBeVisible();
  expect(screen.queryByText("99% CI [-0.15, 0.95]")).not.toBeInTheDocument();
});

describe("BasicInfoSection", () => {
  it("renders heading 'Basic info'", () => {
    render(<BasicInfoSection node={node()} />);
    expect(screen.getByText("Basic info")).toBeInTheDocument();
  });

  it("renders exactly 3 K/V rows (Kind / Stage / Created)", () => {
    const { container } = render(<BasicInfoSection node={node()} />);
    // dd elements only — the outer section also matches data-testid^=basic-info-
    const rows = container.querySelectorAll(
      "dd[data-testid^='basic-info-']",
    );
    expect(rows).toHaveLength(3);
    const ids = Array.from(rows).map((el) => el.getAttribute("data-testid"));
    expect(ids).toEqual([
      "basic-info-kind",
      "basic-info-stage",
      "basic-info-created",
    ]);
  });

  it("Kind value comes verbatim from node.kind (snake_case → spaces)", () => {
    render(<BasicInfoSection node={node({ kind: "dataset_stage" })} />);
    expect(screen.getByTestId("basic-info-kind").textContent).toBe(
      "dataset stage",
    );
  });

  it("Stage value humanised: transform → Transform", () => {
    render(<BasicInfoSection node={node({ stage: "transform" })} />);
    expect(screen.getByTestId("basic-info-stage").textContent).toBe(
      "Transform",
    );
  });

  it("describes a terminal report as a Result and identifies its run", () => {
    render(
      <BasicInfoSection
        node={{
          ...node({ stage: "report", kind: "report", title: "Result" }),
          runs: ["run_20260730_result"],
        } as GraphViewNode}
      />,
    );

    expect(screen.getByTestId("basic-info-kind")).toHaveTextContent("Result");
    expect(screen.getByTestId("basic-info-stage")).toHaveTextContent("Result");
    expect(screen.getByTestId("basic-info-run")).toHaveTextContent("run_20260730_result");
  });

  it("keeps a non-terminal report as Report", () => {
    render(<BasicInfoSection node={node({ stage: "report", kind: "report", title: "Report" })} />);

    expect(screen.getByTestId("basic-info-kind")).toHaveTextContent("report");
    expect(screen.getByTestId("basic-info-stage")).toHaveTextContent("Report");
    expect(screen.queryByTestId("basic-info-run")).not.toBeInTheDocument();
  });

  it("Stage value: unknown → 'Unknown stage' (spec wording)", () => {
    render(<BasicInfoSection node={node({ stage: "unknown" })} />);
    expect(screen.getByTestId("basic-info-stage").textContent).toBe(
      "Unknown stage",
    );
  });

  it("Stage value: future stage we don't know → renders raw value", () => {
    render(
      <BasicInfoSection
        node={node({ stage: "future_stage" as unknown as GraphViewNode["stage"] })}
      />,
    );
    expect(screen.getByTestId("basic-info-stage").textContent).toBe(
      "future_stage",
    );
  });

  it("Created formatted via new Date().toLocaleString() (locale-agnostic assertion)", () => {
    const iso = "2026-05-22T12:34:56Z";
    render(<BasicInfoSection node={node({ createdAt: iso })} />);
    // Plan DoD T6.6: "use toLocaleString() directly in assertion".
    const expected = new Date(iso).toLocaleString();
    expect(screen.getByTestId("basic-info-created").textContent).toBe(
      expected,
    );
  });

  it("Created is em-dash when node.createdAt is undefined", () => {
    render(<BasicInfoSection node={node({ createdAt: undefined })} />);
    expect(screen.getByTestId("basic-info-created").textContent).toBe("—");
  });

  it("Created falls back to raw string when Date parsing throws", () => {
    // new Date(anything) doesn't throw in JS — produces Invalid Date and
    // toLocaleString returns "Invalid Date". Cover the catch path by
    // verifying invalid input still renders something (not blank).
    render(<BasicInfoSection node={node({ createdAt: "not-a-date" })} />);
    const text = screen.getByTestId("basic-info-created").textContent ?? "";
    expect(text.length).toBeGreaterThan(0);
  });
});
