import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentUsagePanel } from "./AgentUsagePanel";
import type { AgentEvent } from "./agentTypes";
import tape from "../../../../tests/fixtures/agent_usage/development_frames.json";

const event = (usage: unknown, seq: number): AgentEvent => ({
  schema_version: "agent.event.v1", event_id: `usage-${seq}`, session_id: "s", seq,
  event_type: "provider_step", created_at: "2026-10-21T00:00:00Z", command_id: "c",
  payload: { usage, usage_state: usage === null ? "unavailable" : "reported", provider_step: seq,
    request_id: `r-${seq}`, provider_request_id: `upstream-${seq}`, retries: 0, elapsed_s: 1, outcome: "stop" },
});

describe("raw usage to visible values", () => {
  it("matches recorded counts without adding reasoning twice", () => {
    render(<AgentUsagePanel events={tape.records.map((r,i)=>event(r.usage,i+1))} />);
    const panel = screen.getByTestId("agent-usage");
    expect(panel).toHaveTextContent(`${tape.records.reduce((s,r)=>s+r.usage.prompt_tokens,0)} input`);
    expect(panel).toHaveTextContent(`${tape.records.reduce((s,r)=>s+r.usage.completion_tokens,0)} output`);
    const rows = within(panel).getAllByRole("row").slice(1);
    tape.records.forEach((record, i) => {
      const cells = within(rows[i]).getAllByRole("cell"), u = record.usage;
      [u.prompt_tokens,u.completion_tokens,u.total_tokens,u.prompt_cache_hit_tokens,u.prompt_cache_miss_tokens,u.completion_tokens_details.reasoning_tokens].forEach((v,j)=>expect(cells[4+j]).toHaveTextContent(String(v)));
    });
    expect(panel).toHaveTextContent("included in output");
    expect(within(panel).getAllByText("Raw usage")).toHaveLength(3);
    expect(panel).toHaveTextContent('"total_tokens": 30217');
  });
  it("keeps inconsistent fields unknown while preserving raw evidence", () => {
    render(<AgentUsagePanel events={[event({prompt_tokens:10,completion_tokens:3,total_tokens:99,prompt_cache_hit_tokens:11,prompt_cache_miss_tokens:5,completion_tokens_details:{reasoning_tokens:4}},1),event(null,2)]} />);
    const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
    for (const i of [6,7,8,9]) expect(cells[i]).toHaveTextContent("Unknown");
    expect(screen.getByTestId("agent-usage")).toHaveTextContent('"total_tokens": 99');
    expect(screen.getByTestId("agent-usage")).toHaveTextContent("reported subtotal");
  });
});
