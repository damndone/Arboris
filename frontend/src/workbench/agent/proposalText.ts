// How a proposal reads to a person: what it will do, in one line, and what
// happened to it. Shared by the approval bar and the transcript receipts.

import type { AgentProposal } from "./agentTypes";

/** One cast entry as the user typed it, e.g. `wage → string`. */
function castLine(entry: unknown): string | null {
  if (!entry || typeof entry !== "object") return null;
  const cast = entry as { column?: unknown; target_dtype?: unknown };
  if (typeof cast.column !== "string" || typeof cast.target_dtype !== "string") return null;
  return `${cast.column} → ${cast.target_dtype}`;
}

export function changeSummary(changes: Record<string, unknown>): string {
  return Object.entries(changes).map(([key, value]) => {
    if (
      key !== "model_options"
      && value
      && typeof value === "object"
      && "old" in value
      && "new" in value
    ) {
      const pair = value as { old?: unknown; new?: unknown };
      return `${key}: ${String(pair.old)} → ${String(pair.new)}`;
    }
    // A data cast's `casts` array reads as human intent, not raw JSON: the batch
    // NL path (data.columns.cast) surfaces here, and a dumped array is unreadable.
    if (key === "casts" && Array.isArray(value)) {
      const lines = value.map(castLine).filter((line): line is string => line !== null);
      if (lines.length === value.length && lines.length > 0) {
        return `Cast ${lines.join(", ")}`;
      }
    }
    if (typeof value === "string") return `${key}: ${value}`;
    return `${key}: ${JSON.stringify(value)}`;
  }).join(" · ");
}


/** The proposal in one line: its first readable step, else its changes, else its operation. */
export function proposalTitle(proposal: AgentProposal): string {
  return proposal.readable?.[0] ?? (changeSummary(proposal.changes) || proposal.operation_id);
}

/** What happened to a proposal, as a receipt says it. A confirmed proposal was
 *  approved; whether its operation succeeded is the operation's own record. */
export function proposalOutcome(status: string): { mark: string; verb: string } {
  if (status === "confirmed") return { mark: "✓", verb: "Approved" };
  if (status === "declined") return { mark: "✕", verb: "Declined" };
  if (status === "stale") return { mark: "↺", verb: "Outdated" };
  return { mark: "·", verb: status.charAt(0).toUpperCase() + status.slice(1) };
}
