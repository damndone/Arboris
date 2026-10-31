import type { AgentEvent } from "./agentTypes";

/** Public invocation identity only; tool arguments and reasoning do not belong here. */
export type ActiveToolCall = {
  session_id: string;
  command_id: string | null;
  tool_call_id: string;
  tool_id: string;
};

/**
 * Follow invocation identity rather than the last event's type. Design reference:
 * OpenAI Codex (Apache-2.0, Copyright 2025 OpenAI), commit
 * 2681f8cba2831ef72bca2c0672b2e49d5f690745,
 * codex-rs/tui/src/exec_cell/model.rs:142 and chatwidget/command_lifecycle.rs:361.
 */
export function updateActiveToolCalls(current: ActiveToolCall[], events: AgentEvent[]): ActiveToolCall[] {
  let calls = current;
  for (const event of events) {
    const commandId = event.command_id ?? null;
    const sameCommand = (call: ActiveToolCall) => call.session_id === event.session_id && call.command_id === commandId;
    if (event.event_type === "turn_start") {
      calls = calls.filter(sameCommand);
      continue;
    }
    if (["turn_end", "agent_end", "error", "aborted"].includes(event.event_type)) {
      calls = calls.filter(call => !sameCommand(call));
      continue;
    }
    if (event.event_type !== "tool_execution_start" && event.event_type !== "tool_execution_end") continue;
    const callId = event.payload.tool_call_id;
    if (typeof callId !== "string" || !callId.trim()) continue;
    const sameCall = (call: ActiveToolCall) => sameCommand(call) && call.tool_call_id === callId;
    if (event.event_type === "tool_execution_end") {
      calls = calls.filter(call => !sameCall(call));
      continue;
    }
    const toolId = event.payload.tool_id;
    if (typeof toolId !== "string" || !toolId.trim() || calls.some(sameCall)) continue;
    calls = [...calls, { session_id: event.session_id, command_id: commandId, tool_call_id: callId, tool_id: toolId }];
  }
  return calls;
}

export function activeToolActivityLabel(calls: ActiveToolCall[] = []): string | null {
  if (!calls.length) return null;
  return calls.map(call => toolTitle(call.tool_id)).join(" · ");
}

/** What a step did, in the reader's words. Unlisted tools read from their id, so a new tool needs no entry here. */
const TOOL_TITLES: Record<string, string> = {
  update_plan: "Updated the plan",
  run_operation: "Ran an operation",
  plan_analysis: "Compared analysis plans",
  calculate: "Calculated",
  list_project_datasets: "Listed datasets",
  inspect_analysis_completion: "Checked what is still missing",
  inspect_operation_contract: "Read an operation's fields",
  inspect_operation_artifact: "Read a result",
  inspect_result_summary: "Read the result summary",
  inspect_project_model_coefficients: "Read model coefficients",
  inspect_completed_operations: "Listed completed operations",
  check_model_claims: "Checked a claim against the model",
  show_dataset_rows: "Showed dataset rows",
  export_analysis_script: "Exported the analysis script",
};

export function toolTitle(toolId: string): string {
  if (TOOL_TITLES[toolId]) return TOOL_TITLES[toolId];
  const words = toolId.replace(/^inspect_(project_)?/, "").replace(/[_\s]+/g, " ").trim();
  return toolId.startsWith("inspect_") ? `Read ${words}` : words.charAt(0).toUpperCase() + words.slice(1);
}

export type ToolStep = { title: string; state: "done" | "failed" | "waiting"; detail: string };

/** One readable step from the receipt's status line; an unparsed line stays visible as the detail. */
export function toolStep(statusLine: string): ToolStep {
  const match = /^(\S+) (✓|✗) ?([\s\S]*)$/.exec(statusLine);
  if (!match) return { title: "Step", state: "done", detail: statusLine };
  const [, toolId, mark, rest] = match;
  const title = toolTitle(toolId);
  if (mark === "✗") return { title, state: "failed", detail: rest.replace(/^(\w*Error|failed) — /, "") };
  if (rest.startsWith("proposal ready")) return { title, state: "waiting", detail: "Waiting for your confirmation" };
  const detail = rest === "ok" ? "" : rest.replace(/^read-only analysis ran without confirmation \(recorded\)( · )?/, "");
  return { title, state: "done", detail };
}

export function observableActivity(eventType: string | null): string {
  if (!eventType) return "Starting";
  const normalized = eventType.toLowerCase();
  if (normalized === "provider_retry") return "The provider connection dropped; retrying";
  if (normalized === "compaction_start") return "Summarizing the earlier conversation to stay within the model's context";
  if (normalized.includes("tool")) return "Working";
  if (normalized.includes("proposal")) return "Preparing a proposal";
  if (normalized === "message_start") return "Waiting for the model";
  if (normalized === "message_update") return "Writing";
  return "Working";
}
