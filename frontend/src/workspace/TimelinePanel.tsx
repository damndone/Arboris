import {useCallback, useEffect, useState} from 'react';
import {apiUrl, readResponse} from '../api';
import type {Schema} from '../apiTypes';
import {useCompletedOperation} from '../workbench/agent/useCompletedOperation';

type Disclosure = Schema<'AnalysisDisclosure'>;
export function useTimeline(projectRoot: string, runId: string) {
  const completedOperation = useCompletedOperation();
  const [value, setValue] = useState<Disclosure | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(n => n + 1), []);
  useEffect(() => {
    let live = true;
    setValue(null); setError(null);
    fetch(apiUrl(`/runs/${encodeURIComponent(runId)}/analysis-disclosure?project_root=${encodeURIComponent(projectRoot)}`))
      .then(response => readResponse<Disclosure>(response))
      .then(result => {if (live) setValue(result);})
      .catch(reason => {if (live) setError(reason instanceof Error ? reason.message : String(reason));});
    return () => {live = false;};
  }, [projectRoot, runId, revision, completedOperation]);
  return {value, error, refresh};
}
export function eventSummary(entry: Disclosure['entries'][number]): string {
  const summary = entry.summary.trim();
  // Ledger summaries may contain an entire serialized patch. Keep that in Source.
  return summary && !/^(?:[{[]|draft=)/.test(summary) ? summary : entry.what.replace(/[._]/g, ' ');
}
export function timelineSummary(value: Disclosure | null): string {
  if (!value) return 'Analysis history';
  const latest = value.entries[value.entries.length - 1];
  return `${latest ? eventSummary(latest) : 'Analysis history'} · ${value.counts.inferential_tests} tests · ${value.counts.models} models · ${value.counts.data_changes} data changes`;
}
export function TimelinePanel({value, error, onRefresh}: {value: Disclosure | null; error: string | null; onRefresh: () => void}) {
  return <section aria-label="Analysis timeline">
    <div className="manual-actions"><h2>Timeline</h2><button type="button" onClick={onRefresh}>Refresh timeline</button></div>
    <p>{timelineSummary(value)}</p>
    {error && <p role="alert">{error}</p>}
    {!value && !error && <p role="status">Loading analysis history…</p>}
    {value && <><ol>{value.entries.map((entry, index) => <li key={`${entry.at}:${index}`}>
      <time dateTime={entry.at ?? undefined}>{entry.at ? new Date(entry.at).toLocaleString() : 'Time not recorded'}</time>
      {' · '}{entry.who === 'ui' ? 'Manual' : entry.who} · {entry.status ?? 'Recorded'}
      <p>{eventSummary(entry)}</p>
      <details><summary>Source</summary><code>{entry.what}</code><pre>{entry.summary}</pre></details>
    </li>)}</ol>{value.entries_omitted > 0 && <p>{value.entries_omitted} earlier entries omitted from this bounded view.</p>}</>}
  </section>;
}
