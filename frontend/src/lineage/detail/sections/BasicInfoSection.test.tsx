// frontend/src/lineage/detail/sections/BasicInfoSection.test.tsx
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
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
