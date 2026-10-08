import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";
import { WorkspaceTopbar, WORKSPACE_VIEWS } from "./WorkspaceTopbar";
import type { LayoutControls } from "./WorkspaceShell";

function controls(overrides: Partial<LayoutControls> = {}): LayoutControls {
  return {
    layout: "results",
    effective: "results",
    setLayout: vi.fn(),
    toggleLayout: vi.fn(),
    agentOpen: true,
    toggleAgent: vi.fn(),
    mapHidden: false,
    toggleMap: vi.fn(),
    ...overrides,
  };
}

function renderTopbar(props: Partial<Parameters<typeof WorkspaceTopbar>[0]> = {}) {
  const handlers = { onView: vi.fn(), onHome: vi.fn(), onOpenSettings: vi.fn(), onNewAnalysis: vi.fn() };
  render(
    <MemoryRouter>
      <WorkspaceTopbar projectRoot="/work/returns" view="graph" controls={controls()} actions={null} {...handlers} {...props} />
    </MemoryRouter>,
  );
  return handlers;
}

describe("WorkspaceTopbar", () => {
  test("views follow the working order and map onto the existing view modes", () => {
    expect(WORKSPACE_VIEWS.map((v) => [v.label, v.id])).toEqual([
      ["Data", "data"],
      ["Analysis", "graph"],
      ["Tables", "table"],
      ["Report", "report"],
      ["Plans", "notebook"],
    ]);
    const { onView } = renderTopbar();
    const tabs = within(screen.getByRole("tablist", { name: "View" })).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Data", "Analysis", "Tables", "Report", "Plans"]);
    expect(screen.getByRole("tab", { name: "Analysis" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Tables" }));
    expect(onView).toHaveBeenCalledWith("table");
  });

  test("the layout switch shows the chosen layout and switches it", () => {
    const setLayout = vi.fn();
    renderTopbar({ controls: controls({ layout: "lineage", effective: "results", setLayout }) });
    const group = screen.getByRole("group", { name: "Layout" });
    expect(within(group).getByRole("button", { name: /Lineage first/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(group).getByRole("button", { name: /Results first/ }));
    expect(setLayout).toHaveBeenCalledWith("results");
  });

  test("search opens the node search, and home, settings and new analysis are one click away", () => {
    const keydown = vi.fn();
    window.addEventListener("keydown", keydown);
    const { onHome, onOpenSettings, onNewAnalysis } = renderTopbar();
    fireEvent.click(screen.getByRole("button", { name: /Search/ }));
    expect(keydown).toHaveBeenCalledWith(expect.objectContaining({ key: "k", metaKey: true }));
    window.removeEventListener("keydown", keydown);
    fireEvent.click(screen.getByRole("button", { name: "Arboris home" }));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "New analysis" }));
    expect(onHome).toHaveBeenCalled();
    expect(onOpenSettings).toHaveBeenCalled();
    expect(onNewAnalysis).toHaveBeenCalled();
  });

  test("the map toggle exists only where there is a map column to hide", () => {
    const toggleMap = vi.fn();
    renderTopbar({ controls: controls({ toggleMap }) });
    fireEvent.click(screen.getByRole("button", { name: "Hide the map" }));
    expect(toggleMap).toHaveBeenCalled();
  });

  test("lineage first has no map toggle", () => {
    renderTopbar({ controls: controls({ layout: "lineage", effective: "lineage" }) });
    expect(screen.queryByRole("button", { name: /the map/ })).not.toBeInTheDocument();
  });
});
