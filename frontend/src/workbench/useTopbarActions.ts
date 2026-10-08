// Topbar analysis actions (plan §15), shared by the classic topbar and the
// v1.9.0 workspace topbar. The context node is the primary MODEL node — its
// drawer hosts the editable rerun panel — so "Rerun" re-runs the analysis
// from any view instead of no-op'ing on whatever happens to be selected.

import { useLineage } from "../lineage/LineageContext";
import { useWorkbench } from "./WorkbenchStateProvider";
import { actionsForSurface, type ActionContext, type ActionEntry } from "./registry/actionRegistry";
import { pickRerunTargetKey } from "./rerunTarget";

export function useTopbarActions(): { actionCtx: ActionContext | null; actions: ActionEntry[] } {
  const { state, dispatch } = useWorkbench();
  const { model } = useLineage();
  const targetKey = pickRerunTargetKey(model, state.selectedKey);
  const ctxNode = model.nodes.find((n) => n.nodeKey === targetKey) ?? model.nodes[0];
  const actionCtx: ActionContext | null = ctxNode
    ? {
        node: ctxNode,
        model,
        selectedKey: state.selectedKey,
        focusKey: state.focusKey,
        pinned: state.pinned,
        dispatch: {
          openDetail: dispatch.selectByCanvasClick,
          pinTab: dispatch.selectByCanvasClick,
          pinUpstream: dispatch.pinFocus,
          // F1: focus-only (see ContextMenu) — don't move selection.
          focusUpstream: dispatch.setFocusOnly,
        },
      }
    : null;
  return { actionCtx, actions: actionCtx ? actionsForSurface("topbar", actionCtx) : [] };
}
