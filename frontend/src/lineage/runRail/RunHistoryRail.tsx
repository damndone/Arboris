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
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { useRunHistory } from "./useRunHistory";
import type { RunSummary } from "../../api";
import { useProjectRootOptional } from "../../workbench/ProjectRootContext";
import { useRailRefreshToken } from "../../workbench/RailRefreshContext";

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

const MIN_RAIL_WIDTH = 160;
const DEFAULT_RAIL_WIDTH = 240;
const MAX_RAIL_WIDTH = 480;
const RAIL_OPEN_KEY_PREFIX = "workbench:runRailOpen:";

function clampRailWidth(width: number): number {
  if (!Number.isFinite(width)) return DEFAULT_RAIL_WIDTH;
  return Math.min(MAX_RAIL_WIDTH, Math.max(MIN_RAIL_WIDTH, Math.round(width)));
}

function readRailOpen(storageKey: string): boolean {
  const raw = sessionStorage.getItem(storageKey);
  return raw === null ? true : raw !== "false";
}

export function readRunHistoryOpen(projectRoot?: string | null): boolean {
  return readRailOpen(`${RAIL_OPEN_KEY_PREFIX}${projectRoot ?? "default"}`);
}

export function persistRunHistoryOpen(projectRoot: string | null | undefined, open: boolean): void {
  sessionStorage.setItem(`${RAIL_OPEN_KEY_PREFIX}${projectRoot ?? "default"}`, String(open));
}

function readRailWidth(storageKey: string): number {
  const raw = sessionStorage.getItem(storageKey);
  return raw === null ? DEFAULT_RAIL_WIDTH : clampRailWidth(Number(raw));
}

