// frontend/src/lineage/hooks/useSelectedNode.test.tsx
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { useSelectedNode } from "./useSelectedNode";

// We exercise the hook through a tiny harness that surfaces both the hook's
// return value AND the active URL — that lets us assert URL mutations
// without poking react-router internals.

interface HarnessRef {
  selectedKey: string | null;
  select: (key: string | null) => void;
  search: string;
}

const ref: { current: HarnessRef | null } = { current: null };

function Harness() {
  const { selectedKey, select } = useSelectedNode();
  const location = useLocation();
  ref.current = { selectedKey, select, search: location.search };
  return (
    <div data-testid="probe">
      key={String(selectedKey)} search={location.search}
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

describe("useSelectedNode", () => {
  it("returns null when ?node= is absent", () => {
    renderAt("/");
    expect(ref.current!.selectedKey).toBeNull();
  });

  it("reads ?node=foo from the URL", () => {
    renderAt("/?node=foo");
    expect(ref.current!.selectedKey).toBe("foo");
  });

  it("select('k1') writes ?node=k1", () => {
    renderAt("/");
    act(() => ref.current!.select("k1"));
    expect(ref.current!.selectedKey).toBe("k1");
    expect(ref.current!.search).toBe("?node=k1");
  });

  it("select(null) removes the ?node= param", () => {
    renderAt("/?node=k1");
    act(() => ref.current!.select(null));
    expect(ref.current!.selectedKey).toBeNull();
    expect(ref.current!.search).toBe("");
  });

  it("select() preserves unrelated query params (immutable update)", () => {
    renderAt("/?tab=lineage&filter=warning");
    act(() => ref.current!.select("k2"));
    const params = new URLSearchParams(ref.current!.search);
    expect(params.get("node")).toBe("k2");
    expect(params.get("tab")).toBe("lineage");
    expect(params.get("filter")).toBe("warning");
  });

  it("?node= (empty value) is normalised to null [REV-3 #2]", () => {
    // URLSearchParams.get returns "" for `?node=`. Without the empty-string
    // guard, downstream consumers would treat "" as a selection and render
    // an empty drawer for a non-existent node.
    renderAt("/?node=");
    expect(ref.current!.selectedKey).toBeNull();
  });

  it("probe DOM reflects the final state", () => {
    renderAt("/?node=initial");
    expect(screen.getByTestId("probe").textContent).toContain("key=initial");
    act(() => ref.current!.select("changed"));
    expect(screen.getByTestId("probe").textContent).toContain("key=changed");
  });
});
