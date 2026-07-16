// v1.6.7 — draft editor mounted in the detail drawer for draft nodes.
// Reuses ModelNodeInspector for the editable_schema controls + Save (which
// emits a patch body), and adds Validate / Execute / Discard wired to the
// DraftRegistry via callbacks. Execute is gated on the draft being valid.
import type { PipelineDraftNode, PipelineDraftPatchRequest } from "../../../api";
import { ModelNodeInspector } from "../../../pipelineDrafts/ModelNodeInspector";
import type { DraftEntry } from "../../drafts/draftRegistry";

type ModelNode = Extract<PipelineDraftNode, { node_type: "model" }>;

export interface DraftEditorSectionProps {
  entry: DraftEntry;
  error?: string | null;
  onPatch: (draftId: string, body: PipelineDraftPatchRequest) => void;
  onValidate: (draftId: string) => void;
  onExecute: (draftId: string) => void;
  onDiscard: (draftId: string) => void;
  busy: boolean;
}

export function DraftEditorSection({
  entry, error = null, onPatch, onValidate, onExecute, onDiscard, busy,
}: DraftEditorSectionProps) {
  const modelNode = entry.draft?.graph.nodes.find(
    (n): n is ModelNode => n.node_type === "model",
  );
  const canExecute = entry.lifecycleState === "valid" && !busy;

  return (
    <section className="draft-editor" aria-label="Draft editor">
      {error && (
        <div role="alert" style={{ color: "var(--danger, #b00020)", marginBottom: 8 }}>
          Draft request failed: {error}
        </div>
      )}
      {modelNode ? (
        <ModelNodeInspector
          node={modelNode}
          draftHash={entry.draftHash}
          onSave={(body) => onPatch(entry.draftId, body)}
          disabled={busy}
        />
      ) : (
        <p className="draft-editor__loading">Loading draft…</p>
      )}
      {entry.validation && entry.validation.checks.length > 0 && (
        <ul className="draft-editor__checks" aria-label="Validation checks">
          {entry.validation.checks.map((c) => (
            <li key={`${c.code}:${c.node_id ?? ""}`}>
              {c.code}: {c.message}
            </li>
          ))}
        </ul>
      )}
      <div className="draft-editor__actions">
        <button type="button" disabled={busy} onClick={() => onValidate(entry.draftId)}>
          Validate
        </button>
        <button type="button" disabled={!canExecute} onClick={() => onExecute(entry.draftId)}>
          Execute
        </button>
        <button type="button" disabled={busy} onClick={() => onDiscard(entry.draftId)}>
          Discard
        </button>
      </div>
    </section>
  );
}
