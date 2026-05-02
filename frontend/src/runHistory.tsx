import { useEffect, useState } from "react";
import {
  ApiError,
  fetchRuns,
  type RunSummary,
} from "./api";

type Props = {
  projectRoot: string;
  onSelect: (runId: string) => void;
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

export function RunHistoryPanel({ projectRoot, onSelect, onError }: Props) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRuns(projectRoot)
      .then((response) => {
        if (cancelled) return;
        setRuns(response.runs);
      })
      .catch((error) => {
        if (cancelled) return;
        const message =
          error instanceof ApiError
            ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
            : error instanceof Error
              ? error.message
              : "Failed to load runs";
        onError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, onError]);

  if (runs === null) {
    return <p className="muted">Loading runs…</p>;
  }
  if (runs.length === 0) {
    return <p className="muted">No runs in this project yet.</p>;
  }

  return (
    <table className="runs-table" aria-label="run history">
      <thead>
        <tr>
          <th>Run ID</th>
          <th>Status</th>
          <th>Mode</th>
          <th>Started</th>
          <th>Y</th>
          <th>X</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr
            key={run.run_id}
            onClick={() => onSelect(run.run_id)}
            className="runs-row"
          >
            <td className="mono">{run.run_id}</td>
            <td>
              <span className={statusBadgeClass(run.status)}>
                {statusLabel(run.status)}
              </span>
            </td>
            <td>{run.mode ?? "—"}</td>
            <td>{run.started_at ?? "—"}</td>
            <td>{run.y ?? "—"}</td>
            <td>{(run.x ?? []).join(", ") || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
