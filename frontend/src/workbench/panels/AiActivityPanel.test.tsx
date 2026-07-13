import { beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { AiActivityPanel } from "./AiActivityPanel";
import { appendAiActivity, makeActivityId } from "../../aiActivity/aiActivityLog";

const ROOT = "/proj/demo";

function seedAsk(question: string) {
  appendAiActivity(ROOT, {
    kind: "ask_ai",
    id: makeActivityId(),
    at: "2026-07-12T08:00:00Z",
    node_key: "nk1",
    node_label: "OLS (primary)",
    question,
    status: "answered",
    model: "deepseek-v4-flash",
    answer: "## Answer\n**ok**",
  });
}

describe("AiActivityPanel", () => {
  beforeEach(() => window.localStorage.clear());

  it("shows a persistent empty state when there is no activity", () => {
    render(<AiActivityPanel runId="r1" projectRoot={ROOT} />);
    expect(screen.getByTestId("ai-activity-empty")).toHaveTextContent(
      "No AI activity yet",
    );
  });

  it("lists ask_ai and report_generate records, newest first", () => {
    seedAsk("first question");
    appendAiActivity(ROOT, {
      kind: "report_generate",
      id: makeActivityId(),
      at: "2026-07-12T08:05:00Z",
      run_id: "run_1",
      instruction: "write the report",
      model: "deepseek-v4-flash",
      fact_count: 15,
      excluded_count: 2,
      report_record_id: "rpt_1",
    });
    render(<AiActivityPanel runId="r1" projectRoot={ROOT} />);
    const rows = screen.getAllByTestId(/ai-activity-(ask|report)/);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("write the report");
    expect(rows[0]).toHaveTextContent("2 excluded");
    expect(rows[1]).toHaveTextContent("first question");
  });

  it("refreshes live when a record is appended elsewhere in the window", () => {
    render(<AiActivityPanel runId="r1" projectRoot={ROOT} />);
    expect(screen.getByTestId("ai-activity-empty")).toBeInTheDocument();
    act(() => seedAsk("late question"));
    expect(screen.getByTestId("ai-activity-ask")).toHaveTextContent("late question");
  });

  it("does not leak records across projects", () => {
    seedAsk("mine");
    render(<AiActivityPanel runId="r1" projectRoot="/proj/other" />);
    expect(screen.getByTestId("ai-activity-empty")).toBeInTheDocument();
  });
});
