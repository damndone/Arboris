import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AiActivityPanel } from "./AiActivityPanel";
import { appendAiActivity, makeActivityId } from "../../aiActivity/aiActivityLog";
import { AgentNavigationContext } from "../agent/agentNavigation";

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
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ activities: [] }),
    }));
  });

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

  it("refreshes live when a record is appended elsewhere in the window", async () => {
    render(<AiActivityPanel runId="r1" projectRoot={ROOT} />);
    expect(screen.getByTestId("ai-activity-empty")).toBeInTheDocument();
    act(() => seedAsk("late question"));
    await waitFor(() => {
      expect(screen.getByTestId("ai-activity-ask")).toHaveTextContent("late question");
    });
  });

  it("does not leak records across projects", () => {
    seedAsk("mine");
    render(<AiActivityPanel runId="r1" projectRoot="/proj/other" />);
    expect(screen.getByTestId("ai-activity-empty")).toBeInTheDocument();
  });

  it("projects durable operation status, Main/Chain path, diff, and typed links", async () => {
    const openNavigation = vi.fn(() => true);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        activities: [{
          kind: "operation",
          activity_id: "oprec-1",
          at: "2026-07-15T09:00:00Z",
          main: {
            kind: "agent_session",
            id: "main-session",
            label: "Agent main-session",
            relation: "parent",
            available: true,
            href: { view: "agent", session_id: "main-session" },
          },
          chain: {
            kind: "chain",
            id: "chain-a",
            label: "Chain chain-a",
            relation: "parent",
            available: true,
            href: { view: "agent", chain_id: "chain-a", session_id: "chain-session" },
          },
          operation: {
            kind: "operation",
            id: "oprec-1",
            label: "model.rerun · completed",
            relation: "audit",
            available: true,
            href: { view: "agent", session_id: "chain-session", operation_record_id: "oprec-1" },
          },
          diff: {
            kind: "diff",
            id: "oprec-1",
            label: "Diff · input_diff.v1",
            relation: "result",
            available: true,
            href: {
              view: "agent",
              session_id: "chain-session",
              operation_record_id: "oprec-1",
              diff: "1",
            },
          },
          status: "completed",
          links: [{
            kind: "run",
            id: "run-child",
            label: "Child run run-child",
            relation: "child",
            available: true,
            href: { view: "graph", run_id: "run-child" },
          }],
          diff_ref: { kind: "input_diff.v1", changed_fields: ["covariance"] },
          verification: { passed: true, checks: { child_terminal_status: true } },
          effect_status: "committed",
          projection_status: "complete",
        }],
        hierarchy: {
          ref: {
            kind: "agent_session",
            id: "main-session",
            label: "Agent main-session",
            relation: "context",
            available: true,
            href: { view: "agent", session_id: "main-session" },
          },
          status: "idle",
          children: [{
            ref: {
              kind: "chain",
              id: "chain-a",
              label: "Chain chain-a",
              relation: "child",
              available: true,
              href: { view: "agent", chain_id: "chain-a" },
            },
            status: "active",
            children: [{
              ref: {
                kind: "operation",
                id: "oprec-1",
                label: "model.rerun · completed",
                relation: "audit",
                available: true,
                href: {
                  view: "agent",
                  session_id: "chain-session",
                  operation_record_id: "oprec-1",
                },
              },
              status: "completed",
              children: [{
                ref: {
                  kind: "diff",
                  id: "oprec-1",
                  label: "Diff · input_diff.v1",
                  relation: "result",
                  available: true,
                  href: {
                    view: "agent",
                    session_id: "chain-session",
                    operation_record_id: "oprec-1",
                    diff: "1",
                  },
                },
                status: "available",
                children: [],
              }],
            }],
          }],
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AgentNavigationContext.Provider value={openNavigation}>
        <AiActivityPanel runId="r1" projectRoot={ROOT} />
      </AgentNavigationContext.Provider>,
    );

    const row = await screen.findByTestId("ai-activity-operation");
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/agent/activity?project_root=%2Fproj%2Fdemo",
    );
    expect(row).toHaveTextContent("Main · Agent main-session");
    expect(row).toHaveTextContent("Chain chain-a");
    expect(row).toHaveTextContent("model.rerun · completed");
    expect(row).toHaveTextContent("effect committed");
    expect(row).toHaveTextContent("projection complete");
    expect(row).toHaveTextContent("verified");
    expect(row).toHaveTextContent("covariance");
    expect(screen.getByTestId("ai-activity-hierarchy")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Open Diff · input_diff.v1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Child run run-child" }));
    expect(openNavigation).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "run", id: "run-child" }),
    );
    fireEvent.click(within(row).getByRole("button", { name: "Open Diff · input_diff.v1" }));
    expect(openNavigation).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "diff", id: "oprec-1" }),
    );
  });

  it("renders granular durable Agent events with typed operation links", async () => {
    const openNavigation = vi.fn(() => true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        activities: [],
        hierarchy: null,
        events: [{
          kind: "event",
          activity_id: "event-7",
          at: "2026-07-15T09:00:00Z",
          seq: 7,
          event_type: "operation_completed",
          session: {
            kind: "agent_session",
            id: "chain-session",
            label: "Agent chain-session",
            relation: "context",
            available: true,
            href: { view: "agent", session_id: "chain-session" },
          },
          main: {
            kind: "agent_session",
            id: "main-session",
            label: "Agent main-session",
            relation: "parent",
            available: true,
            href: { view: "agent", session_id: "main-session" },
          },
          chain: {
            kind: "chain",
            id: "chain-a",
            label: "Chain chain-a",
            relation: "parent",
            available: true,
            href: { view: "agent", chain_id: "chain-a", session_id: "chain-session" },
          },
          command_id: "command-1",
          details: { record_id: "oprec-1", status: "completed" },
          links: [{
            kind: "operation",
            id: "oprec-1",
            label: "model.rerun · completed",
            relation: "audit",
            available: true,
            href: { view: "agent", session_id: "chain-session", operation_record_id: "oprec-1" },
          }],
        }],
      }),
    }));

    render(
      <AgentNavigationContext.Provider value={openNavigation}>
        <AiActivityPanel runId="r1" projectRoot={ROOT} />
      </AgentNavigationContext.Provider>,
    );

    const row = await screen.findByTestId("ai-activity-event");
    expect(row).toHaveTextContent("#7");
    expect(row).toHaveTextContent("operation_completed");
    const link = within(row).getByRole("button", {
      name: "Open model.rerun · completed",
    });
    fireEvent.click(link);
    expect(openNavigation).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "operation", id: "oprec-1" }),
    );
  });
});
