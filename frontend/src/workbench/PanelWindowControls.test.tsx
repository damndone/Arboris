import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PanelWindowControls } from "./PanelWindowControls";

describe("PanelWindowControls", () => {
  it("offers float and pin for a docked surface, with nothing to collapse", () => {
    const onFloat = vi.fn();
    const onPin = vi.fn();
    const onCollapse = vi.fn();

    render(
      <PanelWindowControls
        surface="node panel"
        floating={false}
        pinned={false}
        collapsed={false}
        onFloat={onFloat}
        onPin={onPin}
        onCollapse={onCollapse}
      />,
    );

    expect(screen.getByRole("group", { name: "node panel window controls" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Float node panel" })).toHaveAttribute("data-icon", "float");
    expect(screen.getByRole("button", { name: "Pin node panel" })).toHaveAttribute("data-icon", "pin");
    // A docked panel has nothing to fold; the button used to do nothing there.
    expect(screen.queryByRole("button", { name: "Collapse node panel" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Float node panel" }));
    fireEvent.click(screen.getByRole("button", { name: "Pin node panel" }));

    expect(onFloat).toHaveBeenCalledOnce();
    expect(onPin).toHaveBeenCalledOnce();
    expect(onCollapse).not.toHaveBeenCalled();
  });

  it("uses dock, unpin, and expand actions for a pinned collapsed floating surface", () => {
    render(
      <PanelWindowControls
        surface="report review"
        floating
        pinned
        collapsed
        onDock={vi.fn()}
        onUnpin={vi.fn()}
        onExpand={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Dock report review" })).toHaveAttribute("data-icon", "dock");
    expect(screen.getByRole("button", { name: "Unpin report review" })).toHaveAttribute("data-icon", "pin");
    expect(screen.getByRole("button", { name: "Expand report review" })).toHaveAttribute("data-icon", "expand");
    expect(screen.getByRole("button", { name: "Unpin report review" })).toHaveClass(
      "panel-window-controls__icon-button--active",
    );
  });
});
