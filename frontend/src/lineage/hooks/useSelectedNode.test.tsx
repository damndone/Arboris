// frontend/src/lineage/hooks/useSelectedNode.test.tsx
import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { useSelectedNode } from "./useSelectedNode";
import type { GraphViewNode } from "../api/graphViewTypes";

// We exercise the hook through a tiny harness that surfaces both the hook's
// return value AND the active URL — that lets us assert URL mutations
// without poking react-router internals.

interface HarnessRef {
  selectedKey: string | null;
  select: (key: string | null) => void;
  search: string;
}

const ref: { current: HarnessRef | null } = { current: null };

function node(id: string, trust: GraphViewNode["trust"] = "ok"): GraphViewNode {
  return {
    id,
    nodeKey: id,
    raw: null,
    stage: "unknown",
    kind: "dataset_stage",
    title: id,
    parentStageId: null,
    trust,
    decisions: [],
  };
}

function Harness({
  nodes,
  autoSelectScope,
}: {
  nodes?: GraphViewNode[];
  autoSelectScope?: string | null;
}) {
  const { selectedKey, select } = useSelectedNode(nodes, autoSelectScope);
  const location = useLocation();
  ref.current = { selectedKey, select, search: location.search };
  return (
    <div data-testid="probe">
      key={String(selectedKey)} search={location.search}
    </div>
  );
}

function routeElement(nodes?: GraphViewNode[], autoSelectScope?: string | null) {
  return (
    <Routes>
      <Route
        path="/"
        element={<Harness nodes={nodes} autoSelectScope={autoSelectScope} />}
      />
    </Routes>
  );
}

function renderAt(
  initialPath: string,
  nodes?: GraphViewNode[],
  autoSelectScope?: string | null,
) {
  ref.current = null;
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      {routeElement(nodes, autoSelectScope)}
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

  it("auto-selects the first review node when no ?node= is present", async () => {
    renderAt("/", [
      node("ok"),
      node("caution", "caution"),
      node("review", "review"),
    ]);

    await waitFor(() => expect(ref.current!.selectedKey).toBe("review"));
    expect(new URLSearchParams(ref.current!.search).get("node")).toBe("review");
  });

  it("auto-selects the first caution node when no review node exists", async () => {
    renderAt("/", [node("ok"), node("caution", "caution")]);

    await waitFor(() => expect(ref.current!.selectedKey).toBe("caution"));
    expect(new URLSearchParams(ref.current!.search).get("node")).toBe("caution");
  });

  it("does not auto-select when every node is ok", async () => {
    renderAt("/", [node("ok-1"), node("ok-2")]);

    await waitFor(() => expect(ref.current!.selectedKey).toBeNull());
    expect(ref.current!.search).toBe("");
  });

  it("does not override an explicit ?node= value", async () => {
    renderAt("/?node=other", [node("review", "review")]);

    await waitFor(() => expect(ref.current!.selectedKey).toBe("other"));
    expect(new URLSearchParams(ref.current!.search).get("node")).toBe("other");
  });

  it("does not re-select after the user clears an explicit selection", async () => {
    renderAt("/?node=review", [node("review", "review")]);
    await waitFor(() => expect(ref.current!.selectedKey).toBe("review"));

    act(() => ref.current!.select(null));

    await waitFor(() => expect(ref.current!.selectedKey).toBeNull());
    expect(ref.current!.search).toBe("");
  });

  it("re-arms auto-select when the run scope changes", async () => {
    const view = renderAt("/", [node("review-a", "review")], "run-a");
    await waitFor(() => expect(ref.current!.selectedKey).toBe("review-a"));

    act(() => ref.current!.select(null));
    await waitFor(() => expect(ref.current!.selectedKey).toBeNull());

    view.rerender(
      <MemoryRouter initialEntries={["/"]}>
        {routeElement([node("review-b", "review")], "run-b")}
      </MemoryRouter>,
    );

    await waitFor(() => expect(ref.current!.selectedKey).toBe("review-b"));
    expect(new URLSearchParams(ref.current!.search).get("node")).toBe("review-b");
  });
});
