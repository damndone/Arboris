// v1.6.8 route inversion — `/` is the Launcher, not the Submit form.
// T10: recent-projects grid (localStorage, see recents.ts) + create-project
// modal (CreateProjectModal, reused by T11's topbar switcher).
//
// Opening a recent probes the backend first (fetchRuns) so a deleted/moved
// project marks the card 失效 with a 移除 affordance instead of navigating
// into a dead graph.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, fetchRuns } from "../api";
import { rootToSlug } from "../workbench/projectSlug";
import { CreateProjectModal } from "./CreateProjectModal";
import { listRecents, removeRecent, touchRecent } from "./recents";
import type { RecentProject } from "./recents";

function projectName(root: string): string {
  return root.split("/").filter(Boolean).pop() ?? root;
}

export function LauncherRoute() {
  const navigate = useNavigate();
  const [recents, setRecents] = useState<RecentProject[]>(() => listRecents());
  const [staleRoots, setStaleRoots] = useState<Record<string, boolean>>({});
  const [probingRoot, setProbingRoot] = useState<string | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  function goToProject(root: string, opts: { openGenesis?: boolean } = {}) {
    touchRecent(root);
    const suffix = opts.openGenesis ? "?genesis=1" : "";
    navigate(`/p/${rootToSlug(root)}/graph${suffix}`);
  }

  async function openRecent(root: string) {
    // T11 R1: guard concurrent probes — a second click (same or another
    // card) while one probe is in flight is ignored.
    if (probingRoot) return;
    setProbingRoot(root);
    setProbeError(null);
    // T11 R2: navigate AFTER the finally block, so goToProject (which
    // unmounts this route) is not followed by a setState-after-unmount.
    let probeOk = false;
    try {
      await fetchRuns(root);
      probeOk = true;
    } catch (err) {
      if (err instanceof ApiError && err.code === "PROJECT_NOT_FOUND") {
        setStaleRoots((s) => ({ ...s, [root]: true }));
      } else {
        setProbeError(
          err instanceof Error ? err.message : "无法打开项目，请稍后再试。"
        );
      }
    } finally {
      setProbingRoot(null);
    }
    if (probeOk) goToProject(root);
  }

  function onRemove(root: string) {
    removeRecent(root);
    setRecents(listRecents());
    setStaleRoots((s) => {
      const next = { ...s };
      delete next[root];
      return next;
    });
  }

  return (
    <section className="panel" aria-labelledby="launcher-heading">
      <div className="panel-heading">
        <h2 id="launcher-heading">Econometrics Workbench</h2>
        <span>选择或新建一个项目开始。</span>
      </div>
      <button type="button" onClick={() => setModalOpen(true)}>
        新建项目
      </button>
      {probeError && (
        <p className="field-error" role="alert">
          {probeError}
        </p>
      )}
      {recents.length === 0 ? (
        <p className="muted">最近项目将显示在这里。</p>
      ) : (
        <ul
          aria-label="recent projects"
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
                  onClick={() => openRecent(recent.root)}
                  disabled={stale || probingRoot === recent.root}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                  }}
                >
                  <strong>{projectName(recent.root)}</strong>
                  <span className="mono" style={{ display: "block" }}>
                    {recent.root}
                  </span>
                  <span className="muted" style={{ display: "block" }}>
                    {probingRoot === recent.root
                      ? "打开中…"
                      : `上次打开 ${recent.lastOpened}`}
                  </span>
                </button>
                {stale && (
                  <p className="field-error" style={{ margin: "8px 0 0" }}>
                    失效
                    <button
                      type="button"
                      onClick={() => onRemove(recent.root)}
                      style={{ marginLeft: 8 }}
                    >
                      移除
                    </button>
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <CreateProjectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(projectRoot) => {
          setModalOpen(false);
          goToProject(projectRoot, { openGenesis: true });
        }}
      />
    </section>
  );
}
