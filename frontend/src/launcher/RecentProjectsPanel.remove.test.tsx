// Removing a project from the Home list.
//
// The remove button existed but only appeared once a project had gone stale,
// so a healthy project could never be taken off the list. The wording matters
// too: this clears the entry, it does not delete anything on disk.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RecentProjectsPanel } from "./RecentProjectsPanel";
import { touchRecent } from "./recents";

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

describe("RecentProjectsPanel removal", () => {
  it("offers removal for a healthy project, not only a stale one", () => {
    touchRecent("/p/alpha");

    render(<RecentProjectsPanel onOpenProject={vi.fn()} />);

    expect(screen.getByTestId("recent-remove-/p/alpha")).toBeInTheDocument();
  });

  it("says it only clears the list entry, not the files", () => {
    touchRecent("/p/alpha");

    render(<RecentProjectsPanel onOpenProject={vi.fn()} />);

    expect(screen.getByTestId("recent-remove-/p/alpha")).toHaveAttribute(
      "title",
      expect.stringContaining("left alone") as unknown as string,
    );
  });

  it("drops the entry when removed", () => {
    touchRecent("/p/alpha");
    touchRecent("/p/beta");
    render(<RecentProjectsPanel onOpenProject={vi.fn()} />);

    fireEvent.click(screen.getByTestId("recent-remove-/p/alpha"));

    expect(screen.queryByTestId("recent-remove-/p/alpha")).toBeNull();
    expect(screen.getByTestId("recent-remove-/p/beta")).toBeInTheDocument();
  });
});
