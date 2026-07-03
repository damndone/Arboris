// v1.6.7 — carries the DraftRegistry + draft action handlers down to the
// NodeActionMenu (fork) and the DraftEditorSlot (edit/validate/execute/discard)
// without prop-drilling through WorkbenchShell. Mirrors RerunContext.
import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { PipelineDraftPatchRequest, PipelineDraftResponse } from "../../api";
import type { DraftRegistry } from "./draftRegistry";

export interface DraftActionsValue {
  registry: DraftRegistry;
  busy: boolean;
  onForkDraft: (created: PipelineDraftResponse) => void;
  onPatch: (draftId: string, body: PipelineDraftPatchRequest) => void;
  onValidate: (draftId: string) => void;
  onExecute: (draftId: string) => void;
  onDiscard: (draftId: string) => void;
  onEnsureLoaded: (draftId: string) => void;
}

const DraftActionsContext = createContext<DraftActionsValue | null>(null);

export function useDraftActions(): DraftActionsValue | null {
  return useContext(DraftActionsContext);
}

export function DraftActionsProvider({
  value,
  children,
}: {
  value: DraftActionsValue;
  children: ReactNode;
}) {
  return (
    <DraftActionsContext.Provider value={value}>
      {children}
    </DraftActionsContext.Provider>
  );
}
