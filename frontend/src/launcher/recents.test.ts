import { describe, expect, it, beforeEach } from "vitest";
import { listRecents, touchRecent, removeRecent } from "./recents";

describe("recents", () => {
  beforeEach(() => localStorage.clear());
  it("touch puts most-recent first and dedupes", () => {
    touchRecent("/a");
    touchRecent("/b");
    touchRecent("/a");
    expect(listRecents().map((r) => r.root)).toEqual(["/a", "/b"]);
  });
  it("stores unicode roots verbatim", () => {
    touchRecent("/Users/me/项目规划/示例");
    expect(listRecents()[0].root).toBe("/Users/me/项目规划/示例");
  });
  it("removeRecent drops stale entries", () => {
    touchRecent("/a");
    removeRecent("/a");
    expect(listRecents()).toEqual([]);
  });
  it("caps the list at 12", () => {
    for (let i = 0; i < 15; i++) touchRecent(`/p${i}`);
    expect(listRecents()).toHaveLength(12);
  });
  it("survives corrupt localStorage", () => {
    localStorage.setItem("workbench.recentProjects.v1", "{not json");
    expect(listRecents()).toEqual([]);
  });
});
