import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useOutletContext,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { RunDetailRoute } from "./runDetail";
import { ThemeProvider, ThemeToggle } from "./theme";
import { DraftGraphRoute } from "./pipelineDrafts/DraftGraphRoute";
import { LauncherRoute } from "./launcher/LauncherRoute";
import { WorkbenchHome } from "./workbench/WorkbenchRouteContainer";
import { rootToSlug, slugToRoot } from "./workbench/projectSlug";
import "./styles.css";

export function validatePanelPrediction(s: {
  modelType: string;
  entity: string;
  time: string;
  isPanelData: boolean;
  predictionEnabled: boolean;
  predictionModelType: string;
}): string | null {
  if (s.modelType === "panel_ols") {
    if (s.entity && s.time && s.entity === s.time) {
      return "The entity and time columns cannot be the same column (entity == time).";
    }
    if (!s.entity && !s.time && !s.isPanelData) {
      return "Panel OLS needs an entity or time column; this dataset was not recognised as panel data.";
    }
  }
  if (s.predictionEnabled && !s.predictionModelType) {
    return "Prediction is enabled — choose an algorithm.";
  }
  return null;
}

// --- Context ---

type AppContextValue = {
  projectRoot: string;
  setProjectRoot: (root: string) => void;
  setError: (msg: string | null) => void;
  setActivity: (text: string) => void;
  activity: string;
  settingsRequestVersion: number;
  requestOpenSettings: () => void;
};

function useAppContext(): AppContextValue {
  return useOutletContext<AppContextValue>();
}

// --- v1.6.8 route inversion: legacy redirects + project graph home ---
// The graph is the home; /runs* deep links keep working via redirects
// (spec F8), and the workbench mounts at /p/:slug/graph where slug is a
// base64url-encoded project_root (spec F5 — no %2F in path segments).

function LegacyRunRoute() {
  const { runId } = useParams();
  const [searchParams] = useSearchParams();
  const root = searchParams.get("project_root");
  // v1.6.8: Overview (artifacts / report iframe / full coefficient tables)
  // has no workbench equivalent yet — keep it reachable at the explicit
  // ?tab=overview deep link (same off-nav philosophy as /submit) so no
  // feature goes dead. Everything else redirects into the graph home.
  if (searchParams.get("tab") === "overview") return <RunDetailRoute />;
  if (!root) return <Navigate to="/" replace />;
  // Forward the run id as ?run= — NOT ?focus=, which the workbench URL
  // schema owns as the NODE focus key (urlSchema.ts). Preserve all other
  // params (e.g. ?view=table survives the v1.6.7 run-aware Table flow).
  const forwarded = new URLSearchParams(searchParams);
  forwarded.delete("project_root");
  forwarded.delete("tab");
  forwarded.set("run", runId ?? "");
  return (
    <Navigate replace to={`/p/${rootToSlug(root)}/graph?${forwarded.toString()}`} />
  );
}

function LegacyRunsListRedirect() {
  const [searchParams] = useSearchParams();
  const root = searchParams.get("project_root");
  return <Navigate replace to={root ? `/p/${rootToSlug(root)}/graph` : "/"} />;
}

function SubmitRedirect() {
  const [searchParams] = useSearchParams();
  const root = searchParams.get("project_root");
  return (
    <Navigate
      replace
      to={root ? `/p/${rootToSlug(root)}/graph?open_genesis=1` : "/"}
      state={root ? { openGenesis: true } : undefined}
    />
  );
}

function ProjectGraphRoute() {
  const { slug } = useParams();

  let projectRoot = "";
  try {
    projectRoot = slugToRoot(slug ?? "");
  } catch {
    // malformed slug — fall through to the launcher redirect below
  }
  if (!projectRoot) return <Navigate to="/" replace />;
  // key by slug: switching /p/A/graph → /p/B/graph must remount the bridge,
  // otherwise B's first frame renders with A's resolved run (stale fetch).
  return <ProjectGraphBridge key={slug} projectRoot={projectRoot} />;
}

function ProjectGraphBridge({ projectRoot }: { projectRoot: string }) {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const { settingsRequestVersion } = useAppContext();
  const routeState =
    location.state && typeof location.state === "object"
      ? (location.state as { openGenesis?: unknown })
      : null;
  const openGenesis =
    searchParams.get("genesis") === "1" ||
    searchParams.get("open_genesis") === "1" ||
    routeState?.openGenesis === true;
  // ?run= is the run deep-link param. ?focus= belongs to the workbench URL
  // schema (NODE focus key, rewritten on every canvas interaction) — never
  // read it here.
  //
  // T11: the container is project-keyed now — it owns run resolution
  // (newest head), the loading/error branches, and the zero-run empty
  // canvas. The bridge only decodes the deep link.
  const runParam = searchParams.get("run") ?? "";

  return (
    <div data-testid="project-graph-route">
      <WorkbenchHome
        projectRoot={projectRoot}
        focusRunId={runParam || undefined}
        openGenesis={openGenesis}
        settingsRequestVersion={settingsRequestVersion}
      />
    </div>
  );
}

