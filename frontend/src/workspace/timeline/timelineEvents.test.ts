import { describe, expect, test } from "vitest";
import { describeEvent, describeWho, summarizeTimeline } from "./timelineEvents";

const entry = (what: string, summary = "", who = "User", status = "completed") =>
  ({ at: "2026-10-13T01:00:00Z", who, what, status, summary, categories: [] }) as never;

describe("timeline events in reader terms", () => {
  test("runs, reruns with their changes, tests and exports read as sentences", () => {
    expect(describeEvent(entry("run.submit", "draft=draft_0487"))).toBe("Ran a new analysis");
    expect(describeEvent(entry("run.rerun", JSON.stringify({ changes: [{ field_id: "covariance", old_value: "robust", new_value: "unadjusted" }] })))).toBe(
      "Reran with changes: covariance robust → unadjusted",
    );
    expect(describeEvent(entry("run.rerun", "{\"changes\": [trunc"))).toBe("Reran with changes");
    expect(describeEvent(entry("postestimation.wald"))).toBe("Wald test");
    expect(describeEvent(entry("export.analysis_script", "Local stata script export"))).toBe("Exported a Stata script");
    expect(describeEvent(entry("data.recode", "Recoded age into 3 groups"))).toBe("Recoded age into 3 groups");
    expect(describeEvent(entry("survival.kaplan_meier"))).toBe("Survival: kaplan meier");
    expect(describeEvent({ ...(entry("test.correlations") as object), title: "Pearson correlations" } as never)).toBe("Pearson correlations");
  });

  test("who acted: you or the Agent", () => {
    expect(describeWho("User")).toBe("You");
    expect(describeWho("ui")).toBe("You");
    expect(describeWho("Agent (read-only, no confirmation)")).toBe("Agent");
  });

  test("the bottom-bar line counts with proper plurals and skips zeros", () => {
    const value = { entries: [entry("postestimation.wald")], counts: { models: 2, inferential_tests: 1, data_changes: 0 }, entries_omitted: 0 } as never;
    expect(summarizeTimeline(value)).toBe("Last: Wald test · 2 models · 1 test");
    expect(summarizeTimeline(null)).toBe("Analysis history");
  });
});
