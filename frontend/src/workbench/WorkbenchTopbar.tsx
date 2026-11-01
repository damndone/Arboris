import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { rootToSlug } from "./projectSlug";
import { CreateProjectModal } from "../launcher/CreateProjectModal";
import { listRecents, touchRecent } from "../launcher/recents";

function projectName(root: string): string {
  return root.split("/").filter(Boolean).pop() ?? root;
}

/**
 * v1.6.8 T11 — topbar project switcher: the project name opens a dropdown of
 * recent projects (current one marked) plus a new-project entry which reuses the
 * launcher's CreateProjectModal. Selecting / creating touches recents and
 * navigates to the project's graph home. Popover conventions mirror
 * ContextMenu.tsx (card background, 12px radius, separator ring).
 */
export function ProjectSwitcher({ projectRoot }: { projectRoot: string }) {
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const recents = open ? listRecents() : [];

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpen(false);
    };
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (rootRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onScroll = () => setOpen(false);
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("mousedown", onMouseDown, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onMouseDown, true);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  function goToProject(root: string, opts: { openGenesis?: boolean } = {}) {
    setOpen(false);
    touchRecent(root);
    const suffix = opts.openGenesis ? "?open_genesis=1" : "";
    navigate(`/p/${rootToSlug(root)}/graph${suffix}`, {
      state: opts.openGenesis ? { openGenesis: true } : undefined,
    });
  }

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <button
        type="button"
        data-testid="project-switcher"
        aria-haspopup="menu"
        aria-expanded={open}
        title={projectRoot}
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "4px 10px",
          borderRadius: 6,
          border: "1px solid var(--separator)",
          background: "transparent",
          color: "var(--label)",
          cursor: "pointer",
          fontSize: 13,
          fontWeight: 600,
        }}
      >
        <span className="wb-project-name">{projectName(projectRoot)}</span>
        <span aria-hidden="true" style={{ fontSize: 10 }}>
          ▾
        </span>
      </button>
      {open && (
        <div
          role="menu"
          data-testid="project-switcher-menu"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            background: "var(--bg-card-2)",
            borderRadius: 12,
            padding: 6,
            minWidth: 260,
            boxShadow:
              "var(--shadow-pop), 0 0 0 1px var(--separator)",
            zIndex: 1000,
          }}
        >
          {recents.map((recent) => {
            const isCurrent = recent.root === projectRoot;
            return (
              <button
                key={recent.root}
                type="button"
                role="menuitem"
                aria-current={isCurrent ? "true" : undefined}
                onClick={() => {
                  if (isCurrent) {
                    setOpen(false);
                    return;
                  }
                  goToProject(recent.root);
                }}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                  width: "100%",
                  padding: "9px 12px",
                  borderRadius: 8,
                  background: "transparent",
                  border: 0,
                  color: "var(--label)",
                  cursor: "pointer",
                  textAlign: "left",
                  font: "inherit",
                  fontSize: 13.5,
                }}
              >
                <span>{projectName(recent.root)}</span>
                {isCurrent && (
                  <span
                    style={{ color: "var(--label-tertiary)", fontSize: 12 }}
                  >
                    Current
                  </span>
                )}
              </button>
            );
          })}
          <button
            type="button"
            role="menuitem"
            data-testid="project-switcher-new"
            onClick={() => {
              setOpen(false);
              setModalOpen(true);
            }}
            style={{
              display: "block",
              width: "100%",
              padding: "9px 12px",
              borderRadius: 8,
              background: "transparent",
              border: 0,
              borderTop: recents.length > 0 ? "1px solid var(--separator)" : 0,
              color: "var(--label)",
              cursor: "pointer",
              textAlign: "left",
              font: "inherit",
              fontSize: 13.5,
            }}
          >
            ＋ New project…
          </button>
        </div>
      )}
      <CreateProjectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(root) => {
          setModalOpen(false);
          goToProject(root, { openGenesis: true });
        }}
      />
    </div>
  );
}
