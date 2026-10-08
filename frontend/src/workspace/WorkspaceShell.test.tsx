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

  test("⌘. folds the Agent into a rail without losing its state", () => {
    renderShell();
    fireEvent.click(screen.getByTestId("agent-state"));
    fireEvent.keyDown(window, { key: ".", metaKey: true });
    expect(shell()).toHaveAttribute("data-agent", "folded");
    expect(screen.getByTestId("agent-state")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Show the Agent" }));
    expect(shell()).toHaveAttribute("data-agent", "open");
    expect(screen.getByTestId("agent-state")).toHaveTextContent("1");
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
