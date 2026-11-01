import {useState} from 'react';
import type {PostEstimationResult} from '../../api';
import {formatEstimate, formatPValue} from '../../format/numbers';

/** Identifiers and hashes: they say which result this is, not what it found. */
const IDENTIFIER = /(?:^|_)(?:id|sha256|fingerprint|schema|version|contract)$|^model_type$/;
/** An exact fraction such as a certified bound: right for checking, unreadable as a number. */
const EXACT_FRACTION = /^-?\d{8,}\/\d+$/;
/** Longer than this is a record to inspect on request, not a value to read. */
const READABLE_CHARS = 240;

function valueText(key: string, value: unknown): string {
  if (value === null || value === undefined) return 'Not reported';
  if (typeof value === 'number') return /p_value$/.test(key) ? formatPValue(value) : formatEstimate(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.map(item => valueText(key, item)).join(', ');
  if (typeof value === 'object') return Object.entries(value).map(([field, item]) => `${field.replace(/_/g, ' ')}: ${valueText(field, item)}`).join('; ');
  return String(value);
}

const label = (key: string) => key.replace(/_/g, ' ');

interface Row {key: string; label: string; value: string}
interface Group {label: string; rows: Row[]}

/** What a person reads first; everything else stays one click away and is never dropped. */
export function readableFields(result: Record<string, unknown>): {rows: Row[]; groups: Group[]} {
  const rows: Row[] = [];
  const groups: Group[] = [];
  const place = (key: string, value: unknown, into: Row[]) => {
    if (IDENTIFIER.test(key) || (typeof value === 'string' && EXACT_FRACTION.test(value))) return;
    const text = valueText(key, value);
    if (text.length > READABLE_CHARS) {
      const status = value && typeof value === 'object' && 'status' in value ? (value as {status: unknown}).status : null;
      if (typeof status === 'string') into.push({key, label: label(key), value: status});
      return;
    }
    into.push({key, label: label(key), value: text});
  };
  for (const [key, value] of Object.entries(result)) {
    if (value && typeof value === 'object' && !Array.isArray(value) && valueText(key, value).length > READABLE_CHARS) {
      const inner: Row[] = [];
      for (const [field, item] of Object.entries(value)) place(field, item, inner);
      groups.push({label: label(key), rows: inner});
    } else {
      place(key, value, rows);
    }
  }
  return {rows, groups};
}

/** Rendered only once opened: one certificate can run to hundreds of kilobytes. */
export function TechnicalDetails({label: title, value}: {label: string; value: unknown}) {
  const [open, setOpen] = useState(false);
  return (
    <details className="ws-result-technical" onToggle={event => setOpen(event.currentTarget.open)}>
      <summary>{title}</summary>
      {open && <pre>{JSON.stringify(value, null, 2)}</pre>}
    </details>
  );
}

export function PostEstimationFields({entry}: {entry: PostEstimationResult}) {
  const {rows, groups} = readableFields(entry.result);
  const list = (items: Row[]) => (
    <dl>
      {items.map(row => <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
    </dl>
  );
  return (
    <>
      {rows.length > 0 && list(rows)}
      {groups.map(group => (
        <section key={group.label}>
          <h4>{group.label}</h4>
          {list(group.rows)}
        </section>
      ))}
      <TechnicalDetails label="Technical details" value={entry} />
    </>
  );
}

export function modelTests(entries: PostEstimationResult[], runId: string, modelId: string) {
  return entries.filter(entry => entry.model_run_id === runId && entry.result.model_id === modelId);
}
export function PostEstimationResults({entries}: {entries: PostEstimationResult[]}) {
  if (entries.length === 0) return <div aria-label="Saved model tests"><p>No saved tests for this model yet.</p></div>;
  return (
    <div aria-label="Saved model tests">
      {entries.map((entry) => (
        <article key={`${entry.run_id}:${entry.artifact_id}`}>
          <h3>{entry.title ?? entry.operation_id.replace(/^postestimation\./, '').replace(/[._]/g, ' ')}</h3>
          <PostEstimationFields entry={entry} />
        </article>
      ))}
    </div>
  );
}
