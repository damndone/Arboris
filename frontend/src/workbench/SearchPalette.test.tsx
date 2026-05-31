// frontend/src/workbench/SearchPalette.test.tsx
//
// V1.5.2 P7 — ⌘K palette behaviour tests. Plan §10.

import "@testing-library/jest-dom/vitest";
import {
  act,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { describe, expect, it } from "vitest";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { SearchPalette } from "./SearchPalette";
import { LineageContext, type LineageContextValue } from "../lineage/LineageContext";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../lineage/api/graphViewTypes";

function n(
  id: string,
  overrides: Partial<GraphViewNode> = {},
): GraphViewNode {
  return {
    id,
    nodeKey: id,
    raw: null,
    stage: "model",
    kind: "model",
    title: id,
    parentStageId: null,
    trust: "ok",
    decisions: [],
    ...overrides,
  };
}

function model(): GraphViewModel {
  return {
    schemaVersion: 3,
    runId: "r1",
    legacy: false,
    nodes: [
      n("raw", { title: "Raw CSV", kind: "dataset_stage" }),
      n("income", { title: "income", kind: "variable" }),
      n("log_income", { title: "log_income", kind: "income_var" }),
      n("model:ols", { title: "OLS Primary", kind: "model" }),
    ],
    edges: [],
    stats: { nodeCount: 4, edgeCount: 0, leafCount: 4, hasDpCount: 0 },
  };
}

let lastSearch = "";
function CaptureLocation() {
  lastSearch = useLocation().search;
  return null;
}

function mountAt(path: string) {
  lastSearch = "";
  const ctx: LineageContextValue = {
    model: model(),
    selectedKey: null,
    select: () => {},
  };
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={
            <WorkbenchStateProvider runId="r1">
              <LineageContext.Provider value={ctx}>
                <SearchPalette />
                <CaptureLocation />
              </LineageContext.Provider>
            </WorkbenchStateProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SearchPalette", () => {
  it("is hidden by default", () => {
    mountAt("/");
    expect(screen.queryByTestId("search-palette")).toBeNull();
  });

  it("⌘K opens the palette; Escape closes it", () => {
    mountAt("/");
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    expect(screen.getByTestId("search-palette")).toBeInTheDocument();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.queryByTestId("search-palette")).toBeNull();
  });

  it("Ctrl+K also toggles (cross-platform)", () => {
    mountAt("/");
    act(() => {
      fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    });
    expect(screen.getByTestId("search-palette")).toBeInTheDocument();
  });

  it("typing in the input does NOT write q to URL (only commit does)", () => {
    mountAt("/");
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    const input = screen.getByTestId("search-palette-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "income" } });
    // URL must still not contain q=
    expect(lastSearch).not.toContain("q=");
  });

  it("filters via snapshot.searchIndex substring match", () => {
    mountAt("/");
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    const input = screen.getByTestId("search-palette-input");
    fireEvent.change(input, { target: { value: "income" } });
    // Two nodes match "income": the `income` variable and `log_income`.
    // Each kind (node + variable) projects independently — so we expect
    // at least the two node entries plus matching variable entries.
    const hits = screen.getAllByTestId(/search-palette-hit-/);
    expect(hits.length).toBeGreaterThanOrEqual(2);
    const text = hits.map((h) => h.textContent ?? "").join(" | ");
    expect(text).toContain("income");
    expect(text).toContain("log_income");
  });

  it("Enter commits the cursor's hit — writes q= and selects nodeKey", () => {
    mountAt("/");
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    const input = screen.getByTestId("search-palette-input");
    fireEvent.change(input, { target: { value: "ols" } });
    act(() => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    // Commit closes the palette and writes URL.
    expect(screen.queryByTestId("search-palette")).toBeNull();
    expect(lastSearch).toContain("q=ols");
    // selectBySearchCommit opens a tab + sets active — URL has tabs/active.
    expect(lastSearch).toContain("tabs=model%3Aols");
    expect(lastSearch).toContain("active=model%3Aols");
  });

  it("click on a result row commits the same way as Enter", () => {
    mountAt("/");
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    const input = screen.getByTestId("search-palette-input");
    fireEvent.change(input, { target: { value: "raw" } });
    const firstHit = screen.getByTestId("search-palette-hit-0");
    fireEvent.click(firstHit);
    expect(screen.queryByTestId("search-palette")).toBeNull();
    expect(lastSearch).toContain("q=raw");
  });

  it("F4: ⌘K is ignored while a textarea is focused (does NOT open)", () => {
    mountAt("/");
    // Simulate the user editing text elsewhere (e.g. detail drawer).
    const textarea = document.createElement("textarea");
    document.body.appendChild(textarea);
    textarea.focus();
    expect(document.activeElement).toBe(textarea);

    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    // Palette must stay closed — the keystroke belongs to the textarea.
    expect(screen.queryByTestId("search-palette")).toBeNull();

    document.body.removeChild(textarea);
  });

  it("F4: ⌘K still toggles closed when the palette's own input is focused", () => {
    mountAt("/");
    // Open it (focus is on body here, so the guard doesn't trip).
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    expect(screen.getByTestId("search-palette")).toBeInTheDocument();
    // The palette autofocuses its input — even though that's an
    // editable target, ⌘K should close it because `open` is true.
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    expect(screen.queryByTestId("search-palette")).toBeNull();
  });

  it("ArrowDown moves the cursor; cursor row has data-active=true", () => {
    mountAt("/");
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    const input = screen.getByTestId("search-palette-input");
    fireEvent.change(input, { target: { value: "income" } });
    // Initially cursor=0
    expect(screen.getByTestId("search-palette-hit-0")).toHaveAttribute(
      "data-active",
      "true",
    );
    act(() => {
      fireEvent.keyDown(input, { key: "ArrowDown" });
    });
    expect(screen.getByTestId("search-palette-hit-1")).toHaveAttribute(
      "data-active",
      "true",
    );
  });
});
