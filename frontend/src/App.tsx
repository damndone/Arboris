import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import {
  ApiError,
  createProject,
  fetchRuns,
} from "./api";
import { RunForm } from "./runForm/RunForm";
import { RunDetailRoute } from "./runDetail";
import { ThemeProvider, ThemeToggle } from "./theme";
import { DraftGraphRoute } from "./pipelineDrafts/DraftGraphRoute";
import { LauncherRoute } from "./launcher/LauncherRoute";
import { WorkbenchRouteContainer } from "./workbench/WorkbenchRouteContainer";
import { rootToSlug, slugToRoot } from "./workbench/projectSlug";
import "./styles.css";

type RequestState = "idle" | "working";

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
      return "个体列与时间列不能是同一列 (entity == time)。";
    }
    if (!s.entity && !s.time && !s.isPanelData) {
      return "选择 Panel OLS 时请指定个体或时间列；该数据未被识别为面板数据。";
    }
  }
  if (s.predictionEnabled && !s.predictionModelType) {
    return "已开启预测，请选择算法 (algorithm)。";
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
};

function useAppContext(): AppContextValue {
  return useOutletContext<AppContextValue>();
}

// --- SubmitRoute ---

function SubmitRoute() {
  const { projectRoot, setProjectRoot, setError, setActivity, activity } =
    useAppContext();

  const [parent, setParent] = useState("");
  const [name, setName] = useState("demo");
  // V1.5.4.3: `requestState` stays lifted here because it is shared chrome
  // between the Project panel (onCreateProject) and the RunForm (onRun) —
  // each disables the other's submit button while either request is in
  // flight. Passed into RunForm to preserve that cross-disabling behavior.
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const folderInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setError(null);
  }, [setError]);

  const projectErrors: Record<string, string> = {};
  if (parent.trim() === "") projectErrors.parent = "Required";
  if (name.trim() === "") projectErrors.name = "Required";
  else if (name.includes("/") || name.includes("\\"))
    projectErrors.name = "No path separators";

  const canCreate =
    Object.keys(projectErrors).length === 0 && requestState === "idle";

  async function onCreateProject() {
    setRequestState("working");
    setError(null);
    setActivity("Creating project");
    try {
      const result = await createProject(parent.trim(), name.trim());
      setProjectRoot(result.project_root);
      setActivity("Project ready");
    } catch (error) {
      const message =
        error instanceof ApiError
          ? `[HTTP ${error.status}] ${error.message}`
          : error instanceof Error
            ? error.message
            : "Project creation failed";
      setError(message);
      setActivity("Project creation failed");
    } finally {
      setRequestState("idle");
    }
  }

  function onFolderFiles(files: FileList | null) {
    const first = files?.[0] as (File & { webkitRelativePath?: string }) | undefined;
    const relativePath = first?.webkitRelativePath;
    if (!relativePath) return;
    const rootName = relativePath.split("/")[0];
    if (rootName) setParent(parent ? parent : `/${rootName}`);
  }

  return (
    <>
      <section className="panel" aria-labelledby="project-heading">
        <div className="panel-heading">
          <h2 id="project-heading">Project</h2>
          <span>Parent folder + name → backend creates project_root.</span>
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
          <button
            type="button"
            disabled={!canCreate}
            onClick={onCreateProject}
          >
            {requestState === "working" && activity === "Creating project"
              ? "Creating…"
              : "Create project"}
          </button>
        </div>
        <dl className="summary-list">
          <div>
            <dt>Project root</dt>
            <dd className="mono">{projectRoot || "Not created"}</dd>
          </div>
        </dl>
      </section>

      <RunForm
        projectRoot={projectRoot}
        setError={setError}
        setActivity={setActivity}
        activity={activity}
        requestState={requestState}
        setRequestState={setRequestState}
      />
    </>
  );
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
  // ?run= is the run deep-link param. ?focus= belongs to the workbench URL
  // schema (NODE focus key, rewritten on every canvas interaction) — never
  // read it here.
  const runParam = searchParams.get("run") ?? "";

  // T9 bridge: the workbench container still needs a runId until T11
  // decouples it. Resolve one: ?run= wins; otherwise the newest run.
  // Zero runs → placeholder (T11 replaces it with the real empty canvas).
  const [resolvedRunId, setResolvedRunId] = useState<string | null>(
    runParam || null
  );
  const [resolving, setResolving] = useState(!runParam);
  const [zeroRuns, setZeroRuns] = useState(false);

  useEffect(() => {
    if (runParam) {
      setResolvedRunId(runParam);
      setResolving(false);
      setZeroRuns(false);
      return;
    }
    if (resolvedRunId) return; // already resolved once; canvas owns the URL now
    let cancelled = false;
    setResolving(true);
    fetchRuns(projectRoot)
      .then((res) => {
        if (cancelled) return;
        const runs = res?.runs ?? [];
        if (runs.length === 0) {
          setZeroRuns(true);
          setResolvedRunId(null);
          return;
        }
        const newest = [...runs].sort((a, b) =>
          (b.started_at ?? "").localeCompare(a.started_at ?? "")
        )[0];
        setZeroRuns(false);
        setResolvedRunId(newest.run_id);
      })
      .catch(() => {
        if (!cancelled) setZeroRuns(true);
      })
      .finally(() => {
        if (!cancelled) setResolving(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectRoot, runParam]);
  if (resolving) {
    return (
      <section className="panel" data-testid="project-graph-route">
        <p className="muted">Loading project…</p>
      </section>
    );
  }
  if (zeroRuns || !resolvedRunId) {
    return (
      <section className="panel" data-testid="project-graph-route">
        <div className="panel-heading">
          <h2>Graph workbench</h2>
          <span className="mono">{projectRoot}</span>
        </div>
        <p className="muted">此项目还没有 run——图内创世向导将在这里开始。</p>
      </section>
    );
  }
  return (
    <div data-testid="project-graph-route">
      <WorkbenchRouteContainer projectRoot={projectRoot} runId={resolvedRunId} />
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

  const context = useMemo<AppContextValue>(
    () => ({ projectRoot, setProjectRoot, setError, setActivity, activity }),
    [projectRoot, setProjectRoot, setError, activity]
  );

  const isLauncherActive = location.pathname === "/";
  const isWorkbenchActive = /^\/p\/[^/]+\/graph\/?$/.test(location.pathname);
  // V1.5.0.1 HF2 scoped the dark shell to /runs/:id?tab=lineage so the
  // light Overview tab stayed readable. v1.6.8: /runs/:id is now a
  // redirect and the workbench home is /p/:slug/graph — the dark canvas
  // scope moves there. Launcher (/) and /submit remain light.
  const isLineageDarkScope = isWorkbenchActive;

  return (
    <main
      className={`workbench-shell${isLineageDarkScope ? " workbench-shell--lineage" : ""}`}
    >
      <header className="workbench-header">
        <h1>Local Econometrics Workbench</h1>
        <div className="workbench-header__right">
          <span className="activity" aria-live="polite">
            {activity}
          </span>
          <ThemeToggle />
        </div>
      </header>

      {errorMessage && (
        <section className="panel panel-error" role="alert">
          <strong>Request error</strong>
          <p>{errorMessage}</p>
        </section>
      )}

      <nav className="tabs" role="tablist" aria-label="workbench views">
        <button
          type="button"
          role="tab"
          aria-selected={isLauncherActive}
          onClick={() => navigate("/")}
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

      <Outlet context={context} />
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
          <Route path="submit" element={<SubmitRoute />} />
          <Route path="p/:slug/graph" element={<ProjectGraphRoute />} />
          <Route path="runs" element={<LegacyRunsListRedirect />} />
          <Route path="runs/:runId" element={<LegacyRunRoute />} />
          <Route path="pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
        </Route>
      </Routes>
    </ThemeProvider>
  );
}
