// v1.6.8 T10 — create-project modal.
//
// Exported separately so Task 11's topbar project switcher can reuse it.
// The parent/name validation rules and the Browse folder-picker handling are
// moved verbatim from the legacy SubmitRoute (App.tsx) — parent required;
// name required + no path separators; webkitdirectory Browse derives the
// parent from webkitRelativePath. Errors render inline in the modal (not the
// global banner). Dialog pattern mirrors lineage/modals/RawJsonModal.tsx:
// controlled open/onClose, Escape (capture + stopImmediatePropagation),
// backdrop click closes.

import { useEffect, useRef, useState } from "react";
import { ApiError, createProject } from "../api";

export const CREATE_PROJECT_TITLE_ID = "create-project-title";

interface CreateProjectModalProps {
  /** Controls visibility; modal renders null when false. */
  open: boolean;
  /** Called on Escape, close button, or backdrop click. */
  onClose: () => void;
  /** Called with the backend's project_root after a successful create. */
  onCreated: (projectRoot: string) => void;
}

export function CreateProjectModal({
  open,
  onClose,
  onCreated,
}: CreateProjectModalProps) {
  const [parent, setParent] = useState("");
  const [name, setName] = useState("demo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  // Modal-scoped Escape listener — same pattern as RawJsonModal.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () =>
      window.removeEventListener("keydown", onKey, { capture: true });
  }, [open, onClose]);

  if (!open) return null;

  // Validation rules — verbatim from SubmitRoute.
  const projectErrors: Record<string, string> = {};
  if (parent.trim() === "") projectErrors.parent = "Required";
  if (name.trim() === "") projectErrors.name = "Required";
  else if (name.includes("/") || name.includes("\\"))
    projectErrors.name = "No path separators";

  const canCreate = Object.keys(projectErrors).length === 0 && !busy;

  async function onCreateProject() {
    setBusy(true);
    setError(null);
    try {
      const result = await createProject(parent.trim(), name.trim());
      onCreated(result.project_root);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `[HTTP ${err.status}] ${err.message}`
          : err instanceof Error
            ? err.message
            : "Project creation failed";
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  // Folder-picker handling — verbatim from SubmitRoute.
  function onFolderFiles(files: FileList | null) {
    const first = files?.[0] as (File & { webkitRelativePath?: string }) | undefined;
    const relativePath = first?.webkitRelativePath;
    if (!relativePath) return;
    const rootName = relativePath.split("/")[0];
    if (rootName) setParent(parent ? parent : `/${rootName}`);
  }

  return (
    <div
      role="dialog"
      aria-labelledby={CREATE_PROJECT_TITLE_ID}
      data-testid="create-project-modal"
      onClick={(e) => {
        // Backdrop click closes; clicks inside the card do not.
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
    >
      <section
        className="panel"
        onClick={(e) => e.stopPropagation()}
        style={{ width: 480, maxWidth: "90vw" }}
      >
        <div className="panel-heading">
          <h2 id={CREATE_PROJECT_TITLE_ID}>新建项目</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{ marginLeft: "auto" }}
          >
            ×
          </button>
        </div>
        <div className="control-grid">
          <label>
            Parent folder
            <input
              aria-label="parent folder"
              aria-invalid={Boolean(projectErrors.parent)}
              placeholder="/path/to/workspace"
              value={parent}
              onChange={(event) => setParent(event.target.value)}
            />
            {projectErrors.parent && (
              <span className="field-error">{projectErrors.parent}</span>
            )}
          </label>
          <div className="folder-picker">
            <button
              type="button"
              onClick={() => folderInputRef.current?.click()}
            >
              Browse
            </button>
            <input
              ref={folderInputRef}
              aria-label="folder picker"
              className="visually-hidden"
              type="file"
              multiple
              {...({ webkitdirectory: "true", directory: "true" } as Record<
                string,
                string
              >)}
              onChange={(event) => onFolderFiles(event.target.files)}
            />
          </div>
          <label>
            Project name
            <input
              aria-label="project name"
              aria-invalid={Boolean(projectErrors.name)}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            {projectErrors.name && (
              <span className="field-error">{projectErrors.name}</span>
            )}
          </label>
          <button type="button" disabled={!canCreate} onClick={onCreateProject}>
            {busy ? "Creating…" : "Create project"}
          </button>
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
