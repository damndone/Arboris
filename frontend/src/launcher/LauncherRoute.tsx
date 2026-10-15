// v1.6.8 route inversion — `/` is the Launcher, not the Submit form.
// T10: recent-projects grid (localStorage, see recents.ts) + create-project
// modal (CreateProjectModal, reused by T11's topbar switcher).
//
// Opening a recent probes the backend first (fetchRuns) so a deleted/moved
// project marks the card stale with a remove affordance instead of navigating
// into a dead graph.

import { useState } from "react";
import { useWorkspaceMode } from "../workspace/workspaceMode";
import { WorkspaceLauncherBar } from "../workspace/WorkspaceLauncherBar";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { rootToSlug } from "../workbench/projectSlug";
import { CreateProjectModal } from "./CreateProjectModal";
import { listRecents, touchRecent } from "./recents";
import type { RecentProject } from "./recents";
import { RecentProjectsPanel } from "./RecentProjectsPanel";

export function LauncherRoute() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [modalOpen, setModalOpen] = useState(false);
  const recents = listRecents();
  const workspaceMode = useWorkspaceMode();

  // v1.6.12 (V10): `/` jumps straight into the last project and `?home=1`
  // aliases the in-workbench Home view. Fresh users (no recents) still land
  // on the launcher so they can create their first project.
  // `?launcher=1` stays here: the way out of a project that no longer opens
  // (moved or deleted), which would otherwise be re-entered at once.
  const lastProject = recents[0];
  if (lastProject && searchParams.get("launcher") !== "1") {
    const view = searchParams.get("home") === "1" ? "?view=home" : "";
    return <Navigate replace to={`/p/${rootToSlug(lastProject.root)}/graph${view}`} />;
  }

  function goToProject(root: string, opts: { openGenesis?: boolean } = {}) {
    touchRecent(root);
    const suffix = opts.openGenesis ? "?open_genesis=1" : "";
    navigate(`/p/${rootToSlug(root)}/graph${suffix}`, {
      state: opts.openGenesis ? { openGenesis: true } : undefined,
    });
  }

  const createModal = (
    <CreateProjectModal
      open={modalOpen}
      onClose={() => setModalOpen(false)}
      onCreated={(projectRoot) => {
        setModalOpen(false);
        goToProject(projectRoot, { openGenesis: true });
      }}
    />
  );

  if (workspaceMode === "new") {
    return (
      <div className="ws-page" data-testid="workspace-launcher">
        <header className="ws-topbar" role="banner">
          <WorkspaceLauncherBar />
        </header>
        <main className="ws-launcher" aria-labelledby="launcher-heading">
          <div className="ws-launcher__head">
            <div>
              <h1 id="launcher-heading" className="ws-launcher__title">Projects</h1>
              <p className="ws-launcher__lead">Open a recent project, or start a new one with its own folder.</p>
            </div>
            <button type="button" data-variant="primary" onClick={() => setModalOpen(true)}>
              New project
            </button>
          </div>
          <RecentProjectsPanel onOpenProject={goToProject} />
        </main>
        {createModal}
      </div>
    );
  }

  return (
    <section className="panel" aria-labelledby="launcher-heading">
      <div className="panel-heading">
        <h2 id="launcher-heading">Workbench</h2>
        <span>Choose a project or create a new one to begin.</span>
      </div>
      <button type="button" onClick={() => setModalOpen(true)}>
        New project
      </button>
      <RecentProjectsPanel onOpenProject={goToProject} />
      {createModal}
    </section>
  );
}
