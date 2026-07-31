import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ContextSlicePanel } from "./ContextSlicePanel";
import { provisionalContextSlice } from "./fixtures/provisionalContextSlice";

describe("ContextSlicePanel — what the agent actually saw", () => {
  it("keeps the full evidence and decision chain collapsed until requested", () => {
    render(<ContextSlicePanel slice={provisionalContextSlice()} />);

    const details = screen.getByTestId("context-evidence-details");
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByTestId("context-evidence-summary")).toHaveTextContent(
      "6 recorded events",
    );
  });

  it("names the compiled context and both hashes, kept separate", () => {
    render(<ContextSlicePanel slice={provisionalContextSlice()} />);

    expect(screen.getByTestId("context-slice-identity")).toHaveTextContent(
      "ctx_9c21ab · notebook-plan/v1",
    );
    expect(screen.getByTestId("context-slice-generation-hash")).toHaveTextContent(
      "generation_context_hash sha256:aaaaaaaa…",
    );
    expect(screen.getByTestId("context-slice-freshness-hash")).toHaveTextContent(
      "freshness_dependency_fingerprint fresh1:bbbbbbbb…",
    );
  });

  it("shows the artifact omission as 5 of 59, not 5 of 5", () => {
    render(<ContextSlicePanel slice={provisionalContextSlice()} />);

    const omission = screen.getByTestId("context-omission-artifact_summaries");
    expect(omission).toHaveTextContent("artifact_summaries: 5 of 59 included, 54 omitted");
    expect(omission).toHaveTextContent("section_budget_exceeded");
    expect(omission).toHaveTextContent("36 time_series_json omitted");
  });

  it("keeps the full artifact type counts even where detail was dropped", () => {
    render(<ContextSlicePanel slice={provisionalContextSlice()} />);
    const counts = screen.getByTestId("context-type-counts");
    expect(counts).toHaveTextContent("time_series_json 36");
    expect(counts).toHaveTextContent("model_result 1");
    expect(counts).toHaveTextContent("figure 12");
  });

  it("reports the byte budget per section rather than a bare 'context compiled'", () => {
    render(<ContextSlicePanel slice={provisionalContextSlice()} />);
    const budget = screen.getByTestId("context-budget-report");
    expect(budget).toHaveTextContent("artifact_summaries 1536 / 4096 bytes");
    expect(budget).toHaveTextContent("total 21480 / 24576 bytes");
    expect(screen.getByTestId("context-slice-panel")).not.toHaveTextContent("context compiled.");
  });

  it("lists the source objects with their revisions so the input can be checked by eye", () => {
    render(<ContextSlicePanel slice={provisionalContextSlice()} />);
    const manifest = screen.getByTestId("context-source-manifest");
    expect(manifest).toHaveTextContent("run:run-8ffc81c · rev 3 · active head");
    expect(manifest).toHaveTextContent(
      "analysis_contract:ac_0001 · rev 1 · analysis contract · never truncated",
    );
  });

  it("renders the trace decision chain in sequence order with real event types", () => {
    render(<ContextSlicePanel slice={provisionalContextSlice()} />);

    const rows = screen.getAllByTestId(/^trace-event-/);
    expect(rows.map((row) => row.getAttribute("data-event-type"))).toEqual([
      "context.compiled",
      "agent.plan.requested",
      "agent.plan.completed",
      "option.revision.created",
      "proposal.validation.completed",
      "user.decision.recorded",
    ]);
    expect(rows[0]).toHaveTextContent("#1 context.compiled");
    expect(rows[2]).toHaveTextContent("3 options generated, 1 rejected by validator");
    expect(rows[5]).toHaveTextContent("user.decision.recorded · deferred");
  });

  it("does not label the user's decision as a correct answer or reward", () => {
    render(<ContextSlicePanel slice={provisionalContextSlice()} />);
    const panel = screen.getByTestId("context-slice-panel");
    expect(panel).not.toHaveTextContent("reward");
    expect(panel).not.toHaveTextContent("correct answer");
  });
});
