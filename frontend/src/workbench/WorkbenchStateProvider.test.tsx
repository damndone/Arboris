// frontend/src/workbench/WorkbenchStateProvider.test.tsx
//
// V1.5.2 P2 — §7 transition table tests + URL integration.
//
// The §7 transition table is the spec; each row gets at least one
// test asserting the post-state of (selectedKey, activeTabId, focusKey,
// pinned). If a row drifts, this file fails — that's intentional.
//
// Test harness: <MemoryRouter><Provider><Probe/></Provider></MemoryRouter>.
// Probe captures the current `state` and `dispatch` into a ref so each
// `act(() => ref.current.dispatch.foo())` can be followed by ref reads.

import { act, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import {
  WorkbenchStateProvider,
  useWorkbench,
  type WorkbenchContextValue,
} from "./WorkbenchStateProvider";

interface ProbeRef extends WorkbenchContextValue {
  search: string;
}

const ref: { current: ProbeRef | null } = { current: null };

function Probe() {
  const wb = useWorkbench();
  const loc = useLocation();
  ref.current = { ...wb, search: loc.search };
  return null;
}

function renderAt(initialPath: string, validNodeKeys?: ReadonlySet<string>) {
  ref.current = null;
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/"
          element={
            <WorkbenchStateProvider
              runId="r1"
              validNodeKeys={validNodeKeys}
            >
              <Probe />
            </WorkbenchStateProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

function state() {
  return ref.current!.state;
}
function dispatch() {
  return ref.current!.dispatch;
}

describe("WorkbenchStateProvider — initial parsing", () => {
  it("starts with defaults on bare URL", () => {
    renderAt("/");
    expect(state().view).toBe("graph");
    expect(state().selectedKey).toBeNull();
    expect(state().focusKey).toBeNull();
    expect(state().pinned).toBe(false);
    expect(state().searchQuery).toBe("");
    expect(state().bottomPanel).toEqual({ id: "logs", open: false });
  });

  it("hydrates tabs/active/view/focus/pinned/q/panel from URL", () => {
    renderAt(
      "/?view=table&tabs=n1,n2&active=n2&focus=n1&pinned=1&q=income&panel=shell&panelOpen=1",
    );
    expect(state().view).toBe("table");
    expect(state().tabs.map((t) => t.id)).toEqual(["n1", "n2"]);
    expect(state().activeTabId).toBe("n2");
    expect(state().selectedKey).toBe("n2");
    expect(state().focusKey).toBe("n1");
    expect(state().pinned).toBe(true);
    expect(state().searchQuery).toBe("income");
    expect(state().bottomPanel).toEqual({ id: "shell", open: true });
  });

  it("drops focus when validNodeKeys excludes it (plan §7 last row)", () => {
    renderAt("/?focus=ghost&pinned=1", new Set(["real"]));
    expect(state().focusKey).toBeNull();
    expect(state().pinned).toBe(false);
  });

  it("migrates legacy ?node= to tabs/active (useTabs back-compat)", () => {
    renderAt("/?node=legacy");
    expect(state().tabs.map((t) => t.id)).toEqual(["legacy"]);
    expect(state().activeTabId).toBe("legacy");
    expect(state().selectedKey).toBe("legacy");
  });
});

describe("§7 row: Click node on canvas", () => {
  it("sets selected + active + focus when pinned=0", () => {
    renderAt("/");
    act(() => dispatch().selectByCanvasClick("nA"));
    expect(state().selectedKey).toBe("nA");
    expect(state().activeTabId).toBe("nA");
    expect(state().focusKey).toBe("nA");
    expect(state().pinned).toBe(false);
  });

  it("sets selected + active but leaves focus when pinned=1", () => {
    renderAt("/?tabs=nB&active=nB&focus=nB&pinned=1");
    act(() => dispatch().selectByCanvasClick("nA"));
    expect(state().selectedKey).toBe("nA");
    expect(state().activeTabId).toBe("nA");
    expect(state().focusKey).toBe("nB"); // unchanged
    expect(state().pinned).toBe(true);
  });
});

describe("§7 row: Switch drawer tab", () => {
  it("setActive + focus follows when pinned=0", () => {
    renderAt("/?tabs=n1,n2&active=n1");
    act(() => dispatch().selectByTabSwitch("n2"));
    expect(state().activeTabId).toBe("n2");
    expect(state().selectedKey).toBe("n2");
    expect(state().focusKey).toBe("n2");
  });

  it("setActive but focus unchanged when pinned=1", () => {
    renderAt("/?tabs=n1,n2&active=n1&focus=nX&pinned=1");
    act(() => dispatch().selectByTabSwitch("n2"));
    expect(state().activeTabId).toBe("n2");
    expect(state().focusKey).toBe("nX");
  });
});

describe("§7 row: Search result Enter/click", () => {
  it("opens/activates tab, sets focus, unpins, writes q", () => {
    renderAt("/?focus=other&pinned=1");
    act(() => dispatch().selectBySearchCommit("hit", "income"));
    expect(state().selectedKey).toBe("hit");
    expect(state().activeTabId).toBe("hit");
    expect(state().focusKey).toBe("hit");
    expect(state().pinned).toBe(false); // forced to 0
    expect(state().searchQuery).toBe("income");
  });
});

describe("§7 row: Pin upstream path", () => {
  it("sets focus + pinned=1 without touching selected/active", () => {
    renderAt("/?tabs=nA&active=nA");
    act(() => dispatch().pinFocus("nB"));
    expect(state().selectedKey).toBe("nA"); // unchanged
    expect(state().activeTabId).toBe("nA");
    expect(state().focusKey).toBe("nB");
    expect(state().pinned).toBe(true);
  });
});

describe("§7 row: F1 setFocusOnly (focus, not selection)", () => {
  it("sets focus + pinned=0 WITHOUT touching tabs/active/selected", () => {
    renderAt("/?tabs=nA&active=nA");
    act(() => dispatch().setFocusOnly("nB"));
    // The whole point vs selectByCanvasClick: selection is untouched.
    expect(state().tabs.map((t) => t.id)).toEqual(["nA"]);
    expect(state().activeTabId).toBe("nA");
    expect(state().selectedKey).toBe("nA");
    // Only focus moved; never pinned.
    expect(state().focusKey).toBe("nB");
    expect(state().pinned).toBe(false);
  });

  it("overrides an existing pinned focus back to unpinned", () => {
    renderAt("/?tabs=nA&active=nA&focus=nC&pinned=1");
    act(() => dispatch().setFocusOnly("nB"));
    expect(state().focusKey).toBe("nB");
    expect(state().pinned).toBe(false);
    expect(state().selectedKey).toBe("nA"); // still untouched
    expect(state().activeTabId).toBe("nA");
  });

  it("does not create or activate a tab for the focused node", () => {
    renderAt("/?tabs=nA&active=nA");
    act(() => dispatch().setFocusOnly("nB"));
    expect(state().tabs.find((t) => t.id === "nB")).toBeUndefined();
  });
});

describe("§7 row: Unpin path", () => {
  it("focus → selected, pinned → 0", () => {
    renderAt("/?tabs=nA&active=nA&focus=nB&pinned=1");
    act(() => dispatch().unpinFocus());
    expect(state().focusKey).toBe("nA"); // collapsed to selected
    expect(state().pinned).toBe(false);
  });

  it("focus → null when no tab is active", () => {
    renderAt("/?focus=nB&pinned=1");
    act(() => dispatch().unpinFocus());
    expect(state().focusKey).toBeNull();
    expect(state().pinned).toBe(false);
  });
});

describe("§7 row: Close tab containing focus (pinned=1)", () => {
  it("focus survives — anchor outlives the tab", () => {
    renderAt("/?tabs=nA,nB&active=nA&focus=nB&pinned=1");
    act(() => dispatch().closeTab("nB"));
    expect(state().tabs.map((t) => t.id)).toEqual(["nA"]);
    expect(state().focusKey).toBe("nB"); // still pinned even though tab gone
    expect(state().pinned).toBe(true);
  });
});

describe("§7 row: Close tab containing selected", () => {
  it("selected follows new active (useTabs LRU); focus follows when !pinned", () => {
    renderAt("/?tabs=nA,nB&active=nB");
    act(() => dispatch().closeTab("nB"));
    expect(state().tabs.map((t) => t.id)).toEqual(["nA"]);
    expect(state().activeTabId).toBe("nA");
    expect(state().selectedKey).toBe("nA");
    expect(state().focusKey).toBe("nA"); // !pinned → focus follows
  });

  it("when pinned=1, focus does NOT follow new selected", () => {
    renderAt("/?tabs=nA,nB&active=nB&focus=nB&pinned=1");
    act(() => dispatch().closeTab("nB"));
    expect(state().activeTabId).toBe("nA");
    expect(state().focusKey).toBe("nB"); // pinned wins
  });
});

describe("§7 row: Search hover (not committed)", () => {
  it("setHover does not touch URL", () => {
    renderAt("/?q=existing");
    const before = ref.current!.search;
    act(() => dispatch().setHover("preview"));
    expect(state().hoverKey).toBe("preview");
    expect(ref.current!.search).toBe(before); // URL unchanged
    expect(state().searchQuery).toBe("existing"); // q unchanged
  });
});

describe("View / panel / search dispatch", () => {
  it("setView updates URL view param", () => {
    renderAt("/");
    act(() => dispatch().setView("table"));
    expect(state().view).toBe("table");
    expect(new URLSearchParams(ref.current!.search).get("view")).toBe("table");
  });

  it("togglePanel flips panelOpen", () => {
    renderAt("/");
    expect(state().bottomPanel.open).toBe(false);
    act(() => dispatch().togglePanel());
    expect(state().bottomPanel.open).toBe(true);
    expect(new URLSearchParams(ref.current!.search).get("panelOpen")).toBe(
      "1",
    );
  });

  it("setBottomPanel switches active panel id", () => {
    renderAt("/");
    act(() =>
      dispatch().setBottomPanel({ id: "shell", open: true }),
    );
    expect(state().bottomPanel).toEqual({ id: "shell", open: true });
  });

  it("clearSearch removes q and resets searchCursor", () => {
    renderAt("/?q=income");
    act(() => dispatch().setSearchCursor(3));
    expect(state().searchCursor).toBe(3);
    act(() => dispatch().clearSearch());
    expect(state().searchQuery).toBe("");
    expect(state().searchCursor).toBeNull();
    expect(new URLSearchParams(ref.current!.search).get("q")).toBeNull();
  });
});

describe("contextMenu (Tier 3)", () => {
  it("open + close are memory-only", () => {
    renderAt("/");
    const before = ref.current!.search;
    act(() =>
      dispatch().openContextMenu({ nodeKey: "n1", x: 10, y: 20 }),
    );
    expect(state().contextMenu).toEqual({ nodeKey: "n1", x: 10, y: 20 });
    expect(ref.current!.search).toBe(before);
    act(() => dispatch().closeContextMenu());
    expect(state().contextMenu).toBeNull();
  });
});
