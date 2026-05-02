import { useEffect, useState } from "react";
import {
  ApiError,
  artifactDownloadUrl,
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
  onBack: () => void;
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

export function RunDetailPanel({ projectRoot, runId, onBack, onError }: Props) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [groups, setGroups] = useState<ArtifactGroup[] | null>(null);
  const [showReport, setShowReport] = useState(false);

  useEffect(() => {
    let cancelled = false;
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
    let cancelled = false;
    fetchRunArtifacts(projectRoot, runId)
      .then((value) => {
        if (cancelled) return;
        setGroups(value.groups);
      })
      .catch(() => {
        if (cancelled) return;
        setGroups([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId]);

  if (detail === null) {
    return <p className="muted">Loading run…</p>;
  }

  const issues: IssueRecord[] = detail.errors?.issues ?? [];

  return (
    <section className="panel" aria-labelledby="run-detail-heading">
      <div className="panel-heading">
        <h2 id="run-detail-heading">Run detail</h2>
        <button type="button" onClick={onBack}>
          Back to history
        </button>
      </div>
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
          />
        )}
      </section>
      <section aria-labelledby="artifacts-heading">
        <h3 id="artifacts-heading" className="subhead">
          Artifacts
        </h3>
        {groups === null ? (
          <p className="muted">Loading artifacts…</p>
        ) : groups.length === 0 ? (
          <p className="muted">No artifacts recorded.</p>
        ) : (
          groups.map((group) => (
            <div key={group.artifact_type} className="artifact-group">
              <h4>{group.artifact_type}</h4>
              <ul>
                {group.items.map((item) => (
                  <li key={item.artifact_id}>
                    <a
                      href={artifactDownloadUrl(projectRoot, runId, item.artifact_id)}
                    >
                      {item.artifact_id}
                    </a>
                    <span className="mono"> · {item.path}</span>
                    <span className="muted"> · {item.step}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </section>
    </section>
  );
}
