// v1.9.0 — a project with no runs yet, in the workspace. The same top bar as
// every other page; the body says what to do first (import data) instead of
// an empty canvas. Project home and Plans open here too, before any run.

import { useNavigate } from "react-router-dom";
import type { NotebookMaterializationResponse } from "../notebook/notebookApi";
import { NotebookRouteView } from "../notebook/NotebookRouteView";
import { WorkbenchHomeView } from "../workbench/views/WorkbenchHomeView";
import { rootToSlug } from "../workbench/projectSlug";
import type { ViewMode } from "../workbench/state/urlSchema";
import { PlusIcon } from "./icons";
import { WorkspaceTopbar } from "./WorkspaceTopbar";

const NEEDS_DATA = "Import data first";

export interface WorkspaceProjectStartProps {
  projectRoot: string;
  /** The `view` URL parameter: "home", "notebook", or anything else for the start page. */
  view: string | null;
  legacyFamilyCount: number;
  legacyRunCount: number;
  onOpenWizard: () => void;
  onOpenSettings: () => void;
  notebookActiveRunId: string | null;
  onMaterializedDraft: (response: NotebookMaterializationResponse) => void;
}

export function WorkspaceProjectStart({
  projectRoot,
  view,
  legacyFamilyCount,
  legacyRunCount,
  onOpenWizard,
  onOpenSettings,
  notebookActiveRunId,
  onMaterializedDraft,
}: WorkspaceProjectStartProps) {
  const navigate = useNavigate();
  const path = typeof window === "undefined" ? "" : window.location.pathname;
  const current: ViewMode = view === "home" ? "home" : view === "notebook" ? "notebook" : "graph";
  const go = (next: ViewMode) => navigate(next === "graph" ? path : `${path}?view=${next}`);
  const legacyRuns = legacyRunCount > 0 ? legacyRunCount : legacyFamilyCount;

  return (
    <div className="ws-page" data-testid="workspace-project-start">
      <header className="ws-topbar" role="banner">
        <WorkspaceTopbar
          projectRoot={projectRoot}
          view={current}
          actions={null}
          disabledViews={{ data: NEEDS_DATA, table: NEEDS_DATA, report: NEEDS_DATA }}
          onView={go}
          onHome={() => go("home")}
          onOpenSettings={onOpenSettings}
          onNewAnalysis={onOpenWizard}
        />
      </header>
      <main className="ws-page__body" aria-label={current === "home" ? "Project home" : current === "notebook" ? "Plans" : "Start"}>
        {current === "home" ? (
          <WorkbenchHomeView
            projectRoot={projectRoot}
            onOpenSettings={onOpenSettings}
            onOpenProject={(root) => navigate(`/p/${rootToSlug(root)}/graph`)}
          />
        ) : current === "notebook" ? (
          <NotebookRouteView
            projectRoot={projectRoot}
            activeRunId={notebookActiveRunId}
            onOpenMemorySettings={onOpenSettings}
            onMaterializedDraft={onMaterializedDraft}
          />
        ) : (
          <section className="ws-start" aria-labelledby="ws-start-title">
            <h1 id="ws-start-title" className="ws-start__title">Start with your data</h1>
            <p className="ws-start__lead">
              Import a CSV, SPSS or Stata file. Every step after that, from cleaning to models and tests, appears on the map.
            </p>
            <div className="ws-start__actions">
              <button type="button" className="ws-button ws-button--primary ws-start__primary" data-testid="genesis-cta" onClick={onOpenWizard}>
                <PlusIcon />
                Import data
              </button>
              <button type="button" className="ws-button" onClick={() => go("notebook")}>
                Plan the analysis first
              </button>
            </div>
            {legacyFamilyCount > 0 && (
              <p className="ws-start__note">
                {legacyRuns} earlier run{legacyRuns === 1 ? "" : "s"} predate lineage indexing and cannot be shown on the map.
                Their results stay available on each run's page.
              </p>
            )}
            <p className="ws-start__path" title={projectRoot}>{projectRoot}</p>
          </section>
        )}
      </main>
    </div>
  );
}
