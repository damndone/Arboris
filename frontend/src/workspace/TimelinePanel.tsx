// v1.9.0 — the analysis timeline in the bottom panel. The ledger is the
// record; each entry reads as a sentence (timeline/timelineEvents.ts) with
// who acted and when, newest first, and the raw ledger event one click away.

import { useCallback, useEffect, useState } from "react";
import { apiUrl, readResponse } from "../api";
import { useCompletedOperation } from "../workbench/agent/useCompletedOperation";
import { describeEvent, describeWho, summarizeTimeline, type Disclosure } from "./timeline/timelineEvents";
import "./timeline/timeline.css";

export { summarizeTimeline as timelineSummary };

export function useTimeline(projectRoot: string, runId: string) {
  const completedOperation = useCompletedOperation();
  const [value, setValue] = useState<Disclosure | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  const subject = `${projectRoot}\n${runId}`;
  // A different run starts empty; a refresh of the same run keeps the list
  // on screen until the new one arrives instead of flashing "Loading".
  const [shown, setShown] = useState(subject);
  if (shown !== subject) {
    setShown(subject);
    setValue(null);
  }
  useEffect(() => {
    let live = true;
    setError(null);
    fetch(apiUrl(`/runs/${encodeURIComponent(runId)}/analysis-disclosure?project_root=${encodeURIComponent(projectRoot)}`))
      .then((response) => readResponse<Disclosure>(response))
      .then((result) => live && setValue(result))
      .catch((reason) => live && setError(reason instanceof Error ? reason.message : String(reason)));
    return () => {
      live = false;
    };
  }, [projectRoot, runId, revision, completedOperation]);
  return { value, error, refresh };
}

const timeFormat = new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const dayFormat = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });

function when(at: string | null): { label: string; day: string } {
  if (!at) return { label: "—", day: "" };
  const date = new Date(at);
  return { label: timeFormat.format(date), day: dayFormat.format(date) };
}

export function TimelinePanel({ value, error, onRefresh }: { value: Disclosure | null; error: string | null; onRefresh: () => void }) {
  if (error) {
    return (
      <div className="ws-timeline__note" role="alert">
        Could not load the history: {error}{" "}
        <button type="button" className="ws-timeline__retry" onClick={onRefresh}>Try again</button>
      </div>
    );
  }
  if (!value) return <p className="ws-timeline__note" role="status">Loading analysis history…</p>;
  if (value.entries.length === 0) return <p className="ws-timeline__note">Nothing has happened in this analysis yet.</p>;

  const entries = [...value.entries].reverse();
  let lastDay = "";
  return (
    <section className="ws-timeline" aria-label="Analysis timeline">
      <ol className="ws-timeline__list">
        {entries.map((entry, index) => {
          const time = when(entry.at);
          const showDay = time.day !== lastDay;
          lastDay = time.day;
          const failed = entry.status === "failed";
          return (
            <li key={`${entry.at}:${index}`} className="ws-timeline__entry" data-failed={failed || undefined}>
              <time className="ws-timeline__time" dateTime={entry.at ?? undefined} title={entry.at ? new Date(entry.at).toLocaleString("en") : undefined}>
                {showDay && <span className="ws-timeline__day">{time.day}</span>}
                {time.label}
              </time>
              <span className="ws-timeline__dot" aria-hidden="true" />
              <div className="ws-timeline__main">
                <p className="ws-timeline__what">
                  {describeEvent(entry)}
                  {failed && <span className="ws-timeline__failed">Failed</span>}
                </p>
                <details className="ws-timeline__details">
                  <summary>
                    <span className="ws-timeline__who">{describeWho(entry.who)}</span>
                    <span className="ws-timeline__more">Details</span>
                  </summary>
                  <dl>
                    <dt>Event</dt>
                    <dd><code>{entry.what}</code></dd>
                    <dt>Recorded by</dt>
                    <dd>{entry.who}</dd>
                    {entry.summary && (
                      <>
                        <dt>Record</dt>
                        <dd><pre>{entry.summary}</pre></dd>
                      </>
                    )}
                  </dl>
                </details>
              </div>
            </li>
          );
        })}
      </ol>
      {value.entries_omitted > 0 && (
        <p className="ws-timeline__note">
          {value.entries_omitted} earlier {value.entries_omitted === 1 ? "entry is" : "entries are"} not shown.
        </p>
      )}
    </section>
  );
}
