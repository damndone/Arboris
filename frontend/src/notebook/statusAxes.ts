/**
 * The three status axes stay three (spec §3.4).
 *
 * `lifecycle_status`, `freshness_status` and `validation_status` are
 * orthogonal: an option can be `deferred` + `stale` + `valid` at once, and
 * collapsing them into a single badge would erase the fact that it was valid
 * for the context it was generated against. Nothing here decides whether an
 * option is good — it only decides whether the UI is allowed to offer a
 * one-click run, which spec §4.3 forbids for anything not `fresh`.
 */

import type { NotebookOptionRevision } from "./contracts";

export interface Executability {
  executable: boolean;
  /** Human-readable reason, rendered next to the disabled control. */
  blockedReason: string | null;
  /** True when the honest next step is "ask the agent to revalidate". */
  needsRevalidation: boolean;
}

const TERMINAL_LIFECYCLE_REASON: Partial<Record<NotebookOptionRevision["lifecycle_status"], string>> =
  {
    executing: "This option is already executing",
    executed: "This option has already been executed",
    rejected: "This option was rejected",
    archived: "This option belongs to an archived batch",
  };

export function executability(option: NotebookOptionRevision): Executability {
  if (option.freshness_status === "stale") {
    return {
      executable: false,
      needsRevalidation: true,
      blockedReason:
        "Upstream context changed — this option must be revalidated by the agent before it can run",
    };
  }
  if (option.freshness_status === "revalidating") {
    return {
      executable: false,
      needsRevalidation: false,
      blockedReason: "Revalidating against the current context",
    };
  }
  if (option.validation_status === "invalid") {
    return {
      executable: false,
      needsRevalidation: false,
      blockedReason: "The proposal validator rejected this option",
    };
  }
  if (option.validation_status === "unvalidated") {
    return {
      executable: false,
      needsRevalidation: false,
      blockedReason: "The proposal validator has not judged this option yet",
    };
  }
  const lifecycleReason = TERMINAL_LIFECYCLE_REASON[option.lifecycle_status];
  if (lifecycleReason) {
    return { executable: false, needsRevalidation: false, blockedReason: lifecycleReason };
  }
  return { executable: true, blockedReason: null, needsRevalidation: false };
}

/** Per-axis caption. Never merged into one sentence. */
export function axisNote(option: NotebookOptionRevision): {
  lifecycle: string | null;
  freshness: string | null;
  validation: string | null;
} {
  return {
    lifecycle:
      option.lifecycle_status === "deferred"
        ? "kept for later, not scheduled"
        : null,
    freshness:
      option.freshness_status === "stale"
        ? "the context it depends on has moved"
        : option.freshness_status === "revalidating"
          ? "the agent is regenerating this option"
          : null,
    validation:
      option.validation_status === "valid"
        ? "valid for the context it was generated against"
        : option.validation_status === "unvalidated"
          ? "not yet judged by the proposal validator"
          : "rejected by the proposal validator",
  };
}

export function rankLabel(rank: number): string {
  return rank === 1 ? "rank 1 · recommended" : `rank ${rank} · alternative`;
}
