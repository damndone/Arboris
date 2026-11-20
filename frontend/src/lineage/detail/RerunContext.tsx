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

import { createContext, useContext, useEffect, useMemo, useRef } from "react";
import type { ReactNode } from "react";
import { rerunFromNode } from "../../api";
import type {
  NodeWriteOperationRequestV1,
  RerunResponseV1,
} from "../../api";
import type { NodeOperationContextV1 } from "../api/nodeOperationContext";
import type { ManualRerunPatch } from "./sections/manualRerunPatch";

export interface RerunArgs {
  context: NodeOperationContextV1;
  opOverrides: Record<string, unknown>;
  manualPatch?: ManualRerunPatch;
  rerunReason?: string;
}

export interface RerunReceipt {
  runId: string;
  contextFingerprint: string;
  status: string;
  issue?: string;
  href: string;
}

export interface RerunContextValue {
  submitRerun: (args: RerunArgs) => Promise<RerunResponseV1>;
  /** The active head's run id — the rerun parent default and the run a node-detail
   *  header should attribute the view to. */
  activeRunId: string;
  receipt?: RerunReceipt | null;
  busy?: boolean;
}

export const RerunContext = createContext<RerunContextValue | null>(null);

export function useRerun(): RerunContextValue | null {
  return useContext(RerunContext);
}

export function RerunProvider({
  projectRoot,
  runId,
  onRerun,
  receipt,
  busy = false,
  onSubmitting,
  children,
}: {
  projectRoot: string;
  runId: string;
  onRerun?: (response: RerunResponseV1, context: NodeOperationContextV1) => void;
  receipt?: RerunReceipt | null;
  busy?: boolean;
  onSubmitting?: (submitting: boolean) => void;
  children: ReactNode;
}) {
  const scope = useMemo(() => ({alive: true, submitting: false}), [projectRoot, runId]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  useEffect(() => {
    scope.alive = true;
    return () => {
      scope.alive = false;
      if (scope.submitting) {
        scope.submitting = false;
        onSubmitting?.(false);
      }
    };
  }, [scope]);
  const value = useMemo<RerunContextValue>(
    () => ({
      activeRunId: runId,
      receipt,
      busy,
      submitRerun: async (args: RerunArgs) => {
        if (!scope.alive || currentScope.current !== scope) throw new Error("The run view changed before submission.");
        if (busy || scope.submitting) throw new Error("Another run is being submitted or observed. Open that run before submitting another.");
        onSubmitting?.(true);
        scope.submitting = true;
        try {
          const target = args.context.operation_target;
          const request: NodeWriteOperationRequestV1 = {
            request_id: `rerun_${Date.now()}_${Math.random().toString(36).slice(2)}`,
            operation: "rerun",
            context_version: args.context.context_version,
            context_fingerprint: args.context.context_fingerprint,
            owner_run_id: target.owner_run_id,
            op_node_id: target.op_node_id,
            node_hash: target.node_hash,
            forest_node_key: args.context.selection.forest_node_key,
            owner_resolution: args.context.ownership.owner_resolution,
            active_head_run_id: args.context.ownership.active_head_run_id,
            op_overrides: args.manualPatch ? {} : args.opOverrides,
            manual_patch: args.manualPatch,
            rerun_reason: args.rerunReason,
          };
          const res = await rerunFromNode(projectRoot, target.owner_run_id, request);
          if (scope.alive && currentScope.current === scope) onRerun?.(res, args.context);
          return res;
        } finally {
          if (scope.alive && currentScope.current === scope) {
            scope.submitting = false;
            onSubmitting?.(false);
          }
        }
      },
    }),
    [projectRoot, runId, onRerun, receipt, busy, onSubmitting, scope],
  );
  return <RerunContext.Provider value={value}>{children}</RerunContext.Provider>;
}
