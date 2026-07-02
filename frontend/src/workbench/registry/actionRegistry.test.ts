// frontend/src/workbench/registry/actionRegistry.test.ts
//
// V1.5.2 P4 — actionRegistry contract + dispatch shape tests.

import { describe, expect, it, vi } from "vitest";
import {
  actionRegistry,
  actionsForSurface,
  actionForShortcut,
  matchesKeys,
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
  it("registers the 12 V1.5.2 actions (P4 + P7 topbar additions)", () => {
    expect(actionRegistry.map((a) => a.id).sort()).toEqual(
      [
        "askAiAboutNode",
        "copyAsJson",
        "copyLineagePath",
        "copyNodeId",
        "focusUpstream",
        "generateReport",
        "markNeedsReview",
        "openDetail",
        "pinTab",
        "pinUpstream",
        "rerun",
        "rerunFromNode",
      ].sort(),
    );
  });

  it("topbar surface yields rerun (live in v1.6.6) + generateReport (disabled)", () => {
    const topbarIds = actionsForSurface("topbar", ctx()).map((a) => a.id);
    expect(topbarIds).toEqual(["rerun", "generateReport"]);
    // v1.6.6 ③: topbar Rerun is now live (routes to the node rerun flow).
    const rerun = actionRegistry.find((a) => a.id === "rerun")!;
    expect(rerun.disabled).toBeUndefined();
    // Generate report stays disabled (AI-written report — v1.6.8).
    const gen = actionRegistry.find((a) => a.id === "generateReport")!;
    expect(gen.disabled?.(ctx())).toMatchObject({ reason: expect.any(String) });
  });

  it("no disabled reason references a stale/already-shipped version (honesty)", () => {
    // v1.6.6 ③: dead-button reasons must point at real roadmap targets,
    // not the long-shipped "V1.5.3" / "V2.0" placeholders.
    for (const a of actionRegistry) {
      const out = a.disabled?.(ctx());
      if (out) {
        expect(out.reason).not.toMatch(/V1\.5\.3|V2\.0/);
      }
    }
  });

  it("orders are unique (no slot collisions)", () => {
    const orders = actionRegistry.map((a) => a.order);
    expect(new Set(orders).size).toBe(orders.length);
  });

  it("disabled placeholders return a reason", () => {
    // v1.6.1 (2C.3): rerunFromNode is now live (forks a sibling run).
    const disabled = ["askAiAboutNode", "markNeedsReview"];
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
      "rerunFromNode",
      "rerun", // v1.6.6 ③: topbar Rerun wired to the node rerun flow
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

  it("topbar rerun opens the node detail (→ OperationSection → POST /runs/<id>/rerun)", () => {
    const d = fakeDispatch();
    const c = ctx({ dispatch: d });
    actionRegistry.find((a) => a.id === "rerun")!.invoke(c);
    expect(d.openDetail).toHaveBeenCalledWith("n1");
  });
});

describe("F6 — shortcut matching", () => {
  const ev = (o: Partial<KeyboardEvent>) => ({
    key: "c",
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    ...o,
  });

  it("matchesKeys: ⌘⇧C fires on meta+shift+c (and ctrl+shift+c)", () => {
    const keys = { key: "c", meta: true, shift: true };
    expect(matchesKeys(keys, ev({ metaKey: true, shiftKey: true }))).toBe(true);
    expect(matchesKeys(keys, ev({ ctrlKey: true, shiftKey: true }))).toBe(true);
  });

  it("matchesKeys: does NOT fire on plain ⌘C (missing shift)", () => {
    const keys = { key: "c", meta: true, shift: true };
    expect(matchesKeys(keys, ev({ metaKey: true }))).toBe(false);
  });

  it("matchesKeys: does NOT fire when an extra modifier is held", () => {
    const keys = { key: "c", meta: true, shift: true };
    expect(
      matchesKeys(keys, ev({ metaKey: true, shiftKey: true, altKey: true })),
    ).toBe(false);
  });

  it("matchesKeys: key compare is case-insensitive", () => {
    const keys = { key: "c", meta: true, shift: true };
    expect(matchesKeys(keys, ev({ key: "C", metaKey: true, shiftKey: true }))).toBe(
      true,
    );
  });

  it("actionForShortcut: ⌘⇧C resolves to copyNodeId", () => {
    const a = actionForShortcut(
      ev({ metaKey: true, shiftKey: true }),
      ctx(),
    );
    expect(a?.id).toBe("copyNodeId");
  });

  it("actionForShortcut: unbound combo resolves to null", () => {
    const a = actionForShortcut(ev({ key: "x", metaKey: true }), ctx());
    expect(a).toBeNull();
  });

  it("copyNodeId declares the shortcut surface + structured keys", () => {
    const a = actionRegistry.find((x) => x.id === "copyNodeId")!;
    expect(a.surfaces).toContain("shortcut");
    expect(a.keys).toEqual({ key: "c", meta: true, shift: true });
  });
});
