// v1.9.0 — what any part of the workspace can ask of it: open Analyze (with
// a search) or bring the Agent forward. Provided by WorkbenchWorkspace; absent
// in the classic shell, where callers simply do not offer the action.

import { createContext, useContext } from "react";

export interface WorkspaceCommands {
  analyze(search?: string): void;
  showAgent(): void;
}

export const WorkspaceCommandsContext = createContext<WorkspaceCommands | null>(null);

export function useWorkspaceCommands(): WorkspaceCommands | null {
  return useContext(WorkspaceCommandsContext);
}
