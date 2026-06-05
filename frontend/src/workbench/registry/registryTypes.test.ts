// frontend/src/workbench/registry/registryTypes.test.ts
//
// V1.5.2 — locks the contract shared by section / action / bottom-panel
// registries. If any of these change, downstream registry consumers
// (DetailDrawer, right-click menu, BottomPanel) need to be updated too.

import { describe, expect, it } from "vitest";
import {
  filterAndSort,
  sortByOrder,
  type RegistryEntry,
} from "./registryTypes";

interface Ctx {
  flag: boolean;
}

function entry(
  id: string,
  order: number,
  shouldRender: (c: Ctx) => boolean = () => true,
): RegistryEntry<Ctx> {
  return { id, order, shouldRender };
}

describe("registryTypes", () => {
  describe("sortByOrder", () => {
    it("returns ascending order without mutating input", () => {
      const input = [entry("b", 20), entry("a", 10), entry("c", 30)];
      const out = sortByOrder(input);
      expect(out.map((e) => e.id)).toEqual(["a", "b", "c"]);
      // Original order preserved.
      expect(input.map((e) => e.id)).toEqual(["b", "a", "c"]);
    });

    it("is stable for equal orders", () => {
      // We don't guarantee total ordering for ties — only that ties
      // don't crash. JS sort is stable since ES2019 so insertion
      // order is preserved.
      const out = sortByOrder([entry("a", 10), entry("b", 10)]);
      expect(out.map((e) => e.id)).toEqual(["a", "b"]);
    });
  });

  describe("filterAndSort", () => {
    it("applies shouldRender then sorts by order", () => {
      const entries = [
        entry("a", 30, () => true),
        entry("b", 10, (c) => c.flag),
        entry("c", 20, () => true),
      ];
      const out = filterAndSort(entries, { flag: false });
      expect(out.map((e) => e.id)).toEqual(["c", "a"]);
    });

    it("returns [] when all entries are filtered out", () => {
      const entries = [entry("a", 10, () => false)];
      expect(filterAndSort(entries, { flag: false })).toEqual([]);
    });
  });
});
