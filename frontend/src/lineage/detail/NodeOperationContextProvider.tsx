import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";
import { useForest } from "../../workbench/ForestContext";
import type { GraphViewNode, HeadSetNode } from "../api/graphViewTypes";
import {
  resolveNodeOperationContext,
  type ResolveNodeOperationContextResult,
} from "../api/nodeOperationContext";

const Context = createContext<ResolveNodeOperationContextResult | null>(null);

export function NodeOperationContextProvider({
  node,
  children,
}: {
  node: GraphViewNode;
  children: ReactNode;
}) {
  const forest = useForest();
  const value = useMemo<ResolveNodeOperationContextResult | null>(() => {
    if (!forest || !("runs" in node)) return null;
    return resolveNodeOperationContext({
      forest: forest.forest,
      selected_forest_node_key: (node as HeadSetNode).nodeKey,
      active_head_run_id: forest.activeRunId,
    });
  }, [forest, node]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useResolvedNodeOperationContext(): ResolveNodeOperationContextResult | null {
  return useContext(Context);
}
