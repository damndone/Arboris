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
  previewFile,
  runWorkflow,
  type FilePreview,
  type RunResponse,
  type RunSummary,
} from "./api";
import { RunHistoryPanel } from "./runHistory";
import { RunDetailRoute } from "./runDetail";
import { RunResultView } from "./runResult";
import "./styles.css";

type RequestState = "idle" | "working";

function parseColumns(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "");
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
  const [mode, setMode] = useState("auto");
  const [modelType, setModelType] = useState("auto");
  const [y, setY] = useState("");
  const [x, setX] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [previewState, setPreviewState] = useState<
    "idle" | "loading" | "error"
  >("idle");
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

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
  if (!file) runErrors.file = "Select a CSV or Excel file";

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

  async function onFileChange(nextFile: File | null) {
    setFile(nextFile);
    setPreview(null);
    setPreviewError(null);
    if (!nextFile) {
      setPreviewState("idle");
      return;
    }
    setPreviewState("loading");
    try {
      const nextPreview = await previewFile(nextFile);
      setPreview(nextPreview);
      if (nextPreview.suggestedY) setY(nextPreview.suggestedY);
      setX(nextPreview.suggestedX.join(", "));
      setPreviewState("idle");
    } catch (error) {
      setPreviewState("error");
      setPreviewError(
        error instanceof Error ? error.message : "File preview failed",
      );
    }
  }

  function onFolderFiles(files: FileList | null) {
    const first = files?.[0] as (File & { webkitRelativePath?: string }) | undefined;
    const relativePath = first?.webkitRelativePath;
    if (!relativePath) return;
    const rootName = relativePath.split("/")[0];
    if (rootName) setParent(parent ? parent : `/${rootName}`);
  }

  function setXSelection(column: string, selected: boolean) {
    const next = new Set(xColumns);
    if (selected) next.add(column);
    else next.delete(column);
    setX(Array.from(next).join(", "));
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
        file,
        modelType,
      );
      setLastRun(result);
      setActivity(
        result.status === "blocked"
          ? "Workflow returned blocked"
          : "Workflow completed"
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

      <section className="panel" aria-labelledby="run-heading">
        <div className="panel-heading">
          <h2 id="run-heading">Run</h2>
          <span>Upload CSV or Excel; preview data; submit workflow.</span>
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
            Model type
            <select
              aria-label="model type"
              value={modelType}
              onChange={(event) => setModelType(event.target.value)}
            >
              <option value="auto">Auto (infer from y)</option>
              <option value="ols">OLS (linear regression)</option>
              <option value="logit">Logit (binary outcome)</option>
              <option value="poisson">Poisson (count outcome)</option>
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
            Data file (.csv, .xlsx, .xls)
            <input
              aria-label="data file"
              aria-invalid={Boolean(runErrors.file)}
              type="file"
              accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
              onChange={(event) => {
                void onFileChange(event.target.files?.[0] ?? null);
              }}
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
        {previewState === "loading" && (
          <p className="muted">Previewing file…</p>
        )}
        {previewState === "error" && previewError && (
          <p className="field-error inline-error">{previewError}</p>
        )}
        {preview && (
          <section className="preview-panel" aria-labelledby="preview-heading">
            <div className="panel-heading compact-heading">
              <h3 id="preview-heading" className="subhead">
                Data preview
              </h3>
              <span>
                {preview.fileName} · {preview.rowCount} rows ·{" "}
                {preview.columnCount} columns
              </span>
            </div>
            <div className="preview-table-wrap">
              <table className="preview-table">
                <thead>
                  <tr>
                    {preview.columns.map((column) => (
                      <th key={column.name}>{column.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.previewRows.map((row, index) => (
                    <tr key={index}>
                      {preview.columns.map((column) => (
                        <td key={column.name}>{String(row[column.name] ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="column-selector" aria-label="column selector">
              {preview.columns.map((column) => (
                <div key={column.name} className="column-option">
                  <div>
                    <strong>{column.name}</strong>
                    <span className="column-meta">
                      {column.dtype} · {column.uniqueCount} unique ·{" "}
                      {column.mean !== undefined
                        ? `mean ${column.mean.toFixed(2)} / std ${(column.std ?? 0).toFixed(2)}`
                        : `${(column.missingRate * 100).toFixed(0)}% missing`}
                    </span>
                  </div>
                  <label className="inline-choice">
                    <input
                      type="radio"
                      name="dependent-column"
                      checked={y === column.name}
                      onChange={() => setY(column.name)}
                    />
                    y
                  </label>
                  <label className="inline-choice">
                    <input
                      type="checkbox"
                      checked={xColumns.includes(column.name)}
                      disabled={y === column.name}
                      onChange={(event) =>
                        setXSelection(column.name, event.target.checked)
                      }
                    />
                    x
                  </label>
                </div>
              ))}
            </div>
          </section>
        )}
      </section>

      <section className="panel" aria-labelledby="result-heading">
        <div className="panel-heading">
          <h2 id="result-heading">Last run</h2>
          <span>
            {lastRun
              ? "Workflow output is available below."
              : "No run yet."}
          </span>
        </div>
        {lastRun ? (
          <RunResultView
            projectRoot={projectRoot}
            runId={lastRun.run_id}
            onError={setError}
          />
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
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
  }, [setError]);

  useEffect(() => {
    if (!projectRoot) {
      setRuns(null);
      setSelectedRunId(null);
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

  return (
    <>
      <section className="panel" aria-labelledby="history-heading">
        <div className="panel-heading">
          <h2 id="history-heading">Run history</h2>
          <span>{projectRoot}</span>
        </div>
        <RunHistoryPanel runs={runs} onSelect={setSelectedRunId} />
      </section>
      {selectedRunId && (
        <RunResultView
          projectRoot={projectRoot}
          runId={selectedRunId}
          onError={setError}
        />
      )}
    </>
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
