import { useMemo, useState } from "react";
import { ApiError, createProject, runWorkflow, type RunResponse } from "./api";
import "./styles.css";

type RequestState = "idle" | "working";

const RUN_OUTPUT_PATHS = [
  "run_manifest.json",
  "artifacts_index.json",
  "errors.json",
  "reports/report.html",
  "reports/report.pdf",
  "exports/tables.xlsx"
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

export default function App() {
  const [parent, setParent] = useState("");
  const [name, setName] = useState("demo");
  const [projectRoot, setProjectRoot] = useState("");
  const [mode, setMode] = useState("auto");
  const [y, setY] = useState("");
  const [x, setX] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activity, setActivity] = useState<string>("Idle");

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
    setErrorMessage(null);
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
      setErrorMessage(message);
      setActivity("Project creation failed");
    } finally {
      setRequestState("idle");
    }
  }

  async function onRun() {
    if (!file) return;
    setRequestState("working");
    setErrorMessage(null);
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
    } catch (error) {
      const message =
        error instanceof ApiError
          ? `[HTTP ${error.status}] ${error.message}`
          : error instanceof Error
            ? error.message
            : "Workflow request failed";
      setErrorMessage(message);
      setActivity("Workflow request failed");
    } finally {
      setRequestState("idle");
    }
  }

  const runDir = lastRun ? joinPath(projectRoot, `runs/${lastRun.run_id}`) : null;
  const badgeClass = lastRun
    ? `badge badge-${lastRun.status === "completed" ? "ok" : lastRun.status === "blocked" ? "warn" : "neutral"}`
    : "badge badge-neutral";

  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <h1>Local Econometrics Workbench</h1>
        <span
          className={`activity ${requestState === "working" ? "activity-working" : ""}`}
          aria-live="polite"
        >
          {activity}
        </span>
      </header>

      {errorMessage && (
        <section className="panel panel-error" role="alert">
          <strong>Request error</strong>
          <p>{errorMessage}</p>
        </section>
      )}

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
            {lastRun ? "Outputs are written under the run directory." : "No run yet."}
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
                  <span className={badgeClass}>{statusLabel(lastRun.status)}</span>
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
          <p className="muted">Submit a workflow to see run details and output paths.</p>
        )}
      </section>
    </main>
  );
}
