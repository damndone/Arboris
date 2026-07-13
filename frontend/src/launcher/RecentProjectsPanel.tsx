import { useState } from "react";
import { ApiError, fetchRuns } from "../api";
import { listRecents, removeRecent, touchRecent } from "./recents";
import type { RecentProject } from "./recents";

export interface RecentProjectsPanelProps {
  onOpenProject: (root: string) => void;
}

function projectName(root: string): string {
  return root.split("/").filter(Boolean).pop() ?? root;
}

export function RecentProjectsPanel({ onOpenProject }: RecentProjectsPanelProps) {
  const [recents, setRecents] = useState<RecentProject[]>(() => listRecents());
  const [staleRoots, setStaleRoots] = useState<Record<string, boolean>>({});
  const [probingRoot, setProbingRoot] = useState<string | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);

  async function openRecent(root: string) {
    if (probingRoot) return;
    setProbingRoot(root);
    setProbeError(null);
    let probeOk = false;
    try {
      await fetchRuns(root);
      probeOk = true;
    } catch (error) {
      if (error instanceof ApiError && error.code === "PROJECT_NOT_FOUND") {
        setStaleRoots((current) => ({ ...current, [root]: true }));
      } else {
        setProbeError(error instanceof Error ? error.message : "无法打开项目，请稍后再试。");
      }
    } finally {
      setProbingRoot(null);
    }
    if (probeOk) {
      touchRecent(root);
      onOpenProject(root);
    }
  }

  function remove(root: string) {
    removeRecent(root);
    setRecents(listRecents());
    setStaleRoots((current) => {
      const next = { ...current };
      delete next[root];
      return next;
    });
  }

  return (
    <>
      {probeError && <p className="field-error" role="alert">{probeError}</p>}
      {recents.length === 0 ? (
        <p className="muted">最近项目将显示在这里。</p>
      ) : (
        <ul
          aria-label="recent projects"
          data-testid="recent-projects-panel"
          style={{
            listStyle: "none",
            margin: "16px 0 0",
            padding: 0,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 12,
          }}
        >
          {recents.map((recent) => {
            const stale = Boolean(staleRoots[recent.root]);
            return (
              <li key={recent.root} className="panel" style={{ margin: 0 }}>
                <button
                  type="button"
                  onClick={() => void openRecent(recent.root)}
                  disabled={stale || probingRoot === recent.root}
                  style={{ display: "block", width: "100%", textAlign: "left" }}
                >
                  <strong>{projectName(recent.root)}</strong>
                  <span className="mono" style={{ display: "block" }}>{recent.root}</span>
                  <span className="muted" style={{ display: "block" }}>
                    {probingRoot === recent.root ? "打开中…" : `上次打开 ${recent.lastOpened}`}
                  </span>
                </button>
                {stale && (
                  <p className="field-error" style={{ margin: "8px 0 0" }}>
                    失效
                    <button type="button" onClick={() => remove(recent.root)} style={{ marginLeft: 8 }}>
                      移除
                    </button>
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
