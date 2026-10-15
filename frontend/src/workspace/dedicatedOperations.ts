// v1.9.0 — opening an operation that has its own place in the workbench. The
// catalog says where (`execution.surface`); this module takes the person
// there, on the target they chose in Analyze.

import type { Operation, Target } from "../manual/manualApi";
import type { ViewMode } from "../workbench/state/urlSchema";

export type Surface = NonNullable<Operation["execution"]["surface"]>;

export interface DedicatedContext {
  /** Make the target's run active and select its step on the map. */
  focus(target: Target): void;
  setView(view: ViewMode): void;
  openNewAnalysis?(): void;
  openAnalyze(): void;
  closeAnalyze(): void;
  /** Create a branch proposal from a saved step and open it in the Agent. */
  proposeFork(target: Target & { run_id: string; node_id: string }): Promise<void>;
}

const VIEW: Partial<Record<Surface, ViewMode>> = { graph: "graph", data: "data", table: "table", notebook: "notebook" };

/** Resolves to an error message for the person, or null when it went through. */
export async function openDedicated(op: Operation, target: Target | undefined, ctx: DedicatedContext): Promise<string | null> {
  const surface: Surface = op.execution.surface ?? "graph";
  if (surface === "agent") {
    if (!target || !("run_id" in target) || !("node_id" in target)) return "Select a saved step before creating a branch.";
    try {
      await ctx.proposeFork(target);
      ctx.closeAnalyze();
      return null;
    } catch (error) {
      return error instanceof Error ? error.message : String(error);
    }
  }
  if (surface === "analyze") {
    ctx.openAnalyze();
    return null;
  }
  ctx.closeAnalyze();
  if (target && "run_id" in target) ctx.focus(target);
  if (surface === "new_analysis") ctx.openNewAnalysis?.();
  else ctx.setView(VIEW[surface] ?? "graph");
  return null;
}
