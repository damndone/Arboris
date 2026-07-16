// v1.6.7 — section slot: renders the DraftEditorSection for a draft node by
// pulling its registry entry + handlers from DraftActionsContext. Registered
// in sectionRegistry with shouldRender=isDraft. Degrades to null when there's
// no provider (e.g. legacy/bare-mount tests) or the entry isn't in the registry.
import { useEffect } from "react";
import type { FC } from "react";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { useDraftActions } from "../../drafts/DraftActionsContext";
import { DraftEditorSection } from "./DraftEditorSection";

export const DraftEditorSlot: FC<{ node: GraphViewNode }> = ({ node }) => {
  const actions = useDraftActions();
  const entry =
    actions && node.isDraft && node.draftId
      ? actions.registry.get(node.draftId) ?? null
      : null;
  const draftId = entry?.draftId ?? null;
  const needsLoad = entry !== null && entry.draft === null;
  const onEnsureLoaded = actions?.onEnsureLoaded;

  useEffect(() => {
    if (needsLoad && draftId && onEnsureLoaded) onEnsureLoaded(draftId);
  }, [needsLoad, draftId, onEnsureLoaded]);

  if (!actions || !entry) return null;
  return (
    <DraftEditorSection
      entry={entry}
      error={actions.errors?.[entry.draftId] ?? null}
      onPatch={actions.onPatch}
      onValidate={actions.onValidate}
      onExecute={actions.onExecute}
      onDiscard={actions.onDiscard}
      busy={actions.busy}
    />
  );
};
