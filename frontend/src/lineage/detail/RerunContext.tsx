// frontend/src/lineage/detail/RerunContext.tsx
//
// v1.6.1 (2C.3) — the bridge that lets a node's OperationSection submit a
// rerun without knowing the project/run or how the forest refetches.
//
// The forest canvas wraps the detail drawer in a <RerunProvider> carrying the
// current projectRoot/runId + an `onRerun` callback. OperationSection reads the
// context's `submitRerun`; if there's no provider (legacy DetailDrawer), the
// section degrades to read-only. Submitting NEVER navigates — `onRerun` just
// refetches the head-set so the new sibling branch grows in place (spec §3.3).

import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";
import { rerunFromNode } from "../../api";
import { resolveOwnerRun } from "../api/graphViewTypes";

export interface RerunArgs {
  fromNode: string;
  opOverrides: Record<string, unknown>;
  rerunReason?: string;
  /** The runs that own `fromNode`. A forest node can be shared across runs (deduped),
   *  so the parent is resolved against the active head (see resolveOwnerRun): if the
   *  head owns the node it forks from the version the user is viewing, else from the
   *  first owning run. Omit/empty → fall back to the provider's active run. */
  candidateRuns?: string[];
}

export interface RerunContextValue {
  submitRerun: (args: RerunArgs) => Promise<void>;
  /** The active head's run id — the rerun parent default and the run a node-detail
   *  header should attribute the view to. */
  activeRunId: string;
}

export const RerunContext = createContext<RerunContextValue | null>(null);

export function useRerun(): RerunContextValue | null {
  return useContext(RerunContext);
}

export function RerunProvider({
  projectRoot,
  runId,
  onRerun,
  children,
}: {
  projectRoot: string;
  runId: string;
  /** Called with the new child run id after a successful rerun. The forest
   *  passes a head-set refetch here — deliberately NO router navigation. */
  onRerun?: (childRunId: string) => void;
  children: ReactNode;
}) {
  const value = useMemo<RerunContextValue>(
    () => ({
      activeRunId: runId,
      submitRerun: async (args: RerunArgs) => {
        // `runId` here is the active head (see RerunProvider mount). For a shared node
        // the parent must be the head when it owns the node, else an owning run.
        const parent = resolveOwnerRun(args.candidateRuns, runId) ?? runId;
        const res = await rerunFromNode(projectRoot, parent, args);
        onRerun?.(res.run_id);
      },
    }),
    [projectRoot, runId, onRerun],
  );
  return <RerunContext.Provider value={value}>{children}</RerunContext.Provider>;
}
