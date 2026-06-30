import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { RoleGroupsSection } from "./RoleGroupsSection";
import { LineageContext, type LineageContextValue } from "../../LineageContext";
import type {
  GraphViewEdge,
  GraphViewModel,
  GraphViewNode,
} from "../../api/graphViewTypes";

function modelNode(): GraphViewNode {
  return {
    id: "model:ols_1",
    nodeKey: "model:ols_1",
    raw: null,
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    createdAt: "2026-06-30T00:00:00Z",
  };
}

function renderWith(edges: GraphViewEdge[]) {
  const model: GraphViewModel = {
    schemaVersion: 3,
    runId: "run-1",
    legacy: false,
    nodes: [modelNode()],
    edges,
    stats: { nodeCount: 1, edgeCount: edges.length, leafCount: 1, hasDpCount: 0 },
  };
  const ctx: LineageContextValue = { model, selectedKey: "model:ols_1", select: vi.fn() };
  return render(
    <LineageContext.Provider value={ctx}>
      <RoleGroupsSection node={modelNode()} />
    </LineageContext.Provider>,
  );
}

function edge(source: string, op: string, params: Record<string, unknown> = {}): GraphViewEdge {
  return { id: `${source}->model:ols_1`, source, target: "model:ols_1", op, params };
}

it("renders role groups in canonical order from edges", () => {
  renderWith([
    edge("var:age:cleaned", "enters_as_covariates"),
    edge("var:y:cleaned", "enters_as_outcome"),
    edge("var:x1:cleaned", "enters_as_focal"),
  ]);
  expect(screen.getByText("Outcome Variable (Y)")).toBeInTheDocument();
  expect(screen.getByText("Focal Explanatory Variable (X)")).toBeInTheDocument();
  expect(screen.getByText("Covariates (Z)")).toBeInTheDocument();
  // canonical: outcome before focal before covariates
  const order = Array.from(
    screen.getByTestId("role-groups").querySelectorAll("[data-role]"),
  ).map((n) => n.getAttribute("data-role"));
  expect(order).toEqual(["outcome", "focal", "covariates"]);
});

it("stamps roles: unspecified when only explanatory fallback present", () => {
  renderWith([
    edge("var:y:cleaned", "enters_as_outcome"),
    edge("var:a:cleaned", "enters_as_explanatory_unspecified"),
  ]);
  expect(screen.getByTestId("role-tag")).toHaveTextContent("roles: unspecified");
});

it("renders nothing when the model has no role edges", () => {
  const { container } = renderWith([
    { id: "e1", source: "var:y:cleaned", target: "model:ols_1", op: "feeds" },
  ]);
  expect(container).toBeEmptyDOMElement();
});
