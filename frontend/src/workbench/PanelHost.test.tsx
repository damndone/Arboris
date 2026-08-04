import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PanelHost } from "./PanelHost";

function renderHost(
  activeKind: "node" | "report-review" | null = "report-review",
  initialCollapsed = false,
) {
  return render(
    <PanelHost
      activeKind={activeKind}
      initialCollapsed={initialCollapsed}
      tabs={<div data-testid="panel-tabs">tabs</div>}
      nodePanel={<div data-testid="node-panel">node</div>}
      reportPanel={<div data-testid="report-panel">report</div>}
    />,
  );
}

describe("PanelHost", () => {
  it("renders report review and workspace tabs for the report system tab", () => {
    renderHost("report-review");

    expect(screen.getByTestId("panel-host")).toBeInTheDocument();
    expect(screen.getByTestId("panel-tabs")).toBeInTheDocument();
    expect(screen.getByTestId("report-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("node-panel")).not.toBeInTheDocument();
  });

  it("renders the node panel for a node tab", () => {
    renderHost("node");

    expect(screen.getByTestId("node-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("report-panel")).not.toBeInTheDocument();
  });

  it("renders an honest empty shell when no panel is active", () => {
    renderHost(null);

    const host = screen.getByTestId("panel-host");
    expect(screen.getByTestId("panel-host-empty")).toBeInTheDocument();
    expect(host).toHaveStyle({ width: "0px", flex: "0 0 0px" });
    expect(screen.queryByTestId("panel-tabs")).not.toBeInTheDocument();
    expect(screen.queryByTestId("node-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("report-panel")).not.toBeInTheDocument();
  });

  it("collapses the whole docked host and restores it with a keyboard-accessible handle", () => {
    renderHost("report-review");

    fireEvent.click(screen.getByRole("button", { name: "Collapse right panel" }));

    expect(screen.getByTestId("panel-host")).toHaveAttribute("data-collapsed", "true");
    expect(screen.queryByTestId("report-panel")).not.toBeInTheDocument();

    const restore = screen.getByRole("button", { name: "Expand right panel" });
    expect(restore).toHaveAttribute("aria-expanded", "false");
    expect(restore).toHaveAttribute("data-icon", "expand-left");
    expect(restore.querySelector("svg")).toBeInTheDocument();
    fireEvent.keyDown(restore, { key: "Enter" });

    expect(screen.getByTestId("report-panel")).toBeInTheDocument();
    expect(screen.getByTestId("panel-host")).toHaveAttribute("data-collapsed", "false");
  });

  it("starts collapsed when requested", () => {
    renderHost("node", true);

    expect(screen.getByTestId("panel-host")).toHaveAttribute("data-collapsed", "true");
    expect(screen.getByRole("button", { name: "Expand right panel" })).toBeInTheDocument();
  });

  it("supports a controlled report-review collapse state without rendering a duplicate dock control", () => {
    const onCollapsedChange = vi.fn();
    render(
      <PanelHost
        activeKind="report-review"
        collapsed={false}
        onCollapsedChange={onCollapsedChange}
        tabs={<div data-testid="panel-tabs">tabs</div>}
        nodePanel={<div data-testid="node-panel">node</div>}
        reportPanel={<div data-testid="report-panel">report</div>}
      />,
    );

    expect(screen.queryByRole("button", { name: "Collapse right panel" })).not.toBeInTheDocument();
    expect(screen.getByTestId("panel-host-tabs")).toHaveClass("panel-host-tabs");
  });
});
