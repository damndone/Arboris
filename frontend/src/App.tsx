import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useOutletContext,
  useSearchParams,
} from "react-router-dom";
import {
  ApiError,
  createProject,
  fetchRuns,
  type RunSummary,
} from "./api";
import { RunHistoryPanel } from "./runHistory";
import { RunDetailRoute } from "./runDetail";
import { RunForm } from "./runForm/RunForm";
import { ThemeProvider, ThemeToggle } from "./theme";
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

// --- RunHistoryRoute ---

function RunHistoryRoute() {
  const { projectRoot, setError } = useAppContext();
  const navigate = useNavigate();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    setError(null);
  }, [setError]);

  useEffect(() => {
    if (!projectRoot) {
      setRuns(null);
      return;
    }
    let cancelled = false;
    setRuns(null);
    fetchRuns(projectRoot)
      .then((res) => {
        if (!cancelled) setRuns(res.runs);
      })
      .catch((error) => {
        if (cancelled) return;
        const message =
          error instanceof ApiError
            ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
            : error instanceof Error
              ? error.message
              : "Failed to load runs";
        setError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, setError]);

  if (!projectRoot) {
    return (
      <section className="panel">
        <p className="muted">Select a project first.</p>
      </section>
    );
  }

  // V1.5.0.1 HF3: clicking a run row navigates to /runs/:id?tab=overview
  // instead of inline-rendering RunResultView below the list. This
  // unifies the entry path with the post-run flow (HF1's "Open Lineage"
  // button also lands on /runs/:id), and it lets the user reach the
  // Lineage tab — which the inline-render pattern did not.
  return (
    <section className="panel" aria-labelledby="history-heading">
      <div className="panel-heading">
        <h2 id="history-heading">Run history</h2>
        <span>{projectRoot}</span>
      </div>
      <RunHistoryPanel
        runs={runs}
        onSelect={(runId) => {
          const params = new URLSearchParams({
            project_root: projectRoot,
            tab: "overview",
          });
          navigate(`/runs/${runId}?${params.toString()}`);
        }}
      />
    </section>
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

  const historyUrl = projectRoot
    ? `/runs?project_root=${encodeURIComponent(projectRoot)}`
    : "/runs";

  const isSubmitActive = location.pathname === "/";
  const isHistoryActive = location.pathname.startsWith("/runs");
  // V1.5.0.1 HF2: dark shell is scoped to /runs/:id?tab=lineage,
  // not the whole run-detail route. The V1.5.0 P1 implementation
  // applied dark chrome to the entire /runs/:id route, which left
  // the Overview tab — using V1.4 light .panel/.result-panel styles
  // — with white text on white backgrounds (functionally unreadable).
  // Scoping to the lineage tab means Overview returns to its native
  // V1.4 light styling while Lineage retains the V1.5.0 dark
  // editorial surface. Submit (/) and History (/runs) remain light.
  const tabParam = searchParams.get("tab") ?? "overview";
  const isLineageDarkScope =
    /^\/runs\/[^/?#]+$/.test(location.pathname) && tabParam === "lineage";

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
          aria-selected={isSubmitActive}
          onClick={() => navigate("/")}
        >
          Submit
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={isHistoryActive}
          disabled={!projectRoot}
          onClick={() => {
            navigate(historyUrl);
            setErrorMessage(null);
          }}
        >
          History
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
          <Route index element={<SubmitRoute />} />
          <Route path="runs" element={<RunHistoryRoute />} />
          <Route path="runs/:runId" element={<RunDetailRoute />} />
        </Route>
      </Routes>
    </ThemeProvider>
  );
}
