// v1.6.8 route inversion — `/` is the Launcher, not the Submit form.
// T10: recent-projects grid (localStorage, see recents.ts) + create-project
// modal (CreateProjectModal, reused by T11's topbar switcher).
//
// Opening a recent probes the backend first (fetchRuns) so a deleted/moved
// project marks the card stale with a remove affordance instead of navigating
// into a dead graph.

import { useState } from "react";
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

  // v1.6.12 (V10): `/` jumps straight into the last project and `?home=1`
  // aliases the in-workbench Home view. Fresh users (no recents) still land
  // on the launcher so they can create their first project.
  const lastProject = recents[0];
  if (lastProject) {
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
