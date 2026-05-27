// frontend/src/workbench/registry/actionRegistry.test.ts
//
// V1.5.2 P4 — actionRegistry contract + dispatch shape tests.

import { describe, expect, it, vi } from "vitest";
import {
  actionRegistry,
  actionsForSurface,
  type ActionContext,
  type ActionDispatch,
} from "./actionRegistry";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../../lineage/api/graphViewTypes";

function node(): GraphViewNode {
  return {
    id: "n1",
    nodeKey: "n1",
    raw: { hello: "world" },
    stage: "model",
    kind: "model",
    title: "Primary",
    parentStageId: null,
    trust: "ok",
    decisions: [],
  };
}

function model(): GraphViewModel {
  return {
    schemaVersion: 3,
    runId: "r1",
    legacy: false,
    nodes: [node()],
    edges: [],
    stats: { nodeCount: 1, edgeCount: 0, leafCount: 1, hasDpCount: 0 },
  };
}

function fakeDispatch(): ActionDispatch {
  return {
    openDetail: vi.fn(),
    pinTab: vi.fn(),
    pinUpstream: vi.fn(),
    focusUpstream: vi.fn(),
  };
}

function ctx(overrides: Partial<ActionContext> = {}): ActionContext {
  return {
    node: node(),
    model: model(),
    selectedKey: null,
    focusKey: null,
    pinned: false,
    dispatch: fakeDispatch(),
    ...overrides,
  };
}

describe("actionRegistry", () => {
  it("registers the 10 V1.5.2 actions", () => {
    expect(actionRegistry.map((a) => a.id).sort()).toEqual(
      [
        "askAiAboutNode",
        "copyAsJson",
        "copyLineagePath",
        "copyNodeId",
        "focusUpstream",
        "markNeedsReview",
        "openDetail",
        "pinTab",
        "pinUpstream",
        "rerunFromNode",
      ].sort(),
    );
  });

  it("orders are unique (no slot collisions)", () => {
    const orders = actionRegistry.map((a) => a.order);
    expect(new Set(orders).size).toBe(orders.length);
  });

  it("disabled placeholders return a reason", () => {
    const disabled = ["askAiAboutNode", "rerunFromNode", "markNeedsReview"];
    for (const id of disabled) {
      const a = actionRegistry.find((x) => x.id === id)!;
      const out = a.disabled?.(ctx());
      expect(out).toMatchObject({ reason: expect.any(String) });
    }
  });

  it("live actions have no disabled() function", () => {
    const live = [
      "openDetail",
      "pinTab",
      "copyNodeId",
      "copyAsJson",
      "copyLineagePath",
      "focusUpstream",
      "pinUpstream",
    ];
    for (const id of live) {
      const a = actionRegistry.find((x) => x.id === id)!;
      expect(a.disabled).toBeUndefined();
    }
  });
});

describe("actionsForSurface", () => {
  it("graph-context-menu yields the canvas-relevant action set", () => {
    const ids = actionsForSurface("graph-context-menu", ctx()).map(
      (a) => a.id,
    );
    expect(ids).toEqual([
      "openDetail",
      "pinTab",
      "copyNodeId",
      "copyAsJson",
      "copyLineagePath",
      "focusUpstream",
      "pinUpstream",
      "askAiAboutNode",
      "rerunFromNode",
    ]);
  });

  it("drawer-header-menu excludes canvas-only actions (openDetail/focusUpstream/pinUpstream)", () => {
    const ids = actionsForSurface("drawer-header-menu", ctx()).map(
      (a) => a.id,
    );
    expect(ids).not.toContain("openDetail");
    expect(ids).not.toContain("focusUpstream");
    expect(ids).not.toContain("pinUpstream");
    expect(ids).toContain("copyNodeId");
    expect(ids).toContain("markNeedsReview");
  });

  it("orders results ascending", () => {
    const orders = actionsForSurface("graph-context-menu", ctx()).map(
      (a) => a.order,
    );
    const sorted = [...orders].sort((a, b) => a - b);
    expect(orders).toEqual(sorted);
  });
});

describe("invoke handlers", () => {
  it("openDetail / pinTab call dispatch.openDetail / pinTab with nodeKey", () => {
    const d = fakeDispatch();
    const c = ctx({ dispatch: d });
    actionRegistry.find((a) => a.id === "openDetail")!.invoke(c);
    actionRegistry.find((a) => a.id === "pinTab")!.invoke(c);
    expect(d.openDetail).toHaveBeenCalledWith("n1");
    expect(d.pinTab).toHaveBeenCalledWith("n1");
  });

  it("pinUpstream / focusUpstream call the matching dispatch methods", () => {
    const d = fakeDispatch();
    const c = ctx({ dispatch: d });
    actionRegistry.find((a) => a.id === "pinUpstream")!.invoke(c);
    actionRegistry.find((a) => a.id === "focusUpstream")!.invoke(c);
    expect(d.pinUpstream).toHaveBeenCalledWith("n1");
    expect(d.focusUpstream).toHaveBeenCalledWith("n1");
  });
});
