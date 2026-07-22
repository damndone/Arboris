import type { NotebookSelection } from "./contracts";

/**
 * Gate 6 — selected text as the unit of interaction.
 *
 * Every action carries the selection verbatim plus its `source_ref`, so a
 * follow-up question can be traced back to the sentence that provoked it. None
 * of these actions runs anything: the deferred-option action asks the agent for
 * a proposal, which still has to pass the validator and a confirmation step.
 */

export interface SelectionActionsProps {
  selection: NotebookSelection | null;
  onAsk?: (selection: NotebookSelection) => void;
  onExplain?: (selection: NotebookSelection) => void;
  onFollowUp?: (selection: NotebookSelection) => void;
  onSaveNote?: (selection: NotebookSelection) => void;
  onDeferAsOption?: (selection: NotebookSelection) => void;
}

export function SelectionActions({
  selection,
  onAsk,
  onExplain,
  onFollowUp,
  onSaveNote,
  onDeferAsOption,
}: SelectionActionsProps) {
  if (!selection) return null;

  const actions: { key: string; label: string; handler?: (s: NotebookSelection) => void }[] = [
    { key: "ask", label: "Add to question", handler: onAsk },
    { key: "explain", label: "Explain this", handler: onExplain },
    { key: "follow-up", label: "Ask a targeted follow-up", handler: onFollowUp },
    { key: "note", label: "Save as note", handler: onSaveNote },
    { key: "defer", label: "Save as deferred option", handler: onDeferAsOption },
  ];

  return (
    <div className="nb-selection-actions" data-testid="notebook-selection-actions">
      <blockquote className="nb-selection-quote" data-testid="selection-quote">
        {selection.text}
      </blockquote>
      <span
        className="nb-selection-source"
        data-testid="selection-source"
        data-source-ref={selection.source_ref}
      >
        {`from ${selection.source_label}`}
      </span>
      <div className="nb-selection-buttons">
        {actions.map((action) => (
          <button
            key={action.key}
            type="button"
            className="nb-button"
            data-testid={`selection-action-${action.key}`}
            onClick={() => action.handler?.(selection)}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}
