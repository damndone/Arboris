import { useState } from "react";
import { createPortal } from "react-dom";
import type { RunDeletionPreview } from "../api";

function plural(count: number, singular: string, pluralLabel = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralLabel}`;
}

function blockingMessage(preview: RunDeletionPreview): string | null {
  if (preview.blocking_descendant_run_ids.length > 0) {
    return `This Run has descendants: ${preview.blocking_descendant_run_ids.join(", ")}.`;
  }
  if (preview.blocking_status) {
    return `This Run is ${preview.blocking_status} and cannot be deleted.`;
  }
  return null;
}

export function RunDeletionDialog({
  preview,
  busy = false,
  error = null,
  onClose,
  onConfirm,
}: {
  preview: RunDeletionPreview;
  busy?: boolean;
  error?: string | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const [typedRunId, setTypedRunId] = useState("");
  const blocked = blockingMessage(preview);
  const readyToDelete = preview.deletable && typedRunId === preview.run_id && !busy;
  const deletedRecords =
    preview.agent_session_ids.length +
    preview.agent_event_session_ids.length +
    preview.proposal_ids.length +
    preview.operation_record_ids.length;

  return createPortal(
    <div
      role="presentation"
      data-testid="run-deletion-overlay"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1200,
        display: "grid",
        placeItems: "center",
        padding: 20,
        background: "rgba(0, 0, 0, 0.48)",
      }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="run-deletion-title"
        style={{
          width: "min(520px, 100%)",
          borderRadius: 14,
          padding: 22,
          background: "var(--bg-card, #fff)",
          color: "var(--label, #1d1d1f)",
          boxShadow: "0 22px 70px rgba(0, 0, 0, 0.32)",
        }}
      >
        <h2 id="run-deletion-title" style={{ margin: 0, fontSize: 18 }}>
          Delete Run permanently?
        </h2>
        <p style={{ margin: "10px 0 0", color: "var(--label-secondary, #5f6368)" }}>
          This removes <strong>{preview.run_id}</strong> and its exclusive persisted outputs. It cannot be undone.
        </p>
        {blocked ? (
          <p role="alert" style={{ margin: "16px 0", color: "var(--danger, #c5221f)" }}>
            {blocked}
          </p>
        ) : (
          <>
            <ul style={{ margin: "16px 0", paddingLeft: 20, color: "var(--label-secondary, #5f6368)" }}>
              <li>{plural(Object.values(preview.artifact_counts).reduce((total, count) => total + count, 0), "artifact")}</li>
              <li>{plural(preview.report_count, "report")}</li>
              <li>{plural(deletedRecords, "exclusive agent/control record")}</li>
              {preview.retained_shared_record_ids.length > 0 && (
                <li>{plural(preview.retained_shared_record_ids.length, "shared record")} will be retained</li>
              )}
            </ul>
            <label htmlFor="run-deletion-confirmation" style={{ display: "block", fontSize: 13, fontWeight: 600 }}>
              Type {preview.run_id} to confirm
            </label>
            <input
              id="run-deletion-confirmation"
              value={typedRunId}
              onChange={(event) => setTypedRunId(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              disabled={busy}
              style={{
                width: "100%",
                boxSizing: "border-box",
                marginTop: 8,
                padding: "9px 10px",
                borderRadius: 8,
                border: "1px solid var(--separator, #d9d9de)",
                background: "var(--bg-card-2, #fff)",
                color: "inherit",
              }}
            />
          </>
        )}
        {error && <p role="alert" style={{ margin: "14px 0 0", color: "var(--danger, #c5221f)" }}>{error}</p>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
          <button type="button" onClick={onClose} disabled={busy}>
            Close
          </button>
          {!blocked && (
            <button
              type="button"
              onClick={onConfirm}
              disabled={!readyToDelete}
              style={{
                border: 0,
                borderRadius: 8,
                padding: "8px 12px",
                background: "var(--danger, #c5221f)",
                color: "#fff",
                cursor: readyToDelete ? "pointer" : "not-allowed",
                opacity: readyToDelete ? 1 : 0.5,
              }}
            >
              {busy ? "Deleting…" : "Delete permanently"}
            </button>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}
