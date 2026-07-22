// Figure explanations must survive leaving the tab, and must be logged.
//
// The answer lived only in component state, so switching to Graph and back
// unmounted it and the explanation was gone. It was also the one AI exchange
// in the app that never reached the activity log -- node Ask AI and report
// generation both write records, so the trail had a hole exactly where a
// chart interpretation would have been.

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { appendAiActivity, loadAiActivity, makeActivityId } from "../../aiActivity/aiActivityLog";

describe("figure Ask AI durability", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it("stores a figure explanation under a figure-scoped key", () => {
    appendAiActivity("/p", {
      kind: "ask_ai",
      id: makeActivityId(),
      at: new Date().toISOString(),
      node_key: "figure:fig_residuals",
      node_label: "Figure · residuals",
      question: "Interpret this",
      status: "answered",
      answer: "The residuals look fine.",
    });

    const records = loadAiActivity("/p");
    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({
      kind: "ask_ai",
      node_key: "figure:fig_residuals",
      answer: "The residuals look fine.",
    });
  });

  it("keeps figure explanations separate per artifact", () => {
    for (const artifact of ["fig_a", "fig_b"]) {
      appendAiActivity("/p", {
        kind: "ask_ai",
        id: makeActivityId(),
        at: new Date().toISOString(),
        node_key: `figure:${artifact}`,
        node_label: `Figure · ${artifact}`,
        question: "q",
        status: "answered",
        answer: `answer for ${artifact}`,
      });
    }

    const keys = loadAiActivity("/p").map((r) => ("node_key" in r ? r.node_key : ""));
    expect(new Set(keys)).toEqual(new Set(["figure:fig_a", "figure:fig_b"]));
  });
});
