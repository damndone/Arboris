import type { AgentEvent } from "./agentTypes";

/** Invocation identity and the one bounded line the step row shows; never raw arguments or reasoning. */
export type ActiveToolCall = {
  session_id: string;
  command_id: string | null;
  tool_call_id: string;
  tool_id: string;
  target?: string | null;
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
    const target = typeof event.payload.target === "string" ? { target: event.payload.target } : {};
    calls = [...calls, { session_id: event.session_id, command_id: commandId, tool_call_id: callId, tool_id: toolId, ...target }];
  }
  return calls;
}

export function activeToolActivityLabel(calls: ActiveToolCall[] = []): string | null {
  if (!calls.length) return null;
  return calls.map(call => [runningTitle(call.tool_id), call.target].filter(Boolean).join(" ")).join(" · ");
}

const RUNNING_TITLES: Record<string, string> = {
  update_plan: "Updating the plan",
  run_operation: "Running",
  plan_analysis: "Comparing analysis plans",
  calculate: "Calculating",
  show_chart: "Drawing a chart",
  save_report_version: "Saving a report version",
  export_analysis_script: "Exporting the analysis script",
};

function runningTitle(toolId: string): string {
  if (RUNNING_TITLES[toolId]) return RUNNING_TITLES[toolId];
  return toolTitle(toolId).replace(/^(Read|Listed|Checked|Showed)\b/, verb => ({ Read: "Reading", Listed: "Listing", Checked: "Checking", Showed: "Showing" })[verb] ?? verb);
}

/** What a step did, in the reader's words. Unlisted tools read from their id, so a new tool needs no entry here. */
const TOOL_TITLES: Record<string, string> = {
  update_plan: "Updated the plan",
  run_operation: "Ran an operation",
  plan_analysis: "Compared analysis plans",
  calculate: "Calculated",
  show_chart: "Drew a chart",
  read_reports: "Read the report",
  save_report_version: "Saved a report version",
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

export type ToolStep = {
  title: string;
  state: "done" | "failed" | "waiting";
  detail: string;
  /** What the call was about, from its arguments. */
  target: string | null;
  seconds: number | null;
};

/** With a target the verb is enough: "Ran Frequency table of a, b". */
function stepTitle(toolId: string, state: ToolStep["state"], target: string | null): string {
  if (toolId !== "run_operation" || !target) return toolTitle(toolId);
  return state === "failed" ? "Tried" : state === "waiting" ? "Proposed" : "Ran";
}

/** One readable step from the receipt's status line; an unparsed line stays visible as the detail. */
export function toolStep(statusLine: string, activity?: { target: string | null; seconds: number | null }): ToolStep {
  const target = activity?.target ?? null;
  const seconds = activity?.seconds ?? null;
  const match = /^(\S+) (✓|✗) ?([\s\S]*)$/.exec(statusLine);
  if (!match) return { title: "Step", state: "done", detail: statusLine, target, seconds };
  const [, toolId, mark, rest] = match;
  if (mark === "✗") return { title: stepTitle(toolId, "failed", target), state: "failed", detail: rest.replace(/^(\w*Error|failed) — /, ""), target, seconds };
  if (toolId === "run_operation" && rest === "proposal prepared") {
    return {
      title: target ? "Prepared a proposal for" : "Prepared a proposal",
      state: "waiting",
      detail: "Waiting for the Agent to link it to a plan step",
      target,
      seconds,
    };
  }
  if (rest.startsWith("proposal ready")) return { title: stepTitle(toolId, "waiting", target), state: "waiting", detail: "Waiting for your confirmation", target, seconds };
  const detail = rest === "ok" ? "" : rest.replace(/^read-only analysis ran without confirmation \(recorded\)( · )?/, "");
  return { title: stepTitle(toolId, "done", target), state: "done", detail, target, seconds };
}

export function observableActivity(eventType: string | null): string {
  if (!eventType) return "Starting";
  const normalized = eventType.toLowerCase();
  if (normalized === "provider_retry") return "The provider connection dropped; retrying";
  if (normalized === "compaction_start") return "Summarizing the earlier conversation to stay within the model's context";
  // A running tool names itself; with none running, the model has the turn.
  if (normalized.includes("tool") || normalized === "turn_start") return "Waiting for the model";
  if (normalized.includes("proposal")) return "Preparing a proposal";
  if (normalized === "message_start") return "Waiting for the model";
  if (normalized === "message_progress") return "Thinking";
  if (normalized === "message_update") return "Writing";
  return "Working";
}
