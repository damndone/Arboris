import { useEffect, useMemo, useState } from "react";
import { type RunSummary } from "./api";

const PAGE_SIZE = 25;

type Props = {
  runs: RunSummary[] | null;
  onSelect: (runId: string) => void;
  /** v1.6.5 — the resolved project_root does not exist yet (e.g. a stale
   *  `lastProjectRoot` from a previous session). Show a friendly empty state
   *  instead of a raw red "Request error" banner. */
  projectMissing?: boolean;
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

export function RunHistoryPanel({ runs, onSelect, projectMissing }: Props) {
  const [page, setPage] = useState(1);

  const totalPages = runs ? Math.max(1, Math.ceil(runs.length / PAGE_SIZE)) : 1;

  const pageRuns = useMemo(() => {
    if (!runs) return null;
    const start = (page - 1) * PAGE_SIZE;
    return runs.slice(start, start + PAGE_SIZE);
  }, [runs, page]);

  // Reset to page 1 when runs change
  useEffect(() => {
    setPage(1);
  }, [runs]);

  if (projectMissing) {
    return (
      <div className="muted" data-testid="history-project-missing">
        <p>This project doesn't exist yet.</p>
        <p>
          Pick an existing project folder above, or submit a run to create it —
          your last-used path may be stale.
        </p>
      </div>
    );
  }
  if (runs === null) {
    return <p className="muted">Loading runs…</p>;
  }
  if (runs.length === 0) {
    return <p className="muted">No runs in this project yet.</p>;
  }

  return (
    <>
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
          {pageRuns!.map((run) => (
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
      {runs.length > PAGE_SIZE && (
        <nav className="pagination" aria-label="run history pagination">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </button>
          <span className="pagination-info">
            Page {page} of {totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </nav>
      )}
    </>
  );
}
