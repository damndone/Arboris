// frontend/src/lineage/header/DetailHeader.test.tsx
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DETAIL_HEADER_TITLE_ID, DetailHeader } from "./DetailHeader";
import { LineageContext, type LineageContextValue } from "../LineageContext";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";

function makeNode(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "stage:raw",
    nodeKey: "stage:raw",
    raw: null,
    stage: "source",
    kind: "dataset_stage",
    title: "Raw input data",
    summary: "Raw: 10 rows × 2 cols",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-22T00:00:00Z",
    ...overrides,
  };
}

function makeModel(): GraphViewModel {
  return {
    schemaVersion: 3,
    runId: "run-42",
    legacy: false,
    nodes: [makeNode()],
    edges: [],
    stats: { nodeCount: 1, edgeCount: 0, leafCount: 1, hasDpCount: 0 },
  };
}

function renderHeader(
  node: GraphViewNode,
  onClose: () => void = vi.fn(),
  model: GraphViewModel = makeModel(),
  onShowJson?: () => void,
) {
  const ctx: LineageContextValue = { model, selectedKey: node.id, select: vi.fn() };
  return render(
    <LineageContext.Provider value={ctx}>
      <DetailHeader node={node} onClose={onClose} onShowJson={onShowJson} />
    </LineageContext.Provider>,
  );
}

describe("DetailHeader", () => {
  it("title <h2> carries the DETAIL_HEADER_TITLE_ID anchor for aria-labelledby", () => {
    const { container } = renderHeader(makeNode());
    const heading = container.querySelector(`#${DETAIL_HEADER_TITLE_ID}`);
    expect(heading).not.toBeNull();
    expect(heading?.tagName).toBe("H2");
    expect(heading?.textContent).toBe("Raw input data");
  });

  it("kind label renders verbatim from node.kind", () => {
    renderHeader(makeNode({ kind: "model" }));
    expect(screen.getByText("model")).toBeInTheDocument();
  });

  it("breadcrumb shows runId · nodeKey from context + node", () => {
    renderHeader(makeNode({ nodeKey: "model:ols_1" }));
    expect(screen.getByText("run-42 · model:ols_1")).toBeInTheDocument();
  });

  it("summary line renders when node.summary is set", () => {
    renderHeader(makeNode({ summary: "Raw: 10 rows × 2 cols" }));
    expect(screen.getByText("Raw: 10 rows × 2 cols")).toBeInTheDocument();
  });

  it("summary line is omitted when node.summary is undefined", () => {
    const { container } = renderHeader(makeNode({ summary: undefined }));
    expect(container.querySelector(".dp-sub")).toBeNull();
  });

  it('close button has aria-label="Close" and fires onClose', () => {
    const onClose = vi.fn();
    renderHeader(makeNode(), onClose);
    const btn = screen.getByRole("button", { name: "Close" });
    fireEvent.click(btn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT mount NodeActionMenu when onShowJson is omitted", () => {
    renderHeader(makeNode());
    expect(screen.queryByRole("button", { name: /node actions/i })).toBeNull();
  });

  it("mounts NodeActionMenu when onShowJson is provided (REV-3 F2 reachability)", () => {
    renderHeader(makeNode(), vi.fn(), makeModel(), vi.fn());
    expect(
      screen.getByRole("button", { name: /node actions/i }),
    ).toBeInTheDocument();
  });

  it("NodeActionMenu's View Raw JSON forwards to the onShowJson prop", () => {
    const onShowJson = vi.fn();
    renderHeader(makeNode(), vi.fn(), makeModel(), onShowJson);
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    fireEvent.click(screen.getByText("View Raw JSON"));
    expect(onShowJson).toHaveBeenCalledTimes(1);
  });

  it("throws if mounted outside LineageContext (uses runId)", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(<DetailHeader node={makeNode()} onClose={vi.fn()} />),
    ).toThrow(/useLineage/);
    errSpy.mockRestore();
  });
});
