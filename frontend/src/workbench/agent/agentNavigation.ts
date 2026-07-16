import { createContext, useContext } from "react";
import {
  parseWorkbenchUrl,
  writeWorkbenchUrl,
  type WorkbenchUrlSlice,
} from "../state/urlSchema";
import type { AgentNavigationRef } from "./agentTypes";

export type AgentNavigationHandler = (ref: AgentNavigationRef) => boolean;

export const AgentNavigationContext = createContext<AgentNavigationHandler | null>(null);

export function useAgentNavigationOptional(): AgentNavigationHandler | null {
  return useContext(AgentNavigationContext);
}

/** Apply one verified navigation ref without constructing an arbitrary URL. */
export function applyAgentNavigationRef(
  params: URLSearchParams,
  ref: AgentNavigationRef,
): URLSearchParams {
  const out = new URLSearchParams(params);
  if (!ref.available) return out;

  const href = ref.href;
  if (href.run_id) out.set("run", href.run_id);

  const current = parseWorkbenchUrl(out);
  if (href.view === "graph") {
    const focusKey = href.forest_node_key || href.node_ref || null;
    const next: WorkbenchUrlSlice = {
      ...current,
      view: "graph",
      focusKey,
      pinned: focusKey !== null,
      diffFocused: false,
    };
    return writeWorkbenchUrl(out, next);
  }

  const next: WorkbenchUrlSlice = {
    ...current,
    bottomPanel: "agent",
    agentSessionId: href.session_id,
    agentEntryId: href.entry_id,
    operationRecordId: href.operation_record_id,
    diffFocused: href.diff === "1",
  };
  return writeWorkbenchUrl(out, next);
}
