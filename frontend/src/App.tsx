import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Link,
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
  runWorkflow,
  type RunResponse,
  type RunSummary,
} from "./api";
import { RunHistoryPanel } from "./runHistory";
import { RunDetailPanel } from "./runDetail";
import "./styles.css";

type RequestState = "idle" | "working";

const RUN_OUTPUT_PATHS = [
  "run_manifest.json",
  "artifacts_index.json",
  "errors.json",
  "reports/report.html",
  "reports/report.pdf",
  "exports/tables.xlsx",
];

function joinPath(base: string, suffix: string): string {
  if (!base) return suffix;
  const trimmed = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${trimmed}/${suffix}`;
}

function parseColumns(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

function statusLabel(status: string): string {
  if (!status) return "—";
  return status.charAt(0).toUpperCase() + status.slice(1);
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
  const navigate = useNavigate();

  const [parent, setParent] = useState("");
  const [name, setName] = useState("demo");
  const [mode, setMode] = useState("auto");
  const [y, setY] = useState("");
  const [x, setX] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);

  useEffect(() => {
    setError(null);
  }, [setError]);

  const xColumns = useMemo(() => parseColumns(x), [x]);

  const projectErrors: Record<string, string> = {};
  if (parent.trim() === "") projectErrors.parent = "Required";
  if (name.trim() === "") projectErrors.name = "Required";
  else if (name.includes("/") || name.includes("\\"))
    projectErrors.name = "No path separators";

  const runErrors: Record<string, string> = {};
  if (projectRoot.trim() === "") runErrors.projectRoot = "Create a project first";
  if (y.trim() === "") runErrors.y = "Required";
  if (xColumns.length === 0) runErrors.x = "Provide at least one column";
  if (!file) runErrors.file = "Select a CSV file";

  const canCreate =
    Object.keys(projectErrors).length === 0 && requestState === "idle";
  const canRun =
    Object.keys(runErrors).length === 0 && requestState === "idle";

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

  async function onRun() {
    if (!file) return;
    setRequestState("working");
    setError(null);
    setActivity("Running workflow");
    try {
      const result = await runWorkflow(
        projectRoot.trim(),
        mode,
        y.trim(),
        xColumns.join(","),
        file
      );
      setLastRun(result);
      setActivity(
        result.status === "blocked"
          ? "Workflow returned blocked"
          : "Workflow completed"
      );
      navigate(
        `/runs/${encodeURIComponent(result.run_id)}?project_root=${encodeURIComponent(projectRoot)}`
      );
    } catch (error) {
      const message =
        error instanceof ApiError
          ? `[HTTP ${error.status}] ${error.message}`
          : error instanceof Error
            ? error.message
            : "Workflow request failed";
      setError(message);
      setActivity("Workflow request failed");
    } finally {
      setRequestState("idle");
    }
  }

  const runDir = lastRun
    ? joinPath(projectRoot, `runs/${lastRun.run_id}`)
    : null;
  const badgeClass = lastRun
    ? `badge badge-${lastRun.status === "completed" ? "ok" : lastRun.status === "blocked" ? "warn" : "neutral"}`
    : "badge badge-neutral";

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

      <section className="panel" aria-labelledby="run-heading">
        <div className="panel-heading">
          <h2 id="run-heading">Run</h2>
          <span>Upload one CSV; configure model; submit workflow.</span>
        </div>
        <div className="control-grid run-grid">
          <label>
            Mode
            <select
              aria-label="run mode"
              value={mode}
              onChange={(event) => setMode(event.target.value)}
            >
              <option value="auto">Auto</option>
              <option value="stepped">Stepped</option>
            </select>
          </label>
          <label>
            Dependent variable (y)
            <input
              aria-label="dependent variable"
              aria-invalid={Boolean(runErrors.y)}
              placeholder="y"
              value={y}
              onChange={(event) => setY(event.target.value)}
            />
            {runErrors.y && <span className="field-error">{runErrors.y}</span>}
          </label>
          <label>
            Regressors (x, comma-separated)
            <input
              aria-label="independent variables"
              aria-invalid={Boolean(runErrors.x)}
              placeholder="x1, x2"
              value={x}
              onChange={(event) => setX(event.target.value)}
            />
            <span className={runErrors.x ? "field-error" : "field-hint"}>
              {runErrors.x ?? `${xColumns.length} column${xColumns.length === 1 ? "" : "s"}`}
            </span>
          </label>
          <label>
            Data file (.csv)
            <input
              aria-label="data file"
              aria-invalid={Boolean(runErrors.file)}
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            {file && (
              <span className="field-hint">
                {file.name} · {(file.size / 1024).toFixed(1)} KB
              </span>
            )}
            {runErrors.file && (
              <span className="field-error">{runErrors.file}</span>
            )}
          </label>
          <button type="button" disabled={!canRun} onClick={onRun}>
            {requestState === "working" && activity === "Running workflow"
              ? "Running…"
              : "Run workflow"}
          </button>
        </div>
        {runErrors.projectRoot && (
          <p className="field-error inline-error">{runErrors.projectRoot}</p>
        )}
      </section>

      <section className="panel" aria-labelledby="result-heading">
        <div className="panel-heading">
          <h2 id="result-heading">Last run</h2>
          <span>
            {lastRun
              ? "Outputs are written under the run directory."
              : "No run yet."}
          </span>
        </div>
        {lastRun ? (
          <>
            <dl className="summary-list">
              <div>
                <dt>Run ID</dt>
                <dd className="mono">{lastRun.run_id}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>
                  <span className={badgeClass}>
                    {statusLabel(lastRun.status)}
                  </span>
                  {lastRun.status === "blocked" && (
                    <span className="status-hint">
                      Workflow blocked — inspect <code>errors.json</code>.
                    </span>
                  )}
                </dd>
              </div>
              <div>
                <dt>Project root</dt>
                <dd className="mono">{projectRoot}</dd>
              </div>
              <div>
                <dt>Run directory</dt>
                <dd className="mono">{runDir}</dd>
              </div>
            </dl>
            <h3 className="subhead">Expected outputs</h3>
            <ul className="path-list" aria-label="expected outputs">
              {RUN_OUTPUT_PATHS.map((suffix) => (
                <li key={suffix} className="mono">
                  {joinPath(runDir ?? "", suffix)}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted">
            Submit a workflow to see run details and output paths.
          </p>
        )}
      </section>
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

  const handleSelect = (runId: string) => {
    navigate(
      `/runs/${encodeURIComponent(runId)}?project_root=${encodeURIComponent(projectRoot)}`
    );
  };

  return (
    <section className="panel" aria-labelledby="history-heading">
      <div className="panel-heading">
        <h2 id="history-heading">Run history</h2>
        <span>{projectRoot}</span>
      </div>
      <RunHistoryPanel runs={runs} onSelect={handleSelect} />
    </section>
  );
}

// --- RunDetailRoute ---

function RunDetailRoute() {
  const { projectRoot, setError } = useAppContext();
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();

  useEffect(() => {
    setError(null);
  }, [setError]);

  if (!projectRoot) {
    return (
      <section className="panel panel-error">
        <strong>Missing project_root</strong>
        <p>
          Cannot view run detail without a project.{" "}
          <Link to="/">Return to submit</Link>
        </p>
      </section>
    );
  }

  return (
    <RunDetailPanel
      projectRoot={projectRoot}
      runId={runId!}
      onBack={() =>
        navigate(
          `/runs?project_root=${encodeURIComponent(projectRoot)}`
        )
      }
      onError={setError}
    />
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

  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <h1>Local Econometrics Workbench</h1>
        <span className="activity" aria-live="polite">
          {activity}
        </span>
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
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<SubmitRoute />} />
        <Route path="runs" element={<RunHistoryRoute />} />
        <Route path="runs/:runId" element={<RunDetailRoute />} />
      </Route>
    </Routes>
  );
}
