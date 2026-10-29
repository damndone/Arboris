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
  const label = calls.length === 1 ? "Executing tool" : `Executing ${calls.length} tools`;
  return `${label} · ${calls.map(call => call.tool_id.replace(/[_\s]+/g, " ").trim()).join(", ")}`;
}
