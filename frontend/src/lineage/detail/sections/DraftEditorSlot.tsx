// v1.6.7 — section slot: renders the DraftEditorSection for a draft node by
// pulling its registry entry + handlers from DraftActionsContext. Registered
// in sectionRegistry with shouldRender=isDraft. Degrades to null when there's
// no provider (e.g. legacy/bare-mount tests) or the entry isn't in the registry.
import type { FC } from "react";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { useDraftActions } from "../../drafts/DraftActionsContext";
import { DraftEditorSection } from "./DraftEditorSection";

export const DraftEditorSlot: FC<{ node: GraphViewNode }> = ({ node }) => {
  const actions = useDraftActions();
  if (!node.isDraft || !node.draftId || !actions) return null;
  const entry = actions.registry.get(node.draftId);
  if (!entry) return null;
  return (
    <DraftEditorSection
      entry={entry}
      onPatch={actions.onPatch}
      onValidate={actions.onValidate}
      onExecute={actions.onExecute}
      onDiscard={actions.onDiscard}
      busy={actions.busy}
    />
  );
};
