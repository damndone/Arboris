import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentChart, shownChart, type ChartSpec } from "./AgentChart";
import type { AgentMessage } from "./agentTypes";

const chart: ChartSpec = { kind: "coefficients", title: "Return to education", reference: 0, points: [
  { label: "IV", y: 0.328, low: 0.286, high: 0.371 }, { label: "OLS", y: 0.172, low: 0.15, high: 0.19 }] };
const tool = (content: unknown, name = "show_chart") =>
  ({ role: "tool", name, content: JSON.stringify(content), entry_id: "t" }) as unknown as AgentMessage;

describe("AgentChart", () => {
  it("reads only a successful show_chart result", () => {
    expect(shownChart(tool({ ok: true, output: { chart } }))).toEqual(chart);
    expect(shownChart(tool({ ok: false, output: { chart } }))).toBeNull();
    expect(shownChart(tool({ ok: true, output: { chart } }, "calculate"))).toBeNull();
    expect(shownChart(tool({ ok: true, output: { chart: { ...chart, points: [] } } }))).toBeNull();
  });

  it("names a point on hover and keyboard focus, and keeps a data table", () => {
    render(<AgentChart chart={chart} />);
    const [first, second] = screen.getAllByLabelText(/IV|OLS/).filter((node) => node.tagName.toLowerCase() === "rect");
    fireEvent.mouseEnter(first);
    expect(screen.getByTestId("agent-chart-readout")).toHaveTextContent("IV: 0.328 [0.286, 0.371]");
    fireEvent.focus(second);
    expect(screen.getByTestId("agent-chart-readout")).toHaveTextContent("OLS: 0.172");
    expect(screen.getByRole("table")).toBeTruthy;
  });

  it.each(["bar", "line", "scatter"] as const)("draws %s and a legend for two series", (kind) => {
    render(<AgentChart chart={{ kind, title: "T", points: [
      { label: "a", x: 1, series: "A", y: 2 }, { label: "b", x: 2, series: "A", y: 3 },
      { label: "a", x: 1, series: "B", y: 1 }, { label: "b", x: 2, series: "B", y: -1 }] }} />);
    expect(screen.getByRole("img", { name: "T" })).toBeInTheDocument();
    expect(screen.getByText("B")).toBeInTheDocument();
  });
});
