import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DetailDrawerTabs } from "./DetailDrawerTabs";
import type { GraphViewNode } from "../api/graphViewTypes";
import {
  REPORT_REVIEW_TAB_ID,
  type TabState,
} from "../../workbench/state/tabsSchema";

function tab(id: string, openedAt = 1, nodeKey = id): TabState {
  return { kind: "node", id, nodeKey, openedAt };
}

function node(id: string, title: string, nodeKey = id): GraphViewNode {
  return {
    id,
    nodeKey,
    raw: null,
    stage: "model",
    kind: "model",
    title,
    parentStageId: null,
    trust: "ok",
    decisions: [],
  };
}

function renderTabs(
  props: Partial<React.ComponentProps<typeof DetailDrawerTabs>> = {},
) {
  const onActive = props.onActive ?? vi.fn();
  const onClose = props.onClose ?? vi.fn();
  const tabs = props.tabs ?? [tab("a"), tab("b")];
  const nodes = props.nodes ?? [node("a", "Alpha model"), node("b", "Beta model")];
  render(
    <DetailDrawerTabs
      tabs={tabs}
      nodes={nodes}
      activeTabId={props.activeTabId ?? tabs[0]?.id ?? null}
      onActive={onActive}
      onClose={onClose}
      lastEvictedTabId={props.lastEvictedTabId}
    />,
  );
  return { onActive, onClose };
}

describe("DetailDrawerTabs", () => {
  it("renders one tab per open node with short labels", () => {
    renderTabs({
      tabs: [tab("a"), tab("b"), tab("c")],
      nodes: [
        node("a", "Alpha model"),
        node("b", "Beta model"),
        node("c", "Diagnostics"),
      ],
      activeTabId: "b",
    });

    expect(screen.getByRole("tab", { name: "Alpha model" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Beta model" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Diagnostics" })).toBeInTheDocument();
    expect(screen.getByTestId("detail-drawer-tabs")).toHaveClass(
      "detail-tabs--versions",
    );
    expect(screen.getByRole("tablist")).toHaveClass(
      "detail-tabs__strip--compact",
    );
  });

  it("resolves labels by stable id when nodeKey differs", () => {
    renderTabs({
      tabs: [tab("uuid-a", 1, "logical:a")],
      nodes: [node("uuid-a", "Alpha model", "logical:a")],
      activeTabId: "uuid-a",
    });

    expect(screen.getByRole("tab", { name: "Alpha model" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("clicking a tab activates it", () => {
    const { onActive } = renderTabs({ activeTabId: "a" });

    fireEvent.click(screen.getByRole("tab", { name: "Beta model" }));

    expect(onActive).toHaveBeenCalledWith("b");
  });

  it("clicking a close button closes only that tab", () => {
    const { onActive, onClose } = renderTabs();

    fireEvent.click(screen.getByRole("button", { name: "Close Beta model tab" }));

    expect(onClose).toHaveBeenCalledWith("b");
    expect(onActive).not.toHaveBeenCalled();
  });

  it("renders Report review beside nodes without a close button", () => {
    const { onActive, onClose } = renderTabs({
      tabs: [
        tab("a"),
        { kind: "report-review", id: REPORT_REVIEW_TAB_ID, openedAt: 2 },
        tab("b", 3),
      ],
      activeTabId: REPORT_REVIEW_TAB_ID,
    });

    expect(
      screen.getByRole("tab", { name: "Report review" }),
    ).toHaveAttribute("aria-current", "true");
    expect(
      screen.queryByRole("button", { name: "Close Report review tab" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Report review" }));
    expect(onActive).toHaveBeenCalledWith(REPORT_REVIEW_TAB_ID);
    expect(onClose).not.toHaveBeenCalledWith(REPORT_REVIEW_TAB_ID);

    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(onActive).toHaveBeenCalledWith("b");
  });

  it("Left and Right arrows cycle active tabs when the strip has focus", () => {
    const { onActive } = renderTabs({
      tabs: [tab("a"), tab("b"), tab("c")],
      nodes: [
        node("a", "Alpha model"),
        node("b", "Beta model"),
        node("c", "Diagnostics"),
      ],
      activeTabId: "b",
    });
    const strip = screen.getByRole("tablist");

    fireEvent.keyDown(strip, { key: "ArrowRight" });
    fireEvent.keyDown(strip, { key: "ArrowLeft" });

    expect(onActive).toHaveBeenNthCalledWith(1, "c");
    expect(onActive).toHaveBeenNthCalledWith(2, "a");
  });

  it("shows an eviction notice after the 9th tab pushes out the oldest", () => {
    renderTabs({ lastEvictedTabId: "oldest" });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Oldest tab closed to keep 8 tabs.",
    );
  });
});
