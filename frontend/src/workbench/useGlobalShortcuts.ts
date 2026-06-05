// frontend/src/workbench/useGlobalShortcuts.ts
//
// V1.5.3 F6 — global keyboard dispatcher for the action registry.
//
// Wires actionRegistry entries that declare a `keys` binding + the
// "shortcut" surface to a single window keydown listener. The action
// runs against the CURRENT selected node (the drawer's subject), which
// is the natural target for node-scoped verbs like "copy node id".
//
// Safety rails:
//   - Reuses F4's isEditableTarget: never fires while the user types
//     into an input / textarea / select / contenteditable.
//   - No selected node → no ctx → nothing fires (node-scoped actions
//     need a subject).
//   - Disabled / non-rendering actions are filtered by actionForShortcut,
//     so a bound key silently no-ops when its action isn't available.
//
// Mounted once in WorkbenchRouteContainer's shell, alongside ⌘J/⌘K.

import { useEffect } from "react";
import { useLineage } from "../lineage/LineageContext";
import { useWorkbench } from "./WorkbenchStateProvider";
import {
  actionForShortcut,
  type ActionContext,
} from "./registry/actionRegistry";
import { isEditableTarget } from "./keyboard";

export function useGlobalShortcuts(): void {
  const { model, selectedKey } = useLineage();
  const { state, dispatch } = useWorkbench();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // F4 rule: don't hijack keys while editing text.
      if (isEditableTarget(document.activeElement)) return;

      // Node-scoped actions need a subject — the selected node.
      if (selectedKey === null) return;
      const node = model.nodes.find((n) => n.nodeKey === selectedKey);
      if (!node) return;

      const ctx: ActionContext = {
        node,
        model,
        selectedKey: state.selectedKey,
        focusKey: state.focusKey,
        pinned: state.pinned,
        dispatch: {
          openDetail: dispatch.selectByCanvasClick,
          pinTab: dispatch.selectByCanvasClick,
          pinUpstream: dispatch.pinFocus,
          focusUpstream: dispatch.setFocusOnly,
        },
      };

      const action = actionForShortcut(e, ctx);
      if (!action) return;
      e.preventDefault();
      action.invoke(ctx);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [model, selectedKey, state, dispatch]);
}
