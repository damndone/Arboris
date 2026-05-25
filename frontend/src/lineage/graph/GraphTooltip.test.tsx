import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GraphTooltip } from "./GraphTooltip";
import type { GraphViewNode } from "../api/graphViewTypes";

function vn(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "n1",
    nodeKey: "n1",
    raw: null,
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    summary: "OLS · HC1 · n = 32",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    ...overrides,
  };
}

describe("GraphTooltip (T8.4)", () => {
  it("renders nothing when node is null", () => {
    const { container } = render(<GraphTooltip node={null} x={0} y={0} />);
    expect(container.firstChild).toBeNull();
    expect(document.body.querySelector('[data-testid="graph-tooltip"]')).toBeNull();
  });

  it("portals into document.body (escapes canvas transform)", () => {
    const { container } = render(<GraphTooltip node={vn()} x={100} y={200} />);
    // Portal target is document.body, not the test container.
    expect(container.querySelector('[data-testid="graph-tooltip"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="graph-tooltip"]')).not.toBeNull();
  });

  it("positions at clientX + 18, clientY + 14 (screen-space)", () => {
    render(<GraphTooltip node={vn()} x={100} y={200} />);
    const tip = screen.getByTestId("graph-tooltip");
    expect(tip.style.left).toBe("118px");
    expect(tip.style.top).toBe("214px");
    // position:fixed comes from the CSS class (.ln-graph-tooltip),
    // not inline style — jsdom doesn't resolve it, so we don't assert
    // on tip.style.position. The "zoom independence" test below
    // covers the actually meaningful screen-space property.
  });

  it("renders title, kind, id, trust label, and click hint", () => {
    render(<GraphTooltip node={vn()} x={0} y={0} />);
    expect(screen.getByText("Primary OLS")).toBeInTheDocument();
    expect(screen.getByText("model")).toBeInTheDocument();
    expect(screen.getByText("n1")).toBeInTheDocument();
    expect(screen.getByText("OK")).toBeInTheDocument();
    expect(screen.getByText(/click to inspect/i)).toBeInTheDocument();
  });

  it("omits runtime row when runtimeMs is undefined (V1.5.0 forward-compat)", () => {
    render(<GraphTooltip node={vn()} x={0} y={0} />);
    expect(screen.queryByText("runtime")).toBeNull();
  });

  it("renders runtime row when runtimeMs is present (V1.5.x)", () => {
    render(<GraphTooltip node={vn({ runtimeMs: 420 })} x={0} y={0} />);
    expect(screen.getByText("runtime")).toBeInTheDocument();
    expect(screen.getByText("420 ms")).toBeInTheDocument();
  });

  it("renders at most 2 stats samples (plan T8.4 step 3)", () => {
    const stats = { rows: 1234, cols: 12, missing: 0, na_pct: 0 };
    render(<GraphTooltip node={vn({ stats })} x={0} y={0} />);
    expect(screen.getByText("rows")).toBeInTheDocument();
    expect(screen.getByText("cols")).toBeInTheDocument();
    // Third + fourth stat must be dropped.
    expect(screen.queryByText("missing")).toBeNull();
    expect(screen.queryByText("na_pct")).toBeNull();
  });

  it("formats numeric stats with toLocaleString", () => {
    render(<GraphTooltip node={vn({ stats: { rows: 1234567 } })} x={0} y={0} />);
    expect(screen.getByText("1,234,567")).toBeInTheDocument();
  });

  it("shows correct trust label for review and caution", () => {
    const { rerender } = render(
      <GraphTooltip node={vn({ trust: "review" })} x={0} y={0} />,
    );
    expect(screen.getByText("Review")).toBeInTheDocument();
    rerender(<GraphTooltip node={vn({ trust: "caution" })} x={0} y={0} />);
    expect(screen.getByText("Caution")).toBeInTheDocument();
  });

  it("DoD: pixel position is independent of canvas zoom (portal to body)", () => {
    // The tooltip's left/top derive ONLY from the x/y props — by
    // portaling out of the React Flow viewport, no parent transform
    // (zoom=0.5, zoom=2) can affect computed position. We model this
    // by rendering at the same x/y under nested transformed parents
    // and asserting the inline style is unchanged.
    const Wrapper = ({ scale, x, y }: { scale: number; x: number; y: number }) => (
      <div style={{ transform: `scale(${scale})`, transformOrigin: "0 0" }}>
        <div style={{ transform: `translate(50px, 80px)` }}>
          <GraphTooltip node={vn()} x={x} y={y} />
        </div>
      </div>
    );

    const { unmount } = render(<Wrapper scale={0.5} x={300} y={400} />);
    let tip = screen.getByTestId("graph-tooltip");
    expect(tip.style.left).toBe("318px");
    expect(tip.style.top).toBe("414px");
    unmount();

    render(<Wrapper scale={2} x={300} y={400} />);
    tip = screen.getByTestId("graph-tooltip");
    expect(tip.style.left).toBe("318px");
    expect(tip.style.top).toBe("414px");
  });
});
