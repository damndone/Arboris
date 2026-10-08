// v1.9.0 — Runs, in the bottom panel (design spec §8.3 #2). The classic run
// history rail as a table: same list, status, time and View all; choosing a
// run opens it the way the rail did.

import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMemo } from "react";
import type { RunSummary } from "../api";
import { useForest } from "../workbench/ForestContext";
import { useRunHistory } from "../lineage/runRail/useRunHistory";
import { formatRelativeTime, shortRunId, statusClass } from "../lineage/runRail/runFormat";

function contents(run: RunSummary): string {
  if (!run.y) return run.mode ?? "—";
  const predictors = (run.x ?? []).join(", ");
  return predictors ? `${run.y} on ${predictors}` : run.y;
}

export function RunsTable({ projectRoot }: { projectRoot: string }) {
  const { runs, loading, error } = useRunHistory(projectRoot);
  const activeRunId = useForest()?.activeRunId ?? null;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const sorted = useMemo(
    () =>
      runs
        .filter((run) => typeof run.run_id === "string" && run.run_id.length > 0)
        .sort((a, b) => (b.started_at ? Date.parse(b.started_at) : 0) - (a.started_at ? Date.parse(a.started_at) : 0)),
    [runs],
  );

  const open = (run: RunSummary) => {
    const params = new URLSearchParams({ project_root: projectRoot, tab: "lineage" });
    const view = searchParams.get("view");
    if (view) params.set("view", view);
    navigate(`/runs/${encodeURIComponent(run.run_id)}?${params.toString()}`);
  };

  if (error) return <p className="ws-runs__note" role="alert">Runs could not be loaded: {error.message}</p>;
  if (loading && sorted.length === 0) return <p className="ws-runs__note">Loading runs…</p>;
  if (sorted.length === 0) return <p className="ws-runs__note">No runs yet. Start one with New analysis.</p>;

  return (
    <div className="ws-runs">
      <table className="ws-runs__table">
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Started</th>
            <th scope="col">Contains</th>
            <th scope="col">Status</th>
            <th scope="col"><span className="ws-visually-hidden">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((run) => {
            const active = run.run_id === activeRunId;
            return (
              <tr key={run.run_id} aria-current={active ? "true" : undefined} data-testid={`ws-run-${run.run_id}`}>
                <td className="ws-runs__id" title={run.run_id}>{shortRunId(run.run_id)}</td>
                <td title={run.started_at ?? undefined}>{formatRelativeTime(run.started_at)}</td>
                <td className="ws-runs__contents">{contents(run)}</td>
                <td><span className={statusClass(run.status)}>{run.status ?? "unknown"}</span></td>
                <td className="ws-runs__action">
                  {active ? (
                    <span className="ws-runs__current">Showing</span>
                  ) : (
                    <button type="button" className="ws-runs__open" onClick={() => open(run)}>
                      Show on map
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <Link className="ws-runs__all" to={`/runs?project_root=${encodeURIComponent(projectRoot)}`}>
        View all runs
      </Link>
    </div>
  );
}
