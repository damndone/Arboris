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

export interface RerunArgs {
  fromNode: string;
  opOverrides: Record<string, unknown>;
  rerunReason?: string;
  /** The run that owns `fromNode` (the rerun parent). In the forest, the selected
   *  node may belong to a different run than the one being viewed; omit to use the
   *  provider's default run. */
  runId?: string;
}

export interface RerunContextValue {
  submitRerun: (args: RerunArgs) => Promise<void>;
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
      submitRerun: async (args: RerunArgs) => {
        const res = await rerunFromNode(projectRoot, args.runId ?? runId, args);
        onRerun?.(res.run_id);
      },
    }),
    [projectRoot, runId, onRerun],
  );
  return <RerunContext.Provider value={value}>{children}</RerunContext.Provider>;
}
