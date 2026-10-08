import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test } from "vitest";
import { WorkspaceBottomPanel, type BottomTab } from "./WorkspaceBottomPanel";

const tabs: BottomTab[] = [
  { id: "runs", label: "Runs", render: () => <p>runs body</p> },
  { id: "logs", label: "Logs", render: () => <p>logs body</p> },
  { id: "activity", label: "Activity", render: () => <p>activity body</p> },
];

describe("WorkspaceBottomPanel", () => {
  beforeEach(() => sessionStorage.clear());

  test("starts folded to one row of tabs; choosing a tab opens it", () => {
    render(<WorkspaceBottomPanel projectRoot="/p" tabs={tabs} />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Runs", "Logs", "Activity"]);
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Logs" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("logs body");
    expect(screen.getByRole("tab", { name: "Logs" })).toHaveAttribute("aria-selected", "true");
  });

  test("folds and remembers the tab, open state and height for the session", () => {
    const { unmount } = render(<WorkspaceBottomPanel projectRoot="/p" tabs={tabs} />);
    fireEvent.click(screen.getByRole("tab", { name: "Activity" }));
    fireEvent.keyDown(screen.getByRole("separator", { name: "Bottom panel height" }), { key: "ArrowUp" });
    unmount();
    render(<WorkspaceBottomPanel projectRoot="/p" tabs={tabs} />);
    expect(screen.getByRole("tabpanel")).toHaveTextContent("activity body");
    expect(screen.getByRole("separator", { name: "Bottom panel height" })).toHaveAttribute("aria-valuenow", "264");
    fireEvent.click(screen.getByRole("button", { name: "Fold the bottom panel" }));
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
  });
});
