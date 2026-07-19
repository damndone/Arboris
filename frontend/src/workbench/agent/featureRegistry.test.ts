import { describe, expect, it } from "vitest";
import { createElement } from "react";
import {
  registerFeatureView,
  resolveFeatureView,
} from "./featureRegistry";
import { registerBuiltinFeatureViews } from "./builtinFeatureViews";

describe("resolveFeatureView", () => {
  it("returns null for an undeclared packet contract", () => {
    expect(resolveFeatureView("unknown.contract@1.0")).toBeNull();
  });

  it("resolves a registered view and rejects a duplicate contract key", () => {
    const view = {
      contractKey: "test.feature-registry@1.0",
      render: () => createElement("div"),
    };

    registerFeatureView(view);

    expect(resolveFeatureView(view.contractKey)).toBe(view);
    expect(() => registerFeatureView(view)).toThrow(
      "duplicate agent feature view: test.feature-registry@1.0",
    );
  });

  it("allows the empty builtin bootstrap to run more than once", () => {
    expect(() => registerBuiltinFeatureViews()).not.toThrow();
    expect(() => registerBuiltinFeatureViews()).not.toThrow();
  });
});
