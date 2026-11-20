import { useEffect, useRef, useState } from "react";
import type { NotebookSelection } from "./contracts";
import { listNotebookNotes, saveNotebookNote, type NotebookNote } from "./notebookApi";
import "./NotebookNotes.css";

export function NotebookNotes({ projectRoot, notebookId, selection, onDismiss }: {
  projectRoot: string;
  notebookId: string;
  selection: NotebookSelection | null;
  onDismiss: () => void;
}) {
  const [notes, setNotes] = useState<NotebookNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const mounted = useRef(false);
  const draft = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current = true;
    mounted.current = true;
    void listNotebookNotes(projectRoot, notebookId).then(
      (items) => { if (current) setNotes(items); },
      (failure) => { if (current) setError(failure instanceof Error ? failure.message : "Could not load Notebook notes."); },
    ).finally(() => { if (current) setLoading(false); });
    return () => { current = false; mounted.current = false; };
  }, [projectRoot, notebookId]);

  useEffect(() => {
    if (selection) {
      setSaved(false);
      draft.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    }
  }, [selection]);

  async function save() {
    if (!selection || saving || loading) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const note = await saveNotebookNote(projectRoot, notebookId, selection);
      if (!mounted.current) return;
      setNotes((current) => [...current, note]);
      onDismiss();
      setSaved(true);
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : "The note could not be saved.");
    } finally {
      if (mounted.current) setSaving(false);
    }
  }

  return <section className="nb-selection-composer nb-notes" data-testid="notebook-notes" aria-label="Notebook notes">
    <h3>Notebook notes</h3>
    <p>Saved in this project with the selected source.</p>
    {loading ? <p role="status">Loading notes…</p> : null}
    {notes.length > 0 ? <ul className="nb-notes-list">{notes.map((note) => <li key={note.note_id}>
      <blockquote>{note.text}</blockquote>
      <p>{note.source_label} · <code>{note.source_ref}</code></p>
      <time dateTime={note.created_at}>{new Date(note.created_at).toLocaleString()}</time>
    </li>)}</ul> : !loading && !error ? <p>No saved notes yet.</p> : null}
    {selection ? <div ref={draft} data-testid="notebook-note-draft">
      <h4>Save selected passage</h4>
      <blockquote>{selection.text}</blockquote>
      <p>{selection.source_label} · <code>{selection.source_ref}</code></p>
      <div className="nb-selection-composer-actions">
        <button type="button" className="nb-button nb-button-primary" disabled={saving || loading} onClick={() => void save()}>
          {saving ? "Saving note…" : "Save note"}
        </button>
        <button type="button" className="nb-button" disabled={saving} onClick={onDismiss}>Cancel</button>
      </div>
    </div> : null}
    {error ? <p role="alert">{error}</p> : null}
    {saved ? <p role="status">Note saved in this Notebook.</p> : null}
  </section>;
}