export interface RunHistoryRailProps {
  /** Optional override. When omitted, reads `project_root` from URL. */
  projectRoot?: string | null;
  /** Controlled shell state; keeps the visible control in the topbar. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function RunHistoryRail({
  projectRoot: projectRootProp,
  open: controlledOpen,
  onOpenChange,
}: RunHistoryRailProps = {}): JSX.Element {
  const { runId: activeRunId } = useParams<{ runId: string }>();
  const [searchParams] = useSearchParams();
  const contextProjectRoot = useProjectRootOptional();
  const projectRoot = projectRootProp ?? contextProjectRoot ?? searchParams.get("project_root");
  const navigate = useNavigate();
  const { runs, loading, error, refresh } = useRunHistory(projectRoot);
  const widthStorageKey = `workbench:runRailWidth:${projectRoot ?? "default"}`;
  const openStorageKey = `${RAIL_OPEN_KEY_PREFIX}${projectRoot ?? "default"}`;
  const [railWidth, setRailWidth] = useState(() => readRailWidth(widthStorageKey));
  const [storedRailOpen, setStoredRailOpen] = useState(() => readRailOpen(openStorageKey));
  const railOpen = controlledOpen ?? storedRailOpen;
  const isControlled = controlledOpen !== undefined;
  const dragStart = useRef<{ x: number; width: number; pointerId: number } | null>(null);

  useEffect(() => {
    setRailWidth(readRailWidth(widthStorageKey));
    if (!isControlled) setStoredRailOpen(readRailOpen(openStorageKey));
  }, [isControlled, openStorageKey, widthStorageKey]);

  const commitRailWidth = useCallback((nextWidth: number) => {
    const clamped = clampRailWidth(nextWidth);
    setRailWidth(clamped);
    sessionStorage.setItem(widthStorageKey, String(clamped));
  }, [widthStorageKey]);

  const setRailOpen = useCallback((nextOpen: boolean) => {
    if (!isControlled) setStoredRailOpen(nextOpen);
    persistRunHistoryOpen(projectRoot, nextOpen);
    onOpenChange?.(nextOpen);
  }, [isControlled, onOpenChange, projectRoot]);

  const onRailResizeStart = useCallback((event: PointerEvent<HTMLDivElement>) => {
    dragStart.current = {
      x: event.clientX,
      width: railWidth,
      pointerId: event.pointerId,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }, [railWidth]);

  const onRailResizeMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const start = dragStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    commitRailWidth(start.width + event.clientX - start.x);
  }, [commitRailWidth]);

  const onRailResizeEnd = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const start = dragStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dragStart.current = null;
  }, []);

  // v1.6.9 B1-4 — refresh the moment a pending run (genesis / draft-execute)
  // indexes, instead of waiting out the 30s poll. ForestWorkbench bumps the
  // RailRefreshContext token in its onIndexed callbacks; each change past the
  // initial mount value triggers an immediate re-fetch. The first-render skip
  // keeps mount behavior identical to today (no double fetch), and providerless
  // paths (LegacyGraphWorkbench, standalone routes) hold the default token 0
  // forever — the effect never fires there, so the rail behaves exactly as before.
  const railRefreshToken = useRailRefreshToken();
  const firstTokenRef = useRef(true);
  useEffect(() => {
    if (firstTokenRef.current) {
      firstTokenRef.current = false;
      return;
    }
    refresh();
  }, [railRefreshToken, refresh]);

  const sorted = useMemo(() => {
    // Newest first — backend already does this, but defend against
    // ordering changes by sorting on `started_at` here too.
    //
    // Drop runs with no id first: a run we cannot key, navigate to, or label is
    // not listable, and one malformed run directory must not take the whole
    // workbench down with it (this rail renders inside the shell).
    return runs
      .filter((r) => typeof r.run_id === "string" && r.run_id.length > 0)
      .sort((a, b) => {
      const at = a.started_at ? Date.parse(a.started_at) : 0;
      const bt = b.started_at ? Date.parse(b.started_at) : 0;
      return bt - at;
    });
  }, [runs]);

  const onPick = (r: RunSummary) => {
    if (!projectRoot) return;
    // Preserve the current view (Graph/Table) so switching runs while on the
    // Table doesn't kick the user back to the Graph view.
    const params = new URLSearchParams({ project_root: projectRoot, tab: "lineage" });
    const view = searchParams.get("view");
    if (view) params.set("view", view);
    navigate(`/runs/${encodeURIComponent(r.run_id)}?${params.toString()}`);
  };

  return (
    <>
      <aside
        className={`run-rail${railOpen ? "" : " run-rail--collapsed"}`}
        data-testid="run-rail"
        data-open={railOpen ? "true" : "false"}
        aria-label="Run history"
        style={railOpen
          ? { width: railWidth, flexBasis: railWidth }
          : { width: 0, flexBasis: 0 }}
      >
      {railOpen && (
        <>
          <header className="run-rail__header run-rail__header--compact">
            <h3 className="run-rail__title">Runs</h3>
            {projectRoot && (
              <Link
                to={`/runs?project_root=${encodeURIComponent(projectRoot)}`}
                className="run-rail__viewall"
              >
                View all
              </Link>
            )}
            <button
              type="button"
              className="run-rail__toggle"
              aria-label="Close run history"
              title="Close run history"
              onClick={() => setRailOpen(false)}
              style={{
                marginLeft: "auto",
                width: 24,
                height: 24,
                border: "1px solid var(--separator)",
                borderRadius: 6,
                background: "transparent",
                color: "var(--label-secondary)",
                cursor: "pointer",
                fontSize: 11,
                lineHeight: 1,
              }}
            >
              <span aria-hidden="true">◀</span>
            </button>
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
                      className="run-rail__row run-rail__row--compact"
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
        </>
      )}
      {!railOpen && !isControlled && (
        <button
          type="button"
          className="run-rail__reopen run-rail__reopen--square"
          aria-label="Open run history"
          title="Show runs"
          onClick={() => setRailOpen(true)}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="2.5" stroke="currentColor" strokeWidth="1.6" />
            <line x1="9" y1="4" x2="9" y2="20" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </button>
      )}
      </aside>
      {railOpen ? (
        <div
          role="separator"
          aria-label="Resize run history rail"
          aria-orientation="vertical"
          aria-valuemin={MIN_RAIL_WIDTH}
          aria-valuemax={MAX_RAIL_WIDTH}
          aria-valuenow={railWidth}
          data-testid="run-rail-resizer"
          tabIndex={0}
          onPointerDown={onRailResizeStart}
          onPointerMove={onRailResizeMove}
          onPointerUp={onRailResizeEnd}
          onPointerCancel={onRailResizeEnd}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight") {
              event.preventDefault();
              commitRailWidth(railWidth + 24);
            }
            if (event.key === "ArrowLeft") {
              event.preventDefault();
              commitRailWidth(railWidth - 24);
            }
          }}
          className="run-rail__resizer"
        />
      ) : null}
    </>
  );
}
