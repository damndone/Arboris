import { createContext, useContext, useState, type ReactNode } from "react";

export type ReportPreviewSelection = { term: string | null; level: number | null };

const ReportPreviewSelectionContext = createContext<{
  selections: Record<string, ReportPreviewSelection>;
  setSelection: (nodeKey: string, next: ReportPreviewSelection) => void;
} | null>(null);

export function ReportPreviewSelectionProvider({ children }: { children: ReactNode }) {
  const [selections, setSelections] = useState<Record<string, ReportPreviewSelection>>({});
  return (
    <ReportPreviewSelectionContext.Provider value={{
      selections,
      setSelection: (nodeKey, next) => setSelections((current) => ({ ...current, [nodeKey]: next })),
    }}>
      {children}
    </ReportPreviewSelectionContext.Provider>
  );
}

export function useReportPreviewSelection(
  nodeKey: string,
): [ReportPreviewSelection | undefined, ((next: ReportPreviewSelection) => void) | undefined] {
  const context = useContext(ReportPreviewSelectionContext);
  return context
    ? [context.selections[nodeKey], (next) => context.setSelection(nodeKey, next)]
    : [undefined, undefined];
}
