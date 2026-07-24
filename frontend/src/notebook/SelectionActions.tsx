import { useState, type CSSProperties } from "react";
import type { NotebookSelection, NotebookSelectionAnchor } from "./contracts";

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
  anchor?: NotebookSelectionAnchor | null;
  onAddToTask?: (selection: NotebookSelection) => void;
  onMoreDetails?: (selection: NotebookSelection) => void;
  onAskInSideChat?: (selection: NotebookSelection) => void;
  onAsk?: (selection: NotebookSelection) => void;
  onExplain?: (selection: NotebookSelection) => void;
  onFollowUp?: (selection: NotebookSelection) => void;
  onSaveNote?: (selection: NotebookSelection) => void;
  onDeferAsOption?: (selection: NotebookSelection) => void;
}

export function SelectionActions({
  selection,
  anchor,
  onAddToTask,
  onMoreDetails,
  onAskInSideChat,
  onAsk,
  onExplain,
  onFollowUp,
  onSaveNote,
  onDeferAsOption,
}: SelectionActionsProps) {
  const [moreOpen, setMoreOpen] = useState(false);
  if (!selection) return null;

  const primaryActions: {
    key: string;
    label: string;
    handler?: (s: NotebookSelection) => void;
  }[] = [
    { key: "add-to-task", label: "Add to task", handler: onAddToTask ?? onAsk },
    { key: "more-details", label: "More details", handler: onMoreDetails ?? onExplain },
    { key: "side-chat", label: "Ask in side chat", handler: onAskInSideChat ?? onFollowUp },
  ];
  const additionalActions: {
    key: string;
    label: string;
    handler?: (s: NotebookSelection) => void;
  }[] = [
    { key: "ask", label: "Ask a targeted follow-up", handler: onFollowUp },
    { key: "note", label: "Save as note", handler: onSaveNote },
    { key: "defer", label: "Save as deferred option", handler: onDeferAsOption },
  ];
  const style: CSSProperties | undefined = anchor
    ? { position: "fixed", top: anchor.top, left: anchor.left, zIndex: 20 }
    : undefined;

  return (
    <div
      className="nb-selection-actions"
      data-testid="notebook-selection-actions"
      style={style}
    >
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
        {primaryActions.map((action) => (
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
        <button
          type="button"
          className="nb-button"
          data-testid="selection-action-more"
          aria-expanded={moreOpen}
          onClick={() => setMoreOpen((open) => !open)}
        >
          More actions
        </button>
      </div>
      {moreOpen ? (
        <div className="nb-selection-more" data-testid="selection-more-menu">
          {additionalActions.map((action) => (
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
      ) : null}
    </div>
  );
}
