import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, test } from "vitest";
import { WorkspaceShell, type LayoutControls } from "./WorkspaceShell";
import type { ViewMode } from "../workbench/state/urlSchema";

function Counter({ testId }: { testId: string }) {
  const [count, setCount] = useState(0);
  return (
    <button type="button" data-testid={testId} onClick={() => setCount((c) => c + 1)}>
      {count}
    </button>
  );
}

function Topbar({ controls }: { controls: LayoutControls }) {
  return (
    <div>
      <button type="button" aria-pressed={controls.layout === "results"} onClick={() => controls.setLayout("results")}>
        Results first
      </button>
      <button type="button" aria-pressed={controls.layout === "lineage"} onClick={() => controls.setLayout("lineage")}>
        Lineage first
      </button>
    </div>
  );
}

function renderShell(view: ViewMode = "graph", projectRoot = "/p") {
  return render(
    <WorkspaceShell
      projectRoot={projectRoot}
      view={view}
      topbar={(controls) => <Topbar controls={controls} />}
      stageOpen
      map={() => <Counter testId="map-state" />}
      stage={<Counter testId="stage-state" />}
      agent={<Counter testId="agent-state" />}
      bottom={<div>bottom</div>}
    />,
  );
}

const shell = () => screen.getByTestId("workspace-shell");

