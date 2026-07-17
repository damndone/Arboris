import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkbenchHomeView } from "./WorkbenchHomeView";
import { listRecents, touchRecent } from "../../launcher/recents";

describe("WorkbenchHomeView", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows current/recent projects, create/settings actions, and no graph canvas", async () => {
    touchRecent("/tmp/other");
    touchRecent("/tmp/current");
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        configured: true,
        provider_name: "DeepSeek",
        model: "deepseek-chat",
        context_window_tokens: 1_000_000,
        supports_1m: true,
        key_present: true,
      }),
    });
    const onCreateProject = vi.fn();
    const onOpenSettings = vi.fn();
    render(
      <WorkbenchHomeView
        projectRoot="/tmp/current"
        onCreateProject={onCreateProject}
        onOpenSettings={onOpenSettings}
      />,
    );

    expect(screen.getByTestId("workbench-home")).toBeInTheDocument();
    expect(screen.getByTestId("workbench-home-current-project")).toHaveTextContent("current");
    expect(screen.getByTestId("workbench-home-recent-/tmp/other")).toBeInTheDocument();
    expect(screen.queryByTestId("graph-workbench")).toBeNull();
    fireEvent.click(screen.getByTestId("workbench-home-new-project"));
    fireEvent.click(screen.getByTestId("workbench-home-settings"));
    expect(onCreateProject).toHaveBeenCalledOnce();
    expect(onOpenSettings).toHaveBeenCalledOnce();

    expect(await screen.findByTestId("workbench-home-llm-ready")).toHaveTextContent("1.0M tokens");
    expect(screen.getByTestId("workbench-home-llm-ready")).toHaveTextContent("Supported");
  });

  it("has an explicit zero-recents state and handles LLM errors without spinning forever", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("offline"));
    render(<WorkbenchHomeView onOpenSettings={vi.fn()} />);

    expect(screen.getByTestId("workbench-home-empty-recent")).toBeInTheDocument();
    expect(await screen.findByTestId("workbench-home-llm-error")).toHaveTextContent("offline");
    expect(screen.queryByTestId("workbench-home-llm-loading")).toBeNull();
  });

  it("opens a recent project through the callback", async () => {
    touchRecent("/tmp/other");
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ configured: false, supports_1m: false }),
    });
    const onOpenProject = vi.fn();
    render(<WorkbenchHomeView onOpenProject={onOpenProject} />);
    fireEvent.click(screen.getByTestId("workbench-home-recent-/tmp/other"));
    await waitFor(() => {
      expect(onOpenProject).toHaveBeenCalledWith("/tmp/other");
      expect(screen.getByTestId("workbench-home-llm-ready")).toBeInTheDocument();
    });
  });

  it("reconciles missing recents and records the current project", async () => {
    touchRecent("/gone/project");
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation((url: unknown) => {
      const requestUrl = String(url);
      if (requestUrl.includes("gone%2Fproject")) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({
            error: { code: "PROJECT_NOT_FOUND", message: "Project not found", details: {} },
          }),
        });
      }
      if (requestUrl.includes("/runs")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ runs: [] }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ configured: false, supports_1m: false }),
      });
    });
    const onOpenProject = vi.fn();
    render(
      <WorkbenchHomeView
        projectRoot="/tmp/current"
        onOpenProject={onOpenProject}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("workbench-home-recent-/gone/project")).not.toBeInTheDocument();
      expect(screen.getByTestId("workbench-home-recent-/tmp/current")).toBeInTheDocument();
    });
    expect(listRecents().map((recent) => recent.root)).toEqual(["/tmp/current"]);
    expect(onOpenProject).not.toHaveBeenCalled();
  });

  it("removes a missing recent on click without leaving a dead-route error", async () => {
    touchRecent("/gone/project");
    let runsCalls = 0;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation((url: unknown) => {
      const requestUrl = String(url);
      if (requestUrl.includes("/runs")) {
        runsCalls += 1;
        if (runsCalls === 1) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve({ runs: [] }),
          });
        }
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({
            error: { code: "PROJECT_NOT_FOUND", message: "Project not found", details: {} },
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ configured: false, supports_1m: false }),
      });
    });
    const onOpenProject = vi.fn();
    render(<WorkbenchHomeView onOpenProject={onOpenProject} />);

    fireEvent.click(screen.getByTestId("workbench-home-recent-/gone/project"));

    await waitFor(() => {
      expect(listRecents()).toEqual([]);
      expect(screen.queryByTestId("workbench-home-recent-/gone/project")).not.toBeInTheDocument();
    });
    expect(onOpenProject).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Project missing or moved")).not.toBeInTheDocument();
  });
});
