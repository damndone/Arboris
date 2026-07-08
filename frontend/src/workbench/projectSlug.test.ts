import { describe, expect, it } from "vitest";
import { rootToSlug, slugToRoot } from "./projectSlug";

describe("projectSlug", () => {
  it.each([
    "/Users/me/work/demo",
    "/Users/jiayuanren/项目规划/示例项目",
    "/tmp/with space/and-dash_underscore",
  ])("roundtrips %s", (root) => {
    expect(slugToRoot(rootToSlug(root))).toBe(root);
  });

  it("produces URL-path-safe slugs (no / + = %)", () => {
    const slug = rootToSlug("/Users/jiayuanren/项目规划/p1");
    expect(slug).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("slugToRoot throws on malformed input (never garbage)", () => {
    expect(() => slugToRoot("!!!not-base64!!!")).toThrow();
  });
});
