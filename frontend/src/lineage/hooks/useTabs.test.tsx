import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { useTabs, type UseTabsResult } from "./useTabs";

interface HarnessRef extends UseTabsResult {
  search: string;
}

const ref: { current: HarnessRef | null } = { current: null };

function Harness() {
  const tabs = useTabs();
  const location = useLocation();
  ref.current = { ...tabs, search: location.search };
  return (
    <div data-testid="probe">
      tabs={tabs.tabs.map((t) => t.id).join(",")} active={tabs.activeTabId ?? ""}
      {" "}search={location.search}
    </div>
  );
}

function renderAt(initialPath: string) {
  ref.current = null;
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/" element={<Harness />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("useTabs", () => {
  it("openTab creates a tab and makes it active", () => {
    renderAt("/");

    act(() => ref.current!.openTab("n1"));

    expect(ref.current!.tabs.map((t) => t.id)).toEqual(["n1"]);
    expect(ref.current!.activeNodeKey).toBe("n1");
    const params = new URLSearchParams(ref.current!.search);
    expect(params.get("tabs")).toBe("n1");
    expect(params.get("active")).toBe("n1");
  });

  it("openTab focuses an existing tab without duplicating it", () => {
    renderAt("/?tabs=a,b&active=a");

    act(() => ref.current!.openTab("b"));

    expect(ref.current!.tabs.map((t) => t.id)).toEqual(["a", "b"]);
    expect(ref.current!.activeNodeKey).toBe("b");
  });

  it("closeTab on the active tab activates the next neighbour", () => {
    renderAt("/?tabs=a,b,c&active=b");

    act(() => ref.current!.closeTab("b"));

    expect(ref.current!.tabs.map((t) => t.id)).toEqual(["a", "c"]);
    expect(ref.current!.activeNodeKey).toBe("c");
  });

  it("closeTab on the last tab clears active state and URL tab params", () => {
    renderAt("/?tabs=a&active=a&tab=lineage");

    act(() => ref.current!.closeTab("a"));

    expect(ref.current!.tabs).toEqual([]);
    expect(ref.current!.activeNodeKey).toBeNull();
    const params = new URLSearchParams(ref.current!.search);
    expect(params.get("tabs")).toBeNull();
    expect(params.get("active")).toBeNull();
    expect(params.get("tab")).toBe("lineage");
  });

  it("evicts the oldest tab before opening the 9th tab", () => {
    renderAt("/");

    act(() => {
      for (let i = 1; i <= 9; i += 1) ref.current!.openTab(`n${i}`);
    });

    expect(ref.current!.tabs.map((t) => t.id)).toEqual([
      "n2",
      "n3",
      "n4",
      "n5",
      "n6",
      "n7",
      "n8",
      "n9",
    ]);
    expect(ref.current!.activeNodeKey).toBe("n9");
    expect(ref.current!.lastEvictedTabId).toBe("n1");
  });

  it("round-trips tabs and active state from the URL", () => {
    renderAt("/?tabs=a,b&active=b");

    expect(ref.current!.tabs.map((t) => t.id)).toEqual(["a", "b"]);
    expect(ref.current!.activeNodeKey).toBe("b");
  });

  it("setActive is a no-op when the tab is already active", () => {
    renderAt("/?tabs=a,b&active=b");
    const before = ref.current!.search;

    act(() => ref.current!.setActive("b"));

    expect(ref.current!.search).toBe(before);
    expect(ref.current!.tabs.map((t) => t.id)).toEqual(["a", "b"]);
    expect(ref.current!.activeNodeKey).toBe("b");
  });

  it("multiple opens preserve open order", () => {
    renderAt("/");

    act(() => {
      ref.current!.openTab("a");
      ref.current!.openTab("b");
      ref.current!.openTab("c");
    });

    expect(ref.current!.tabs.map((t) => t.id)).toEqual(["a", "b", "c"]);
    expect(screen.getByTestId("probe")).toHaveTextContent("active=c");
  });

  it("uses legacy ?node= as the initial active tab when tabs are absent", () => {
    renderAt("/?node=legacy&tab=lineage");

    expect(ref.current!.tabs.map((t) => t.id)).toEqual(["legacy"]);
    expect(ref.current!.activeNodeKey).toBe("legacy");
  });
});
