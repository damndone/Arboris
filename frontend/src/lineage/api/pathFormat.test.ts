import { describe, expect, it } from "vitest";
import { formatUpstreamPath, groupByDepth, separatorAfter } from "./pathFormat";

const path = [
  { label: "Raw input data", depth: 0 },
  { label: "Cleaned data", depth: 1 },
  { label: "wage (cleaned)", depth: 2 },
  { label: "education (cleaned)", depth: 2 },
  { label: "exper (cleaned)", depth: 2 },
  { label: "ols_robust (primary)", depth: 3 },
];

describe("formatUpstreamPath", () => {
  it("groups parallel same-depth nodes with + instead of a fake → chain", () => {
    // 用户反馈 2026-07-12: wage/education/exper 是平行分支不是递进关系。
    expect(formatUpstreamPath(path)).toBe(
      "Raw input data → Cleaned data → (wage (cleaned) + education (cleaned) + exper (cleaned)) → ols_robust (primary)",
    );
  });

  it("degrades to the plain arrow chain when depth is absent (legacy)", () => {
    expect(
      formatUpstreamPath([{ label: "a" }, { label: "b" }, { label: "c" }]),
    ).toBe("a → b → c");
  });
});

describe("groupByDepth", () => {
  it("only groups CONSECUTIVE same-depth items", () => {
    const groups = groupByDepth(path);
    expect(groups.map((g) => g.length)).toEqual([1, 1, 3, 1]);
  });
});

describe("separatorAfter", () => {
  it("+ between siblings, → across depth steps, → when depth unknown", () => {
    expect(separatorAfter(path, 1)).toBe("→"); // cleaned → wage
    expect(separatorAfter(path, 2)).toBe("+"); // wage + education
    expect(separatorAfter(path, 4)).toBe("→"); // exper → model
    expect(separatorAfter([{}, {}], 0)).toBe("→");
  });
});
