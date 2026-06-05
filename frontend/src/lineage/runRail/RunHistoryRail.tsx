/* RunHistoryRail.tsx — V1.5.1 T3'.
 *
 * Left rail showing recent runs for the current project. Replaces the
 * deferred 8-stage navigation rail from the original spec §6 (now
 * V1.5.2 followup at docs/superpowers/followups/v1.5.2-stage-navigation.md).
 *
 * Visual: 240px wide column flush with the lineage canvas. Each row is
 * a button with short run id + relative time + status pill. Current run
 * (URL :runId) gets aria-current="true" + active background.
 *
 * Click: navigates to /runs/<id>?project_root=…&tab=lineage.
 *
 * Empty / loading / error states render inline text rather than
 * banners — the rail's signature visual is the list, and the user is
 * already on a run page so a giant "Loading…" splash would be silly.
 */
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMemo } from "react";
import { useRunHistory } from "./useRunHistory";
import type { RunSummary } from "../../api";

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const delta = Date.now() - t;
  const s = Math.round(delta / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

function shortRunId(id: string): string {
  // Workbench run ids look like: 20260525_210044_142101_055d5cbd
  // The last 8-char hex segment is the unique tail; render that.
  const tail = id.split("_").pop() ?? id;
  return tail.slice(0, 8);
}

function statusClass(status: string): string {
  switch (status) {
    case "completed":
    case "ok":
      return "run-rail__pill run-rail__pill--ok";
    case "failed":
    case "error":
      return "run-rail__pill run-rail__pill--red";
    case "blocked":
      return "run-rail__pill run-rail__pill--warn";
    case "running":
      return "run-rail__pill run-rail__pill--info";
    default:
      return "run-rail__pill run-rail__pill--neutral";
  }
}

export interface RunHistoryRailProps {
  /** Optional override. When omitted, reads `project_root` from URL. */
  projectRoot?: string | null;
}

export function RunHistoryRail({ projectRoot: projectRootProp }: RunHistoryRailProps = {}): JSX.Element {
  const { runId: activeRunId } = useParams<{ runId: string }>();
  const [searchParams] = useSearchParams();
  const projectRoot = projectRootProp ?? searchParams.get("project_root");
  const navigate = useNavigate();
  const { runs, loading, error } = useRunHistory(projectRoot);

  const sorted = useMemo(() => {
    // Newest first — backend already does this, but defend against
    // ordering changes by sorting on `started_at` here too.
    return [...runs].sort((a, b) => {
      const at = a.started_at ? Date.parse(a.started_at) : 0;
      const bt = b.started_at ? Date.parse(b.started_at) : 0;
      return bt - at;
    });
  }, [runs]);

  const onPick = (r: RunSummary) => {
    if (!projectRoot) return;
    navigate(
      `/runs/${encodeURIComponent(r.run_id)}?project_root=${encodeURIComponent(
        projectRoot,
      )}&tab=lineage`,
    );
  };

  return (
    <aside
      className="run-rail"
      data-testid="run-rail"
      aria-label="Run history"
    >
      <header className="run-rail__header">
        <h3 className="run-rail__title">Runs</h3>
        {projectRoot && (
          <Link
            to={`/runs?project_root=${encodeURIComponent(projectRoot)}`}
            className="run-rail__viewall"
          >
            View all
          </Link>
        )}
      </header>
      {loading && sorted.length === 0 && (
        <p className="run-rail__empty">Loading…</p>
      )}
      {!loading && sorted.length === 0 && !error && (
        <p className="run-rail__empty">No runs yet.</p>
      )}
      {error && sorted.length === 0 && (
        <p className="run-rail__empty">Couldn't load runs.</p>
      )}
      {sorted.length > 0 && (
        <ul className="run-rail__list" role="list">
          {sorted.map((r) => {
            const isActive = r.run_id === activeRunId;
            return (
              <li key={r.run_id}>
                <button
                  type="button"
                  className="run-rail__row"
                  data-testid={`run-rail-row-${r.run_id}`}
                  data-active={isActive ? "true" : undefined}
                  aria-current={isActive ? "true" : undefined}
                  onClick={() => onPick(r)}
                  title={`${r.run_id}\nstatus: ${r.status}\nstarted: ${
                    r.started_at ?? "—"
                  }`}
                >
                  <span className="run-rail__id">{shortRunId(r.run_id)}</span>
                  <span className="run-rail__time">
                    {formatRelativeTime(r.started_at)}
                  </span>
                  <span className={statusClass(r.status)}>{r.status}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
