import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  artifactDownloadUrl,
  connectRunEvents,
  fetchRunArtifacts,
  fetchRunDetail,
  reportUrl,
  type ArtifactGroup,
  type IssueRecord,
  type RunDetail,
} from "./api";

type Props = {
  projectRoot: string;
  runId: string;
  onError: (message: string) => void;
};

function statusBadgeClass(status: string): string {
  if (status === "completed") return "badge badge-ok";
  if (status === "blocked" || status === "failed") return "badge badge-warn";
  return "badge badge-neutral";
}

function statusLabel(status: string): string {
  if (!status) return "—";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatNumber(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(4)
    : "—";
}

function coefficientRows(detail: RunDetail) {
  return (detail.model_results ?? []).flatMap((model) =>
    Object.entries(model.coefficients ?? {})
      .filter(([term]) => term !== "Intercept" && !term.startsWith("C("))
      .map(([term, coefficient]) => ({
        modelId: model.model_id,
        term,
        estimate: coefficient.estimate,
        stdError: coefficient.std_error,
        pValue: coefficient.p_value,
      })),
  );
}

type ArtifactsState =
  | { status: "loading" }
  | { status: "loaded"; groups: ArtifactGroup[] }
  | { status: "error"; message: string };

type StepStatus = "pending" | "running" | "completed" | "blocked";
type StepProgress = { step: string; label: string; status: StepStatus };

const PROGRESS_STEPS: StepProgress[] = [
  { step: "ingestion", label: "Ingestion", status: "pending" },
  { step: "schema", label: "Schema", status: "pending" },
  { step: "cleaning", label: "Cleaning", status: "pending" },
  { step: "profiling", label: "Profiling", status: "pending" },
  { step: "validation", label: "Validation", status: "pending" },
  { step: "routing", label: "Routing", status: "pending" },
  { step: "model_check", label: "Model check", status: "pending" },
  { step: "estimation", label: "Estimation", status: "pending" },
  { step: "visualization", label: "Visualization", status: "pending" },
  { step: "narrative", label: "Narrative", status: "pending" },
  { step: "reporting", label: "Reporting", status: "pending" },
  { step: "export", label: "Export", status: "pending" },
];

export function RunResultView({ projectRoot, runId, onError }: Props) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [artifactsState, setArtifactsState] = useState<ArtifactsState>({
    status: "loading",
  });
  const [showReport, setShowReport] = useState(false);
  const [progressSteps, setProgressSteps] =
    useState<StepProgress[]>(PROGRESS_STEPS);
  const [isLive, setIsLive] = useState(false);
  const fetchIdRef = useRef(0);

  const fetchArtifacts = useCallback(() => {
    const id = ++fetchIdRef.current;
    setArtifactsState({ status: "loading" });
    fetchRunArtifacts(projectRoot, runId)
      .then((value) => {
        if (id !== fetchIdRef.current) return;
        setArtifactsState({ status: "loaded", groups: value.groups });
      })
      .catch((error) => {
        if (id !== fetchIdRef.current) return;
        const message =
          error instanceof ApiError
            ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
            : error instanceof Error
              ? error.message
              : "Unknown error";
        setArtifactsState({ status: "error", message });
      });
  }, [projectRoot, runId]);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    fetchRunDetail(projectRoot, runId)
      .then((value) => {
        if (cancelled) return;
        setDetail(value);
      })
      .catch((error) => {
        if (cancelled) return;
        const message =
          error instanceof ApiError
            ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
            : error instanceof Error
              ? error.message
              : "Failed to load run detail";
        onError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, onError]);

  useEffect(() => {
    fetchArtifacts();
    return () => {
      fetchIdRef.current += 1;
    };
  }, [fetchArtifacts]);

  useEffect(() => {
    if (!detail || detail.status !== "running") return;
    setIsLive(true);

    const cleanup = connectRunEvents(projectRoot, runId, {
      onStepStart: (step) => {
        setProgressSteps((prev) =>
          prev.map((s) => (s.step === step ? { ...s, status: "running" } : s)),
        );
      },
      onStepComplete: (step) => {
        setProgressSteps((prev) =>
          prev.map((s) =>
            s.step === step ? { ...s, status: "completed" } : s,
          ),
        );
      },
      onStepBlocked: (step) => {
        setProgressSteps((prev) =>
          prev.map((s) => (s.step === step ? { ...s, status: "blocked" } : s)),
        );
      },
      onTerminal: () => {
        setIsLive(false);
        fetchRunDetail(projectRoot, runId).then(setDetail).catch(() => {});
        fetchArtifacts();
      },
      onError: () => {
        setIsLive(false);
      },
    });
    return cleanup;
  }, [detail?.status, projectRoot, runId, fetchArtifacts]);

  if (detail === null) {
    return <p className="muted">Loading run…</p>;
  }

  const issues: IssueRecord[] = detail.errors?.issues ?? [];
  const coefficients = coefficientRows(detail);

  return (
    <section className="result-panel" aria-labelledby="run-detail-heading">
      <div className="panel-heading">
        <h2 id="run-detail-heading">Run detail</h2>
        <span className={statusBadgeClass(detail.status)}>
          {statusLabel(detail.status)}
        </span>
      </div>
      {isLive && (
        <section className="progress-panel" aria-label="run progress">
          <h3 className="subhead">Progress</h3>
          <ol className="progress-list">
            {progressSteps.map((s) => (
              <li key={s.step} className={`progress-step ${s.status}`}>
                <span className={`progress-dot ${s.status}`} />
                {s.label}
              </li>
            ))}
          </ol>
        </section>
      )}

      <dl className="summary-list">
        <div>
          <dt>Run ID</dt>
          <dd className="mono">{detail.run_id}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={statusBadgeClass(detail.status)}>
              {statusLabel(detail.status)}
            </span>
          </dd>
        </div>
        <div>
          <dt>Mode</dt>
          <dd>{detail.mode ?? "—"}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{detail.started_at ?? "—"}</dd>
        </div>
        <div>
          <dt>Y</dt>
          <dd>{detail.y ?? "—"}</dd>
        </div>
        <div>
          <dt>X</dt>
          <dd>{(detail.x ?? []).join(", ") || "—"}</dd>
        </div>
      </dl>
      <h3 className="subhead">Artifact counts</h3>
      <ul className="path-list" aria-label="artifact counts">
        {Object.entries(detail.artifact_counts).map(([type, count]) => (
          <li key={type} className="mono">
            {type}: {count}
          </li>
        ))}
      </ul>
      {coefficients.length > 0 && (
        <section aria-labelledby="coefficients-heading">
          <h3 id="coefficients-heading" className="subhead">
            Coefficients
          </h3>
          <div className="coefficients-table-wrap">
            <table className="coefficients-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Term</th>
                  <th>Estimate</th>
                  <th>Std. error</th>
                  <th>p-value</th>
                </tr>
              </thead>
              <tbody>
                {coefficients.map((row) => (
                  <tr key={`${row.modelId}:${row.term}`}>
                    <td>{row.modelId}</td>
                    <td>{row.term}</td>
                    <td>{formatNumber(row.estimate)}</td>
                    <td>{formatNumber(row.stdError)}</td>
                    <td>{formatNumber(row.pValue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {issues.length > 0 && (
        <section className="panel panel-error" role="alert">
          <strong>Issues</strong>
          <ul>
            {issues.map((issue, index) => (
              <li key={index}>
                <strong>{issue.code ?? "ISSUE"}</strong>:{" "}
                <span>{issue.message ?? ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-labelledby="report-heading">
        <h3 id="report-heading" className="subhead">
          Report
        </h3>
        <button type="button" onClick={() => setShowReport((value) => !value)}>
          {showReport ? "Hide report" : "View report"}
        </button>
        <a
          className="report-link"
          href={reportUrl(projectRoot, runId)}
          target="_blank"
          rel="noreferrer"
        >
          Open in new tab
        </a>
        {showReport && (
          <iframe
            title="Run report"
            src={reportUrl(projectRoot, runId)}
            className="report-frame"
            sandbox="allow-same-origin"
          />
        )}
      </section>
      <section aria-labelledby="artifacts-heading">
        <h3 id="artifacts-heading" className="subhead">
          Artifacts
        </h3>
        {artifactsState.status === "loading" && (
          <p className="muted">Loading artifacts…</p>
        )}
        {artifactsState.status === "loaded" &&
          artifactsState.groups.length === 0 && (
            <p className="muted">No artifacts recorded.</p>
          )}
        {artifactsState.status === "loaded" &&
          artifactsState.groups.length > 0 &&
          artifactsState.groups.map((group) => (
            <div key={group.artifact_type} className="artifact-group">
              <h4>{group.artifact_type}</h4>
              <ul>
                {group.items.map((item) => (
                  <li key={item.artifact_id}>
                    <a
                      href={artifactDownloadUrl(
                        projectRoot,
                        runId,
                        item.artifact_id,
                      )}
                    >
                      {item.artifact_id}
                    </a>
                    <span className="mono"> · {item.path}</span>
                    <span className="muted"> · {item.step}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        {artifactsState.status === "error" && (
          <div className="panel panel-error" role="alert">
            <p>Failed to load artifacts: {artifactsState.message}</p>
            <button type="button" onClick={fetchArtifacts}>
              Retry
            </button>
          </div>
        )}
      </section>
    </section>
  );
}
