// v1.6.8 T10 — Launcher: recent projects (localStorage) + create-project
// modal. Mirrors App.test.tsx conventions: MemoryRouter + <App/>,
// vi.stubGlobal fetch, jsonResponse helper. The launcher renders under
// AppShell's Outlet, so we exercise it through <App/> at "/".
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../App";
import { listRecents, touchRecent } from "./recents";

type FetchInit = { status?: number; ok?: boolean };

function jsonResponse(body: unknown, init: FetchInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

type RouteFn = (url: string, init?: RequestInit) => Response | Promise<Response>;
function installFetchRouter(route: RouteFn) {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (url: unknown, init?: RequestInit) => {
      const u = typeof url === "string" ? url : String(url);
      return Promise.resolve(route(u, init));
    }
  );
}

function renderAt(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  try {
    localStorage.clear();
  } catch {
    // ignore
  }
  try {
    sessionStorage.clear();
  } catch {
    // ignore
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LauncherRoute", () => {
  it("renders recent projects as cards (name + full root)", () => {
    touchRecent("/Users/me/项目规划/示例");
    touchRecent("/tmp/alpha");
    renderAt("/");

    // Most-recent first; project name = last path segment, full root visible.
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("/tmp/alpha")).toBeInTheDocument();
    expect(screen.getByText("示例")).toBeInTheDocument();
    expect(screen.getByText("/Users/me/项目规划/示例")).toBeInTheDocument();
  });

  it("clicking a recent card probes the project then navigates to /p/<slug>/graph", async () => {
    touchRecent("/tmp/alpha");
    installFetchRouter((url) => {
      if (url.includes("/runs")) return jsonResponse({ runs: [] });
      throw new Error(`unexpected fetch ${url}`);
    });
    renderAt("/");

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    expect(await screen.findByTestId("project-graph-route")).toBeInTheDocument();
    // A successful open re-touches the recent.
    expect(listRecents()[0].root).toBe("/tmp/alpha");
  });

  it("create modal: opens, creates the project, navigates, and records the recent", async () => {
    installFetchRouter((url, init) => {
      if (url.includes("/projects") && init?.method === "POST") {
        return jsonResponse({ project_root: "/tmp/demo" });
      }
      if (url.includes("/runs")) return jsonResponse({ runs: [] });
      throw new Error(`unexpected fetch ${url}`);
    });
    renderAt("/");

    fireEvent.click(screen.getByRole("button", { name: "新建项目" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("parent folder"), {
      target: { value: "/tmp" },
    });
    fireEvent.change(screen.getByLabelText("project name"), {
      target: { value: "demo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByTestId("project-graph-route")).toBeInTheDocument();

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "POST"
    );
    expect(postCall).toBeTruthy();
    expect(String(postCall?.[0])).toContain("/projects");
    expect(listRecents()[0].root).toBe("/tmp/demo");
  });

  it("create modal validation: empty parent or bad name disables Create", () => {
    renderAt("/");
    fireEvent.click(screen.getByRole("button", { name: "新建项目" }));

    // Empty parent → disabled.
    const create = screen.getByRole("button", { name: "Create project" });
    expect(create).toBeDisabled();

    // Valid parent + name → enabled.
    fireEvent.change(screen.getByLabelText("parent folder"), {
      target: { value: "/tmp" },
    });
    expect(create).toBeEnabled();

    // Path separator in name → disabled again.
    fireEvent.change(screen.getByLabelText("project name"), {
      target: { value: "a/b" },
    });
    expect(create).toBeDisabled();

    // Empty name → disabled.
    fireEvent.change(screen.getByLabelText("project name"), {
      target: { value: "" },
    });
    expect(create).toBeDisabled();
  });

  it("stale recent: PROJECT_NOT_FOUND marks the card 失效 with 移除, no navigation", async () => {
    touchRecent("/gone/project");
    installFetchRouter((url) => {
      if (url.includes("/runs")) {
        return jsonResponse(
          { error: { code: "PROJECT_NOT_FOUND", message: "Project not found", details: {} } },
          { status: 404 }
        );
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    renderAt("/");

    fireEvent.click(screen.getByRole("button", { name: /project/ }));

    expect(await screen.findByText("失效")).toBeInTheDocument();
    expect(screen.queryByTestId("project-graph-route")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "移除" }));
    await waitFor(() => {
      expect(screen.queryByText("/gone/project")).not.toBeInTheDocument();
    });
    expect(listRecents()).toEqual([]);
  });

  it("corrupt localStorage → empty state with a hint", () => {
    localStorage.setItem("workbench.recentProjects.v1", "{not json");
    renderAt("/");
    expect(screen.getByText("最近项目将显示在这里。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建项目" })).toBeInTheDocument();
  });
});