describe("WorkspaceShell", () => {
  beforeEach(() => localStorage.clear());

  test("lays out the five regions as landmarks", () => {
    renderShell();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Map" })).toContainElement(screen.getByTestId("map-state"));
    expect(screen.getByRole("main", { name: "Stage" })).toContainElement(screen.getByTestId("stage-state"));
    expect(screen.getByRole("complementary", { name: "Agent" })).toContainElement(screen.getByTestId("agent-state"));
    expect(screen.getByRole("region", { name: "Bottom panel" })).toHaveTextContent("bottom");
    expect(shell()).toHaveAttribute("data-layout", "results");
  });

  test("switching layouts keeps every region mounted and remembers the choice per project", () => {
    renderShell();
    fireEvent.click(screen.getByTestId("map-state"));
    fireEvent.click(screen.getByTestId("agent-state"));
    fireEvent.click(screen.getByRole("button", { name: "Lineage first" }));
    expect(shell()).toHaveAttribute("data-layout", "lineage");
    expect(screen.getByTestId("map-state")).toHaveTextContent("1");
    expect(screen.getByTestId("agent-state")).toHaveTextContent("1");
    expect(localStorage.getItem("workbench:layout:/p")).toBe("lineage");
  });

  test("⌘\\ toggles the layout and the divider answers the arrow keys", () => {
    renderShell();
    fireEvent.keyDown(window, { key: "\\", metaKey: true });
    expect(shell()).toHaveAttribute("data-layout", "lineage");
    const divider = screen.getByRole("separator", { name: /map width/i });
    fireEvent.keyDown(divider, { key: "ArrowLeft" });
    expect(shell()).toHaveAttribute("data-layout", "results");
    fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(shell()).toHaveAttribute("data-layout", "lineage");
  });

  test("⌘. folds the Agent into a floating bubble without losing its state", () => {
    renderShell();
    fireEvent.click(screen.getByTestId("agent-state"));
    fireEvent.keyDown(window, { key: ".", metaKey: true });
    expect(shell()).toHaveAttribute("data-agent", "folded");
    expect(screen.getByTestId("agent-state")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Show the Agent" }));
    expect(shell()).toHaveAttribute("data-agent", "open");
    expect(screen.getByTestId("agent-state")).toHaveTextContent("1");
  });


  test("bubble and floating modes release the grid column and keep conversation state", () => {
    renderShell();
    fireEvent.click(screen.getByTestId("agent-state"));
    fireEvent.click(screen.getByRole("button", { name: "Fold the Agent" }));
    expect(shell().style.getPropertyValue("--ws-agent")).toBe("0px");
    fireEvent.click(screen.getByRole("button", { name: "Show the Agent" }));
    expect(screen.getByRole("complementary", { name: "Agent" })).toHaveAttribute("data-mode", "floating");
    expect(shell().style.getPropertyValue("--ws-agent")).toBe("0px");
    fireEvent.click(screen.getByRole("button", { name: "Collapse conversation history" }));
    expect(screen.getByRole("complementary", { name: "Agent" })).toHaveAttribute("data-compact", "true");
    fireEvent.click(screen.getByRole("button", { name: "Fully expand the Agent" }));
    expect(shell().style.getPropertyValue("--ws-agent")).toBe("380px");
    expect(screen.getByTestId("agent-state")).toHaveTextContent("1");
    expect(screen.getByRole("complementary", { name: "Agent" })).toHaveAttribute("data-compact", "false");
  });
  test("width is adjustable in both docked and floating modes", () => {
    renderShell();
    fireEvent.keyDown(screen.getByRole("separator", { name: "Agent width" }), { key: "ArrowLeft" });
    expect(shell().style.getPropertyValue("--ws-agent")).toBe("400px");
    fireEvent.click(screen.getByRole("button", { name: "Float the Agent" }));
    fireEvent.keyDown(screen.getByRole("separator", { name: "Agent width" }), { key: "ArrowRight" });
    expect(screen.getByRole("separator", { name: "Agent width" })).toHaveAttribute("aria-valuenow", "380");
    for (let i = 0; i < 40; i++) fireEvent.keyDown(screen.getByRole("separator", { name: "Agent width" }), { key: "ArrowRight" });
    expect(screen.getByRole("separator", { name: "Agent width" })).toHaveAttribute("aria-valuenow", "280");
  });
  test("docked resizing reserves space for the map and results", () => {
    const previous = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 900 });
    try {
      renderShell();
      for (let i = 0; i < 30; i++) fireEvent.keyDown(screen.getByRole("separator", { name: "Agent width" }), { key: "ArrowLeft" });
      expect(shell().style.getPropertyValue("--ws-agent")).toBe("420px");
      expect(screen.getByRole("separator", { name: "Agent width" })).toHaveAttribute("aria-valuemax", "420");
    } finally {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: previous });
    }
  });
  test("bubble moves with the keyboard without opening and stays in bounds", () => {
    localStorage.setItem("workbench:agent-open", "false");
    renderShell();
    const bubble = screen.getByRole("button", { name: "Show the Agent" });
    for (let i = 0; i < 80; i++) fireEvent.keyDown(bubble, { key: "ArrowLeft" });
    expect(screen.getByRole("complementary", { name: "Agent" }).style.left).toBe("12px");
    expect(shell()).toHaveAttribute("data-agent", "folded");
  });

  test("wide views borrow the wide stage in lineage first and give it back", () => {
    localStorage.setItem("workbench:layout:/p", "lineage");
    const { rerender } = renderShell("data");
    expect(shell()).toHaveAttribute("data-layout", "results");
    expect(screen.getByRole("button", { name: "Lineage first" })).toHaveAttribute("aria-pressed", "true");
    rerender(
      <WorkspaceShell
        projectRoot="/p"
        view="graph"
        topbar={(controls) => <Topbar controls={controls} />}
        stageOpen
        map={() => <Counter testId="map-state" />}
        stage={<Counter testId="stage-state" />}
        agent={<Counter testId="agent-state" />}
        bottom={<div>bottom</div>}
      />,
    );
    expect(shell()).toHaveAttribute("data-layout", "lineage");
  });

  test("each project opens in the layout it was left in", () => {
    localStorage.setItem("workbench:layout:/q", "lineage");
    renderShell("graph", "/q");
    expect(shell()).toHaveAttribute("data-layout", "lineage");
  });

  test("with nothing open the stage steps aside and the map shows the full graph", () => {
    render(
      <WorkspaceShell
        projectRoot="/p"
        view="graph"
        topbar={(controls) => <Topbar controls={controls} />}
        stageOpen={false}
        map={(presentation) => <span data-testid="presentation">{presentation}</span>}
        stage={<div>stage</div>}
        agent={<div>agent</div>}
        bottom={<div>bottom</div>}
      />,
    );
    expect(shell()).toHaveAttribute("data-stage", "closed");
    expect(screen.getByTestId("presentation")).toHaveTextContent("graph");
    expect(screen.queryByRole("separator", { name: /map width/i })).not.toBeInTheDocument();
  });

  test("an open stage in results first narrows the map to the tree", () => {
    render(
      <WorkspaceShell
        projectRoot="/p"
        view="graph"
        topbar={(controls) => <Topbar controls={controls} />}
        stageOpen
        map={(presentation) => <span data-testid="presentation">{presentation}</span>}
        stage={<div>stage</div>}
        agent={<div>agent</div>}
        bottom={<div>bottom</div>}
      />,
    );
    expect(screen.getByTestId("presentation")).toHaveTextContent("tree");
  });
});
