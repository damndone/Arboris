import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RecentProjectsPanel } from "./RecentProjectsPanel";
import { listRecents, touchRecent } from "./recents";
import { rootToSlug } from "../workbench/projectSlug";

function Harness() {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <RecentProjectsPanel
        onOpenProject={(root) => navigate(`/p/${rootToSlug(root)}`)}
      />
      <output data-testid="panel-location">{location.pathname}</output>
    </>
  );
}

describe("RecentProjectsPanel", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => vi.restoreAllMocks());

  it("renders an explicit empty state", () => {
    render(<RecentProjectsPanel onOpenProject={vi.fn()} />);
    expect(screen.getByText("Recent projects appear here."))
      .toBeInTheDocument();
  });

  it("probes, opens, and reorders a recent project", async () => {
    touchRecent("/tmp/older");
    touchRecent("/tmp/project");
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ runs: [] }),
    });
    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /project/ }));
    expect(await screen.findByTestId("panel-location")).toHaveTextContent(
      `/p/${rootToSlug("/tmp/project")}`,
    );
    expect(listRecents()[0].root).toBe("/tmp/project");
  });

  it("marks missing projects stale and lets the user remove them", async () => {
    touchRecent("/tmp/gone");
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 404,
      json: () =>
        Promise.resolve({
          error: { code: "PROJECT_NOT_FOUND", message: "missing", details: {} },
        }),
    });
    render(<RecentProjectsPanel onOpenProject={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /gone/ }));
    expect(await screen.findByText("stale")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(listRecents()).toEqual([]));
  });
});
