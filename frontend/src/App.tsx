import { useState } from "react";
import { createProject, runWorkflow } from "./api";
import "./styles.css";

type RequestState = "idle" | "working" | "error";

export default function App() {
  const [parent, setParent] = useState("");
  const [name, setName] = useState("demo");
  const [projectRoot, setProjectRoot] = useState("");
  const [mode, setMode] = useState("auto");
  const [y, setY] = useState("");
  const [x, setX] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("No run yet");
  const [requestState, setRequestState] = useState<RequestState>("idle");

  async function onCreateProject() {
    setRequestState("working");
    try {
      const result = await createProject(parent, name);
      setProjectRoot(result.project_root);
      setStatus("Project ready");
      setRequestState("idle");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Project creation failed");
      setRequestState("error");
    }
  }

  async function onRun() {
    if (!file) {
      return;
    }
    setRequestState("working");
    setStatus("Running workflow");
    try {
      const result = await runWorkflow(projectRoot, mode, y, x, file);
      setStatus(`${result.status}: ${result.run_id}`);
      setRequestState("idle");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Workflow failed");
      setRequestState("error");
    }
  }

  const canCreate = parent.trim() !== "" && name.trim() !== "";
  const canRun =
    projectRoot.trim() !== "" && y.trim() !== "" && x.trim() !== "" && file !== null;

  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <div>
          <p className="eyebrow">Local analysis</p>
          <h1>Local Econometrics Workbench</h1>
        </div>
        <div className={`status-pill ${requestState}`} aria-live="polite">
          {status}
        </div>
      </header>

      <section className="panel" aria-labelledby="project-heading">
        <div className="panel-heading">
          <h2 id="project-heading">Project</h2>
          <span>Choose a local parent folder and project name.</span>
        </div>
        <div className="control-grid">
          <label>
            Parent folder
            <input
              aria-label="parent folder"
              placeholder="/path/to/workspace"
              value={parent}
              onChange={(event) => setParent(event.target.value)}
            />
          </label>
          <label>
            Project name
            <input
              aria-label="project name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <button disabled={!canCreate || requestState === "working"} onClick={onCreateProject}>
            Create project
          </button>
        </div>
        <dl className="summary-list">
          <div>
            <dt>Project root</dt>
            <dd>{projectRoot || "Not created"}</dd>
          </div>
        </dl>
      </section>

      <section className="panel" aria-labelledby="run-heading">
        <div className="panel-heading">
          <h2 id="run-heading">Run</h2>
          <span>Upload one CSV and run the workflow.</span>
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
            Dependent variable
            <input
              aria-label="dependent variable"
              placeholder="y"
              value={y}
              onChange={(event) => setY(event.target.value)}
            />
          </label>
          <label>
            Independent variables
            <input
              aria-label="independent variables"
              placeholder="x1, x2"
              value={x}
              onChange={(event) => setX(event.target.value)}
            />
          </label>
          <label>
            Data file
            <input
              aria-label="data file"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button disabled={!canRun || requestState === "working"} onClick={onRun}>
            Run workflow
          </button>
        </div>
      </section>
    </main>
  );
}