// --- AppShell ---

function AppShell() {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();

  const [projectRoot, setProjectRootState] = useState<string>(() => {
    const fromUrl = searchParams.get("project_root");
    if (fromUrl) return fromUrl;
    try {
      return localStorage.getItem("lastProjectRoot") ?? "";
    } catch {
      return "";
    }
  });

  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activity, setActivity] = useState<string>("Idle");
  const [settingsRequestVersion, setSettingsRequestVersion] = useState(0);

  useEffect(() => {
    const fromUrl = searchParams.get("project_root");
    if (fromUrl && fromUrl !== projectRoot) {
      setProjectRootState(fromUrl);
    }
  }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

  // v1.6.8: on /p/:slug/graph the slug IS the project identity — sync it
  // into shell state (and localStorage) so the topbar and other consumers
  // agree with the URL.
  useEffect(() => {
    const match = location.pathname.match(/^\/p\/([^/]+)\/graph\/?$/);
    if (!match) return;
    try {
      const fromSlug = slugToRoot(match[1]);
      if (fromSlug && fromSlug !== projectRoot) {
        setProjectRootState(fromSlug);
        try {
          localStorage.setItem("lastProjectRoot", fromSlug);
        } catch {
          // ignore
        }
      }
    } catch {
      // malformed slug — ProjectGraphRoute redirects to the launcher
    }
  }, [location.pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  const setProjectRoot = useCallback((root: string) => {
    setProjectRootState(root);
    try {
      localStorage.setItem("lastProjectRoot", root);
    } catch {
      // ignore
    }
  }, []);

  const setError = useCallback((msg: string | null) => {
    setErrorMessage(msg);
  }, []);

  const requestOpenSettings = useCallback(() => {
    setSettingsRequestVersion((version) => version + 1);
  }, []);

  const context = useMemo<AppContextValue>(
    () => ({
      projectRoot,
      setProjectRoot,
      setError,
      setActivity,
      activity,
      settingsRequestVersion,
      requestOpenSettings,
    }),
    [
      projectRoot,
      setProjectRoot,
      setError,
      activity,
      settingsRequestVersion,
      requestOpenSettings,
    ]
  );

  const isProjectGraphRoute = /^\/p\/[^/]+\/graph\/?$/.test(location.pathname);
  const isLauncherActive = location.pathname === "/";
  const isProjectHomeActive =
    isLauncherActive || (isProjectGraphRoute && searchParams.get("view") === "home");
  const isWorkbenchActive = isProjectGraphRoute && !isProjectHomeActive;
  // Every project graph view, including project Home, owns the full-height
  // Workbench canvas. The outer Home/Workbench selection changes navigation
  // state, not the layout contract of the project route.
  const isLineageDarkScope = isProjectGraphRoute;

  return (
    <main
      className={`workbench-shell${isLineageDarkScope ? " workbench-shell--lineage" : ""}`}
    >
      {errorMessage && (
        <section className="panel panel-error" role="alert">
          <strong>Request error</strong>
          <p>{errorMessage}</p>
        </section>
      )}

      <div className="workbench-navigation-row">
        <nav className="tabs" role="tablist" aria-label="workbench views">
          <button
            type="button"
            role="tab"
            aria-selected={isProjectHomeActive}
            onClick={() => {
              if (isProjectGraphRoute && projectRoot && !errorMessage) {
                navigate(`/p/${rootToSlug(projectRoot)}/graph?view=home`);
              } else {
                navigate("/");
              }
            }}
          >
            Home
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={isWorkbenchActive}
            disabled={!projectRoot}
            onClick={() => {
              navigate(`/p/${rootToSlug(projectRoot)}/graph`);
              setErrorMessage(null);
            }}
          >
            Workbench
          </button>
        </nav>
        <div className="workbench-navigation-actions">
          {activity !== "Idle" && (
            <span className="activity" aria-live="polite">
              {activity}
            </span>
          )}
          {isProjectGraphRoute && (
            <button
              type="button"
              className="workbench-settings-button"
              aria-label="Settings"
              title="Settings"
              data-testid="workbench-shell-settings"
              onClick={requestOpenSettings}
            >
              <span aria-hidden="true">⚙</span>
            </button>
          )}
          <ThemeToggle />
        </div>
      </div>

      <div className="workbench-outlet">
        <Outlet context={context} />
      </div>
    </main>
  );
}

// --- App (router root) ---

export default function App() {
  // V1.5.1 T6 — ThemeProvider lives here (not main.tsx) so App.test.tsx
  // and any other consumer that renders <App /> directly gets the theme
  // context for free. main.tsx no longer wraps to avoid a double-listener.
  return (
    <ThemeProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<LauncherRoute />} />
          <Route path="submit" element={<SubmitRedirect />} />
          <Route path="p/:slug/graph" element={<ProjectGraphRoute />} />
          <Route path="runs" element={<LegacyRunsListRedirect />} />
          <Route path="runs/:runId" element={<LegacyRunRoute />} />
          <Route path="pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
        </Route>
      </Routes>
    </ThemeProvider>
  );
}
