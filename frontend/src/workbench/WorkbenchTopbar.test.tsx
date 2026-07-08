// frontend/src/workbench/WorkbenchTopbar.test.tsx
//
// v1.6.8 T11 — topbar project switcher. ProjectSwitcher is exercised
// standalone (it only needs a router), so these tests don't have to stand up
// the full Workbench/Lineage provider stack the topbar itself requires.
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectSwitcher } from "./WorkbenchTopbar";
import { listRecents, touchRecent } from "../launcher/recents";
import { rootToSlug } from "./projectSlug";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

function renderSwitcher(projectRoot = "/tmp/当前项目") {
  return render(
    <MemoryRouter initialEntries={["/p/x/graph"]}>
      <ProjectSwitcher projectRoot={projectRoot} />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProjectSwitcher (T11)", () => {
  it("renders the current project name (basename of projectRoot)", () => {
    renderSwitcher("/tmp/当前项目");
    expect(screen.getByTestId("project-switcher")).toHaveTextContent(
      "当前项目",
    );
  });

  it("dropdown lists recents with the current project marked", () => {
    touchRecent("/tmp/other");
    touchRecent("/tmp/当前项目");
    renderSwitcher("/tmp/当前项目");

    fireEvent.click(screen.getByTestId("project-switcher"));
    const menu = screen.getByTestId("project-switcher-menu");
    expect(menu).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /当前项目/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("menuitem", { name: "other" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("selecting a recent navigates to its graph home and touches recents", () => {
    touchRecent("/tmp/other");
    renderSwitcher("/tmp/当前项目");

    fireEvent.click(screen.getByTestId("project-switcher"));
    fireEvent.click(screen.getByRole("menuitem", { name: "other" }));

    expect(screen.getByTestId("location")).toHaveTextContent(
      `/p/${rootToSlug("/tmp/other")}/graph`,
    );
    expect(listRecents()[0].root).toBe("/tmp/other");
    // Menu closes after selection.
    expect(screen.queryByTestId("project-switcher-menu")).toBeNull();
  });

  it("Escape closes the dropdown menu", () => {
    touchRecent("/tmp/other");
    renderSwitcher("/tmp/当前项目");

    fireEvent.click(screen.getByTestId("project-switcher"));
    expect(screen.getByTestId("project-switcher-menu")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByTestId("project-switcher-menu")).toBeNull();
  });

  it("outside mousedown closes the dropdown menu", () => {
    touchRecent("/tmp/other");
    renderSwitcher("/tmp/当前项目");

    fireEvent.click(screen.getByTestId("project-switcher"));
    expect(screen.getByTestId("project-switcher-menu")).toBeInTheDocument();

    fireEvent.mouseDown(document.body);

    expect(screen.queryByTestId("project-switcher-menu")).toBeNull();
  });

  it("＋ 新建项目… creates a project and hands off directly to genesis upload", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ project_root: "/tmp/fresh" }),
    } as unknown as Response);
    renderSwitcher("/tmp/当前项目");

    fireEvent.click(screen.getByTestId("project-switcher"));
    fireEvent.click(screen.getByTestId("project-switcher-new"));
    expect(screen.getByTestId("create-project-modal")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("parent folder"), {
      target: { value: "/tmp" },
    });
    fireEvent.change(screen.getByLabelText("project name"), {
      target: { value: "fresh" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `/p/${rootToSlug("/tmp/fresh")}/graph?genesis=1`,
      ),
    );
    expect(listRecents()[0].root).toBe("/tmp/fresh");
    expect(screen.queryByTestId("create-project-modal")).toBeNull();
  });
});
