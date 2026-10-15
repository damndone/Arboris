import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { MapTree, mapRows } from "./MapTree";
import type { GraphViewEdge, GraphViewNode } from "../lineage/api/graphViewTypes";

function node(id: string, stage: GraphViewNode["stage"], title: string, extra: Partial<GraphViewNode> = {}): GraphViewNode {
  return { id, nodeKey: id, raw: {}, stage, kind: stage, title, parentStageId: null, trust: "ok", decisions: [], ...extra } as GraphViewNode;
}

const nodes = [
  node("raw", "source", "Raw input data", { summary: "300 rows × 5 columns" }),
  node("clean", "clean", "Cleaned data"),
  node("ols", "model", "OLS baseline", { summary: "educ 1.043" }),
  node("iv", "model", "IV · distance", { summary: "educ 0.466", trust: "review" }),
  node("report", "report", "Report"),
];
const edges: GraphViewEdge[] = [
  { id: "e1", source: "raw", target: "clean" },
  { id: "e2", source: "clean", target: "ols" },
  { id: "e3", source: "clean", target: "iv" },
  { id: "e4", source: "iv", target: "report" },
];

describe("MapTree", () => {
  test("data first as a tree, then each model one step in with what hangs off it", () => {
    expect(mapRows(nodes, edges).map((row) => [row.node.id, row.depth])).toEqual([
      ["raw", 0],
      ["clean", 0],
      ["ols", 0],
      ["iv", 0],
      ["report", 1],
    ]);
    expect(mapRows(nodes, edges).map((row) => row.group)).toEqual(["data", "data", "analysis", "analysis", "analysis"]);
  });

  test("variables that also feed the models stay in the data part, before the models", () => {
    const withVars = [...nodes, node("wage", "transform", "wage (cleaned)"), node("educ", "transform", "educ (cleaned)")];
    const withEdges = [
      ...edges,
      { id: "v1", source: "clean", target: "wage" },
      { id: "v2", source: "clean", target: "educ" },
      { id: "v3", source: "wage", target: "ols" },
      { id: "v4", source: "educ", target: "iv" },
    ];
    expect(mapRows(withVars, withEdges).map((row) => [row.node.id, row.depth])).toEqual([
      ["raw", 0],
      ["clean", 0],
      ["wage", 1],
      ["educ", 1],
      ["ols", 0],
      ["iv", 0],
      ["report", 1],
    ]);
  });

  test("a node reached twice is listed once, under its first parent", () => {
    const dag = [...edges, { id: "e5", source: "ols", target: "report" }];
    expect(mapRows(nodes, dag).filter((row) => row.node.id === "report")).toHaveLength(1);
  });

  test("shows each step with its summary, marks the selection and selects on click", () => {
    const onSelect = vi.fn();
    render(<MapTree nodes={nodes} edges={edges} selectedKey="iv" onSelect={onSelect} />);
    expect(within(screen.getByRole("list", { name: "Data steps" })).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Raw input data300 rows × 5 columns",
      "Cleaned data",
    ]);
    expect(within(screen.getByRole("list", { name: "Analyses" })).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "OLS baselineeduc 1.043",
      expect.stringContaining("IV · distance"),
      "Report",
    ]);
    expect(screen.getByRole("button", { name: /IV · distance/ })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /IV · distance/ })).toHaveTextContent("Needs review");
    fireEvent.click(screen.getByRole("button", { name: /OLS baseline/ }));
    expect(onSelect).toHaveBeenCalledWith("ols");
  });
});
