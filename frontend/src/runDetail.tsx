import { useEffect, useState } from "react";
import {
  ApiError,
  fetchRunDetail,
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
    </section>
  );
}
